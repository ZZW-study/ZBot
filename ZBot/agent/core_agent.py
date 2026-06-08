"""主 Agent 会话处理模块。"""

from __future__ import annotations

import asyncio
import copy
import json
from typing import Any, Awaitable, Callable

from loguru import logger

from ZBot.agent.base_agent import BaseAgent
from ZBot.agent.context import ContextBuilder
from ZBot.agent.evolution.complexity import compute_complexity
from ZBot.agent.evolution.curator import SkillCurator
from ZBot.agent.evolution.metrics import record_evolution_event
from ZBot.agent.evolution.trajectory import SessionTrajectory, extract_trajectory
from ZBot.agent.evolution.usage_tracker import SkillUsageTracker
from ZBot.agent.subagent.subagent_pool import SubAgentPool
from ZBot.agent.tools.create_sub_agent import CreateSubAgentTool
from ZBot.agent.tools.filesystem import EditFileTool, WriteFileTool
from ZBot.agent.tools.skills import NewSkillsListLoader, SkillReader, SkillsManager
from ZBot.services.config.agent_runtime import AgentRuntimeConfig
from ZBot.cron.service import CronService
from ZBot.prompts.agent import SKILL_REVIEW_SYSTEM, build_skill_review_prompt, build_validation_feedback
from ZBot.providers.base import LLMProvider
from ZBot.services.task_validation import validate_before_task_complete_hook
from ZBot.session.manager import Session, SessionManager

_SKILL_REVIEW_SYSTEM = SKILL_REVIEW_SYSTEM


class CoreAgent(BaseAgent):
    """主 Agent：负责用户会话、记忆、工具调度和最终回复。"""

    def __init__(
        self,
        provider: LLMProvider,
        runtime_config: AgentRuntimeConfig,
        cron_service: CronService | None = None,
    ):
        """初始化主 Agent 的长期会话能力。"""
        super().__init__(
            provider=provider,
            runtime_config=runtime_config,
            cron_service=cron_service,
        )

        self.context = ContextBuilder(self.workspace)
        self.sessions = SessionManager(self.workspace)
        self.recent_history_token_budget_ratio = runtime_config.recent_history_token_budget_ratio
        self.recent_history_max_tokens = runtime_config.recent_history_max_tokens
        self.memory_consolidation_interval = runtime_config.memory_consolidation_interval
        self.session_memory_keep_recent_tokens = runtime_config.session_memory_keep_recent_tokens
        self._is_consolidating: bool = False
        self._consolidation_task: asyncio.Task[None] | None = None
        self.subagent_pool: SubAgentPool | None = None
        self.skill_review_complexity_threshold = runtime_config.skill_review_complexity_threshold  # 写skills的，写的阈值
        self.usage_tracker = SkillUsageTracker(self.workspace)
        self.curator = SkillCurator(
            skills_dir=self.workspace / "skills",
            usage_tracker=self.usage_tracker,
            workspace_path=self.workspace,
            catalog=self.context.skills,
        )
        self._register_core_tools()

    async def process_message(
        self,
        message: str | list[dict[str, Any]],
        session_name: str = "default",
        *,
        on_progress: Callable[..., Awaitable[None]],
    ) -> str:
        """处理一条用户消息，是 CLI 和上层调用 CoreAgent 的主入口。"""
        await self.connect_mcp()
        self.subagent_pool = self.ensure_subagent_pool()

        preview_message = self._message_preview(message)
        logger.info("正在处理消息：{}", preview_message[:80] + "..." if len(preview_message) > 80 else preview_message)

        session, is_load = await self.sessions.get_or_create(session_name)
        if is_load:
            logger.info("会话 '{}' 已加载，包含 {} 条历史消息", session_name, len(session.messages))
            if session.memory_snapshot:
                await self.context.session_memory.write_session_memory(session.memory_snapshot)

        self._schedule_consolidation(session)

        final_content = await self._run_turn(
            session,
            content=message,
            on_progress=on_progress,
        )
        preview = final_content[:120] + "..." if len(final_content) > 120 else final_content
        logger.info("回复：{}", preview)
        return final_content

    async def close_mcp(self) -> None:
        """关闭子 Agent 池、MCP 连接栈和使用追踪器。"""
        await self._cancel_consolidation_task()
        await self.usage_tracker.close()
        if self.subagent_pool is not None:
            await self.subagent_pool.close()
            self.subagent_pool = None
        if not self._mcp_stack:
            return
        try:
            await self._mcp_stack.aclose()
        except BaseException as exc:
            if not (isinstance(exc, RuntimeError) or exc.__class__.__name__ == "BaseExceptionGroup"):
                raise
        finally:
            self._mcp_stack = None
            self._mcp_connected = False

    async def consolidate_all_session_memory(self, session_name: str) -> None:
        """对指定会话执行完整会话记忆归档。"""
        session, _ = await self.sessions.get_or_create(session_name)
        await self.context.session_memory.consolidate(
            session,
            self.provider,
            self.model,
            keep_recent_tokens=self.session_memory_keep_recent_tokens,
            consolidate_all=True,
        )
        await self.sessions.save(session)

    async def consolidate_daily_memory(self, session_name: str) -> None:
        """把指定会话整理进日常记忆。"""
        session, _ = await self.sessions.get_or_create(session_name)
        consolidate_daily_memory_result = await self.context.daily_memory.add_daily_memory(
            self.provider,
            self.model,
            session,
        )
        if not consolidate_daily_memory_result:
            logger.error("日常记忆归档失败")
        else:
            logger.info("日常记忆归档成功")

    async def review_skills(self, session_name: str) -> None:
        """会话结束时回顾对话，进化技能库。"""
        session, _ = await self.sessions.get_or_create(session_name)
        messages = session.messages[session.last_consolidated :]
        if not messages:
            return

        # 复杂度门槛：简单任务不触发技能进化
        try:
            complexity = compute_complexity(messages, threshold=self.skill_review_complexity_threshold)
        except Exception:
            logger.exception("复杂度计算失败，跳过技能进化")
            return
        if not complexity.should_review:
            logger.info(
                "任务复杂度 {} 低于阈值 {}，跳过技能进化（工具调用: {}, 唯一工具: {}）",
                complexity.score,
                self.skill_review_complexity_threshold,
                complexity.tool_call_count,
                complexity.unique_tools,
            )
            return

        # 提取结构化轨迹替代原始 transcript
        trajectory = extract_trajectory(messages)

        # 跨会话模式注入：查询日常记忆中的技能相关模式
        cross_session_patterns = ""
        try:
            cross_session_patterns = await self.context.daily_memory.get_daily_memory_text(
                "最近会话中是否有工具调用失败、重试、或需要创建和更新技能的模式",
                score_threshold=0.6,
            )
        except Exception:
            logger.warning("跨会话模式查询失败，跳过")

        prompt = self._build_skill_review_prompt(trajectory, session.memory_snapshot or "", cross_session_patterns)

        # 只保留技能相关工具
        skill_tool_names = {"load_new_skills_list", "read_skill", "skills_manager"}
        skill_tools = [d for d in self.tools.get_definitions() if d.get("function", {}).get("name") in skill_tool_names]

        chat_messages: list[dict[str, Any]] = [
            {"role": "system", "content": _SKILL_REVIEW_SYSTEM},
            {"role": "user", "content": prompt},
        ]

        for _ in range(10):  # 最多 10 轮工具调用
            try:
                response = await asyncio.wait_for(
                    self.provider.chat(
                        messages=chat_messages,
                        tools=skill_tools,
                        model=self.model,
                    ),
                    timeout=120,
                )
            except asyncio.TimeoutError:
                logger.warning("技能进化审查 LLM 调用超时（120秒）")
                return
            except Exception:
                logger.exception("技能进化审查 LLM 调用失败")
                return

            if not response.has_tool_calls:
                final = response.content or ""
                if "Nothing to save" not in final:
                    logger.info("技能进化审查结果：{}", final[:200])
                return

            # 追加 assistant 消息（含 tool_calls）
            tool_call_dicts = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                    },
                }
                for tc in response.tool_calls
            ]
            self._add_assistant_message(chat_messages, response.content, tool_call_dicts)

            # 逐个执行工具并追加结果
            for tc in response.tool_calls:
                logger.info("技能审查调用工具：{}({})", tc.name, str(tc.arguments)[:100])
                result = await self.tools.execute(tc.name, tc.arguments)
                self._add_tool_result(chat_messages, tc.id, tc.name, result)

                # 记录技能使用事件和进化指标
                if tc.name == "skills_manager":
                    action = tc.arguments.get("action", "")
                    skill_name = tc.arguments.get("name", "")
                    if action in ("create", "patch") and skill_name:
                        await self.usage_tracker.record(skill_name, session_name, action)
                        await record_evolution_event(self.workspace, action, skill_name, session_name)

        logger.warning("技能进化审查达到最大轮次（10），强制结束")

    async def run_curator(self) -> None:
        """运行技能 Curator：健康检查 + 自动生命周期转换。"""
        try:
            report = await self.curator.run_maintenance()

            # 记录生命周期转换事件
            for skill_name, new_status in report.transitions_made:
                await record_evolution_event(self.workspace, new_status, skill_name)

            if report.transitions_made:
                logger.info(
                    "Curator 维护完成：{} 个技能状态转换",
                    len(report.transitions_made),
                )
            else:
                logger.debug("Curator 维护完成：无需转换")
        except Exception:
            logger.exception("Curator 维护失败")

    def _build_skill_review_prompt(
        self,
        trajectory: SessionTrajectory,
        memory_snapshot: str,
        cross_session_patterns: str = "",
    ) -> str:
        """构建技能进化审查的用户提示词（使用结构化轨迹替代原始 transcript）。"""
        steps_text = "\n".join(
            f"  {i + 1}. {s.tool_name}({'OK' if s.success else 'FAIL'}) — {s.arguments_summary}"
            + (f" → {s.result_summary[:100]}" if s.result_summary else "")
            for i, s in enumerate(trajectory.steps)
        )
        return build_skill_review_prompt(
            task_summary=trajectory.task_summary,
            memory_snapshot=memory_snapshot,
            steps_text=steps_text,
            step_count=len(trajectory.steps),
            tools_used=trajectory.tools_used,
            final_outcome=trajectory.final_outcome,
            error_pattern=trajectory.error_pattern,
            cross_session_patterns=cross_session_patterns,
        )



    def ensure_subagent_pool(self) -> SubAgentPool:
        """确保子 Agent 池已创建，并返回池实例。"""
        if self.subagent_pool is None:
            self.subagent_pool = SubAgentPool(self)
        return self.subagent_pool


    async def _save_task_progress_artifact(self, content: str) -> str | None:
        """上下文压缩前保存任务进度文件，避免长期状态只塞进 system 摘要。"""
        from ZBot.services.formatting import ensure_dir

        artifact_path = self.workspace / "memory" / "TASK_PROGRESS.md"
        ensure_dir(artifact_path.parent)
        try:
            await asyncio.to_thread(artifact_path.write_text, content, encoding="utf-8")
        except Exception:
            logger.exception("写入任务进度 artifact 失败")
            return None
        return str(artifact_path)


    def _register_core_tools(self) -> None:
        """注册只有主 Agent 才能使用的工具。"""
        sub_agent_tool = CreateSubAgentTool()
        sub_agent_tool.bind_agent(self)
        self.tools.register(sub_agent_tool)

        allowed_dir = self.workspace if self.restrict_to_workspace else None
        self.tools.register(WriteFileTool(workspace=self.workspace, allowed_dir=allowed_dir))
        self.tools.register(EditFileTool(workspace=self.workspace, allowed_dir=allowed_dir))

        from ZBot.agent.skills_load import BUILTIN_SKILLS_DIR

        skills_dir = self.workspace / "skills"
        self.tools.register(NewSkillsListLoader(skills_dir=skills_dir, builtin_skills_dir=BUILTIN_SKILLS_DIR))
        self.tools.register(
            SkillReader(
                skills_dir=skills_dir,
            )
        )
        self.tools.register(SkillsManager(skills_dir=skills_dir, catalog=self.context.skills))

    async def _run_turn(
        self,
        session: Session,
        *,
        content: str | list[dict[str, Any]],
        on_progress: Callable[..., Awaitable[None]],
    ) -> str:
        """执行一轮对话：构造上下文、运行 Agent loop、写回会话。

        H21: 用 try/except 包住 run_agent_loop 和 _complete_unfinished_task,
        任一环节抛异常时,仍然把已经积累的 all_messages 落盘 + 保存 session,
        保证用户的输入不会因为模型/工具异常而丢失上下文。
        """
        history: list[dict[str, Any]] = await session.get_history_by_token_budget(self._recent_history_token_budget(), self.provider, self.model)

        initial_messages: list[dict[str, Any]] = await self.context.build_messages(
            history=history,
            user_message=content,
            score_threshold=self.score_threshold,
        )

        final_content: str | None = None
        tools_used: list[str] = []
        all_messages: list[dict[str, Any]] = initial_messages
        try:
            final_content, tools_used, all_messages = await self.run_agent_loop(
                initial_messages,
                on_progress=on_progress,
            )
            final_content = final_content or "我已经完成处理，但没有需要额外返回的内容。"

            # 任务完成验证：最多重试3次，验证通过则保存并返回
            final_content, all_messages, retry_tools_used = await self._complete_unfinished_task(
                self._message_preview(content),
                final_content,
                all_messages,
                on_progress,
            )
            tools_used.extend(retry_tools_used)
            final_content = final_content or "我已经完成处理，但没有需要额外返回的内容。"
        except BaseException as exc:
            # 任意异常(包括 CancelledError)都要保存已积累的消息链,
            # 否则下次 turn 时用户的输入就丢了。
            logger.exception("Agent turn 异常,尽力保存当前进度: {}", exc)
            self._save_turn(session, all_messages, 1 + len(history), tools_used)
            try:
                await self.sessions.save(session)
            except Exception:
                logger.exception("保存 session 失败,用户消息可能丢失")
            raise
        self._save_turn(session, all_messages, 1 + len(history), tools_used)
        await self.sessions.save(session)
        return final_content

    def _schedule_consolidation(self, session: Session) -> None:
        """当未归档消息达到阈值时，安排后台会话记忆归档任务。"""
        unconsolidated = len(session.messages) - session.last_consolidated
        if unconsolidated < self.memory_consolidation_interval or self._is_consolidating:
            return

        async def _run_consolidation() -> None:
            """执行后台归档，并在结束时回收归档状态标记。"""
            try:
                await self.context.session_memory.consolidate(
                    session,
                    self.provider,
                    self.model,
                    keep_recent_tokens=self.session_memory_keep_recent_tokens,
                )
            finally:
                self._is_consolidating = False

        self._is_consolidating = True
        self._consolidation_task = asyncio.create_task(_run_consolidation())
        self._consolidation_task.add_done_callback(self._on_consolidation_done)

    def _on_consolidation_done(self, task: asyncio.Task[None]) -> None:
        """回收后台会话归档任务，记录异常，避免 create_task 静默泄漏。"""
        if self._consolidation_task is task:
            self._consolidation_task = None
        if task.cancelled():
            return
        try:
            task.result()
        except Exception:
            logger.exception("后台会话记忆归档失败")

    async def _cancel_consolidation_task(self) -> None:
        """关闭 Agent 时取消仍在运行的后台归档任务。"""
        task = self._consolidation_task
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        finally:
            if self._consolidation_task is task:
                self._consolidation_task = None
            self._is_consolidating = False


    def _recent_history_token_budget(self) -> int:
        """按模型上下文窗口计算短期历史预算，并设置 64K 默认硬上限。"""
        ratio_budget = int(self.context_window * self.recent_history_token_budget_ratio)
        return max(1, min(ratio_budget, self.recent_history_max_tokens))


    def _save_turn(
        self,
        session: Session,
        messages: list[dict[str, Any]],
        skip: int,
        tools_used: list[str] | None = None,
    ) -> None:
        """把本轮新增消息写回 session。"""
        from datetime import datetime

        turn_start = self._latest_user_message_index(messages, fallback=skip)
        turn_messages = [
            copy.deepcopy(message)
            for message in messages[turn_start:]
            if message.get("role") in {"user", "assistant", "tool"}
        ]
        self._annotate_tools_used(turn_messages, tools_used or [])

        for entry in turn_messages:
            role = entry.get("role")
            content = entry.get("content")

            if role == "assistant" and not content and not entry.get("tool_calls"):
                continue

            if role == "tool" and isinstance(content, str) and len(content) > self._TOOL_RESULT_MAX_CHARS:
                entry["content"] = content[: self._TOOL_RESULT_MAX_CHARS] + "\n……（内容已截断）"
            elif role == "user":
                entry["content"] = self._strip_runtime_context(content)

            entry.setdefault("timestamp", datetime.now().isoformat())
            session.messages.append(entry)

        session.updated_at = datetime.now()



    @staticmethod
    def _latest_user_message_index(messages: list[dict[str, Any]], *, fallback: int) -> int:
        """定位本轮用户消息，避免把内部 system 摘要或验收反馈写入会话历史。"""
        for index in range(len(messages) - 1, -1, -1):
            if messages[index].get("role") == "user":
                return index
        return max(0, min(fallback, len(messages)))



    @staticmethod
    def _strip_runtime_context(content: str | list[dict[str, Any]] | None) -> str | None | list[dict[str, Any]]:
        """剥离用户消息中的运行时上下文标签，并把大 base64 块改成轻量元信息。"""
        if not content:
            return content or ""

        if isinstance(content, list):
            return CoreAgent._sanitize_content_blocks(content)

        runtime_tag = ContextBuilder._RUNTIME_CONTEXT_TAG
        if content.startswith(runtime_tag):
            lines = content.split("\n\n", 1)
            if len(lines) > 1:
                return lines[1].strip()
            return ""

        return content



    @staticmethod
    def _sanitize_content_blocks(blocks: list[dict[str, Any]]) -> str:
        """保存历史时把多模态 blocks 转成文本摘要，避免 session 里残留 base64。"""
        texts: list[str] = []
        for block in blocks:
            block_copy = copy.deepcopy(block)
            if block_copy.get("type") == "text":
                text_value = CoreAgent._strip_runtime_context(str(block_copy.get("text") or ""))
                if isinstance(text_value, str):
                    text = text_value.strip()
                    if text:
                        texts.append(text)
            elif block_copy.get("type") == "image_url":
                image_url = block_copy.get("image_url")
                url = image_url.get("url") if isinstance(image_url, dict) else ""
                mime = CoreAgent._data_url_mime(url)
                texts.append(f"[已上传图片，MIME={mime or 'unknown'}，原始 data URL 未写入会话历史]")
            else:
                texts.append(f"[已上传内容块，type={block_copy.get('type', 'unknown')}，原始内容未写入会话历史]")
        return "\n\n".join(texts)



    @staticmethod
    def _data_url_mime(url: str | None) -> str | None:
        """从 data URL 中提取 MIME 类型。"""
        if not isinstance(url, str) or not url.startswith("data:") or ";base64," not in url:
            return None
        return url[5:].split(";base64,", 1)[0] or None

    @staticmethod
    def _message_preview(message: str | list[dict[str, Any]]) -> str:
        """生成适合日志、验收提示和错误信息使用的用户消息文本预览。"""
        if isinstance(message, str):
            return message
        texts: list[str] = []
        media_count = 0
        for block in message:
            if block.get("type") == "text":
                texts.append(str(block.get("text") or ""))
            else:
                media_count += 1
        suffix = f"\n[包含 {media_count} 个多模态内容块]" if media_count else ""
        return "\n".join(texts).strip() + suffix

    @staticmethod
    def _annotate_tools_used(messages: list[dict[str, Any]], tools_used: list[str]) -> None:
        """把本轮使用过的工具名挂到最后一条 assistant 消息上。"""
        if not tools_used:
            return

        unique_tools = list(dict.fromkeys(tools_used))
        for message in reversed(messages):
            if message.get("role") == "assistant":
                message["tools_used"] = unique_tools
                return

    async def _complete_unfinished_task(
        self,
        user_message: str,
        final_content: str,
        all_messages: list[dict[str, Any]],
        on_progress: Callable[..., Awaitable[None]],
        max_retries: int = 3,
    ) -> tuple[str, list[dict[str, Any]], list[str]]:
        """验证任务完成度，未完成则重试，直到通过或达到重试上限。"""

        retry_tools_used: list[str] = []
        for _ in range(max_retries):
            filter_message = self._recent_validation_evidence(all_messages)
            validate_result: dict[str, Any] = await validate_before_task_complete_hook(
                provider=self.provider,
                model=self.model,
                user_message=user_message,
                final_content=final_content,
                filter_message=filter_message,
            )

            if not validate_result:
                return final_content, all_messages, retry_tools_used
            if validate_result.get("completed") is True:
                return final_content, all_messages, retry_tools_used

            feedback = build_validation_feedback(validate_result)
            all_messages.append({"role": "system", "content": feedback})
            result, tools_used, retry_messages = await self.run_agent_loop(all_messages, on_progress=on_progress)
            retry_tools_used.extend(tools_used)
            all_messages = retry_messages
            final_content = result or "我已经完成处理，但没有需要额外返回的内容。"

        return final_content, all_messages, retry_tools_used

    @staticmethod
    def _recent_validation_evidence(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """提取最近一轮用户消息之后的 assistant/tool 证据，避免把整条历史交给验收器。"""
        start_index = 0
        for index in range(len(messages) - 1, -1, -1):
            if messages[index].get("role") == "user":
                start_index = index
                break

        evidence: list[dict[str, Any]] = []
        for message in messages[start_index:]:
            role = message.get("role")
            if role not in {"user", "assistant", "tool"}:
                continue
            entry: dict[str, Any] = {"role": role, "content": CoreAgent._evidence_content(message.get("content", ""))}
            if role == "tool":
                entry["name"] = message.get("name", "")
                entry["tool_call_id"] = message.get("tool_call_id", "")
            if role == "assistant" and message.get("tool_calls"):
                entry["tool_calls"] = message["tool_calls"]
            evidence.append(entry)
        return evidence

    @staticmethod
    def _evidence_content(content: Any) -> str:
        """把验收证据里的多模态内容转成文本，避免把 base64 交给验收器。"""
        if isinstance(content, list):
            return CoreAgent._sanitize_content_blocks(content)
        return str(content or "")
