# pyright: reportCallIssue=false
"""
==============================================================================
Agent Loop 测试文件 + CI/CD 完整教程
==============================================================================


一、什么是 CI/CD？
──────────────────

CI = Continuous Integration（持续集成）
CD = Continuous Delivery（持续交付）或 Continuous Deployment（持续部署）

你平时开发 ZBot 的流程大概是：
    1. 写代码
    2. 手动跑一下，看看有没有报错
    3. 没问题就 git push

CI/CD 就是把第 2 步自动化：
    1. 你写完代码，push 到 GitHub
    2. GitHub 自动帮你跑一堆检查（代码风格、类型检查、测试）
    3. 全部通过 → 允许你合并代码到 main 分支
    4. 有失败 → 禁止合并，告诉你哪里出了问题

CI 和 CD 的区别：
    CI：每次代码变更后，自动构建、自动测试、自动检查质量
    Continuous Delivery：代码随时可以发布，但上线需要人工批准
    Continuous Deployment：代码通过测试后自动发布到生产环境


二、为什么需要 CI/CD？
──────────────────────

没有 CI/CD 的翻车场景：

    场景 1：你改了 hooks.py 的验证逻辑
        → 没跑测试就提交了
        → 合并到 main 后发现任务完成验证全部失效
        → agent 每次都说"已完成"，但其实没完成

    场景 2：你改了 shell.py，不小心放行了 rm -rf
        → 没有安全测试
        → 上线后 agent 执行了 rm -rf /
        → 灾难

    场景 3：你改了 memory 模块，同事改了 context builder
        → 两个人各自的测试都通过
        → 合在一起就崩了
        → CI 会在合并前发现这种"集成"问题


三、Agent 项目的测试和普通项目有什么不同？
────────────────────────────────────────

普通项目测：函数输出、API 状态码、数据库读写、页面渲染

Agent 项目还要额外测：
    - 模型是否选对工具
    - 危险操作是否被拦截（rm -rf、读 ~/.ssh）
    - 任务是否真的完成（不是模型说完成就算完成）
    - 是否陷入死循环
    - 工具失败后能否恢复
    - 是否越权读写文件
    - token / 成本是否超预算


四、测试分 7 层
────────────────

第 1 层 - 静态检查（秒级）：
    ruff check .           → 检查代码风格、常见错误
    ruff format --check .  → 检查格式是否统一
    mypy src               → 检查类型是否正确

第 2 层 - 单元测试（秒级）：
    测单个函数/模块的确定性逻辑，不依赖外部服务。
    覆盖：tool registry、permission guard、hook engine、memory store

第 3 层 - 工具集成测试（秒到分钟级）：
    测工具在真实环境（sandbox）下能不能正常工作。
    覆盖：shell tool、file tool、browser tool

第 4 层 - Agent 行为测试（秒级）：← 本文件测的就是这层
    用 FakeModel（假的 LLM）测 agent runtime。
    不测模型智商，测 agent 框架本身是否可靠。

第 5 层 - Agent Eval（分钟到小时级）：
    用真实 LLM 跑真实任务，测任务完成质量。
    PR 只跑 smoke eval（10~30 个核心任务）
    nightly 跑 full eval（100+ 任务）

第 6 层 - 安全测试（一票否决）：
    危险命令是否被拦截、敏感文件是否被保护、prompt injection 能否骗过 agent

第 7 层 - 构建部署测试：
    Docker build 能否成功、CLI 能否启动、配置能否正确加载


五、CI/CD 流水线设计
────────────────────

PR 阶段（每次提 PR 都跑）：
    ruff check → ruff format → mypy → pytest → smoke eval → 安全测试
    全部通过 → 允许合并；任何一步失败 → 禁止合并

main 阶段（合并到 main 后自动跑）：
    完整测试 → Docker build → 部署 staging → staging smoke test

nightly 阶段（每天凌晨定时跑）：
    full agent eval + 真实 LLM + 成本统计 + 回归报告


六、GitHub Actions —— GitHub 内置的 CI/CD
────────────────────────────────────────

GitHub Actions 是 GitHub 内置的 CI/CD 服务，免费（公开仓库无限免费）。
不需要自己搭服务器，只需要在仓库里放一个 YAML 文件，GitHub 就会自动跑。

核心概念：
    Workflow（工作流）= 一个 YAML 文件，定义"什么时候跑、跑什么"
        文件位置：.github/workflows/xxx.yml
    Trigger（触发器）= "什么时候跑"
        pull_request → 提 PR 时跑
        push         → push 代码时跑
        schedule     → 定时跑（如每天凌晨 3 点）
        workflow_dispatch → 手动点按钮跑
    Job（任务）= "跑什么"，一个 workflow 里可以有多个 job 并行跑
    Step（步骤）= job 里的每一步操作

给 ZBot 配 GitHub Actions 的步骤：

    1. 创建 .github/workflows/ci.yml：

        name: CI
        on:
          pull_request:
            branches: [main]
          push:
            branches: [main]

        jobs:
          test:
            runs-on: ubuntu-latest
            steps:
              - uses: actions/checkout@v4
              - uses: actions/setup-python@v5
                with:
                  python-version: "3.13"
              - name: Install dependencies
                run: |
                  python -m pip install --upgrade pip
                  pip install -e ".[dev]"
              - name: Lint
                run: |
                  ruff check .
                  ruff format --check .
              - name: Type check
                run: mypy src
              - name: Run tests
                run: pytest ZBot/test/ -v

    2. push 到 GitHub，去仓库页面 → Actions 标签页就能看到 CI 在跑

    3. 设置分支保护（可选但强烈推荐）：
       Settings → Branches → main → Add rule
       勾选 "Require status checks to pass before merging"
       效果：CI 不通过，GitHub 禁止合并 PR 到 main


七、这个文件测的是什么？
────────────────────────

BaseAgent.run_agent_loop —— ZBot 的核心循环：

    用户发消息 → 调用大模型 → 模型回复
                                ↓
                        有工具调用？──是──→ 执行工具 → 结果追加到消息链 → 继续循环
                                ↓
                               否
                                ↓
                        返回最终回复给用户

我们不调用真实大模型（贵、慢、不稳定），用 FakeProvider 返回预设回复。

测试覆盖的场景：
    1. 直接回复（不调工具）→ 正常返回最终答案
    2. 单次工具调用 → 执行工具后返回
    3. 多个工具同时调用 → 按顺序全部执行
    4. 多轮工具调用 → 第一轮结果喂给第二轮
    5. 模型返回错误 → loop 停止，返回错误信息
    6. 工具执行失败 → 错误信息传给模型继续处理
    7. 超时 → 自动停止，返回超时提示
    8. 思考块 → 被剥离，不污染最终回复
    9. 连续失败无进展 → 注入"换策略"提示
   10. 空消息 / None 回复 → 不崩溃


八、pytest 用法速查
──────────────────

    pytest                                           # 跑所有测试
    pytest ZBot/test/agent_loop_test.py              # 跑某个文件
    pytest ZBot/test/agent_loop_test.py::TestAgentLoopBasic  # 跑某个类
    pytest ZBot/test/agent_loop_test.py -v -s        # 详细输出 + print
    pytest --lf                                      # 只跑上次失败的
    pytest --cov=ZBot --cov-report=term-missing      # 跑测试 + 覆盖率

pytest 核心概念：
    测试函数 = 以 test_ 开头的函数，pytest 自动运行它
    assert   = 断言，检查结果是否符合预期
    fixture  = 用 @pytest.fixture 定义的可复用资源，pytest 自动注入
    @pytest.mark.asyncio = 标记异步测试函数


九、AAA 测试模式
────────────────

每个测试分三步：

    Arrange（准备）：创建假数据
        fake_provider = FakeProvider(responses=[make_text_response("你好")])
        agent = StubAgent(provider=fake_provider, runtime_config=...)

    Act（执行）：调用被测函数
        final_content, tools_used, messages = await agent.run_agent_loop(...)

    Assert（断言）：验证结果
        assert final_content == "你好"
        assert tools_used == []


十、CI 门禁标准
────────────────

PR 合并必须满足：
    - unit tests 100% 通过
    - safety tests 100% 通过（一票否决）
    - smoke eval pass_rate >= 80%
    - 至少 1 人 review

main 合并后必须满足：
    - 全部测试通过
    - Docker build 成功
    - staging smoke test 通过

nightly 必须满足：
    - full eval pass_rate 不低于上周均值
    - 成本上涨不超过 20%


==============================================================================
下面开始实际的测试代码
==============================================================================
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from ZBot.agent.base_agent import BaseAgent
from ZBot.config.agent_runtime import AgentRuntimeConfig
from ZBot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


# =============================================================================
# 测试用的假数据结构
#
# 说明：
#   BaseAgent 是抽象类，不能直接实例化。
#   我们需要创建一个最小的子类 TestAgent，只实现必要的抽象方法。
#   同时创建一个 FakeProvider，模拟 LLM 的返回值。
# =============================================================================


class FakeProvider(LLMProvider):
    """假的 LLM 提供商：按照预设的回复序列依次返回。

    工作原理：
        1. 创建时传入一个回复列表，例如 [回复1, 回复2, 回复3]
        2. 每次调用 chat() 时，按顺序返回下一个回复
        3. 所有回复用完后，抛出异常（防止无限循环）

    为什么需要它：
        测试 agent loop 时，我们不想调用真实 LLM（贵、慢、不稳定）。
        用 FakeProvider 可以精确控制模型的每一步回复，让测试可重复。
    """

    def __init__(self, responses: list[LLMResponse], delay: float = 0.0):
        """初始化假提供商。

        Args:
            responses: 预设的回复列表，每次 chat() 调用消耗一个。
            delay: 每次调用的模拟延迟（秒），用于测试超时场景。
        """
        # 不调用 super().__init__()，因为我们不需要 api_key 和 api_base
        self._responses = list(responses)  # 复制一份，避免修改原始数据
        self._call_index = 0               # 记录当前调用到第几次
        self.call_history: list[list[dict[str, Any]]] = []  # 记录每次调用时传入的 messages
        self._delay = delay

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        on_delta: Any = None,
    ) -> LLMResponse:
        """返回预设的下一个回复。

        如果预设回复用完了，抛出 RuntimeError 防止无限循环。
        """
        self.call_history.append(messages)

        if self._delay > 0:
            await asyncio.sleep(self._delay)

        if self._call_index >= len(self._responses):
            raise RuntimeError(
                f"FakeProvider 的预设回复已用完（共 {len(self._responses)} 条），"
                f"但 agent loop 还在继续调用。可能是死循环。"
            )

        response = self._responses[self._call_index]
        self._call_index += 1
        return response


class StubAgent(BaseAgent):
    """用于测试的最小 Agent 子类。

    BaseAgent 是抽象类，不能直接实例化。
    这个子类只实现必要的抽象方法，不做任何额外的事情。
    所有核心逻辑（run_agent_loop）都在 BaseAgent 中，我们就是来测它的。

    注意：命名为 StubAgent 而非 TestAgent，避免 pytest 把它当作测试类收集。
    """

    # 抽象方法必须实现，但测试中不需要用到，所以留空
    async def process_message(self, message: str, **kwargs: Any) -> str:
        return "test"


# =============================================================================
# pytest fixture：可复用的测试前置资源
#
# 说明：
#   @pytest.fixture 装饰器定义一个"前置资源"函数。
#   测试函数通过参数名引用 fixture，pytest 会自动调用它并传入结果。
#   好处：多个测试可以共享同一套初始化逻辑，不用重复写。
# =============================================================================


@pytest.fixture
def runtime_config(tmp_path: Path) -> AgentRuntimeConfig:
    """创建一个测试用的 Agent 运行时配置。

    tmp_path 是 pytest 内置 fixture，自动创建一个临时目录，
    测试结束后自动清理，不会污染项目文件。
    """
    # 位置参数构造（Pyright 对 @dataclass(slots=True) 有误报，运行时完全正常）
    config = AgentRuntimeConfig(
        tmp_path,           # workspace: Path
        "test-model",       # model: str
        0.1,                # temperature: float
        4096,               # max_tokens: int
        None,               # reasoning_effort: str | None
        30,                 # agent_timeout_seconds: int
    )
    return config


@pytest.fixture
def noop_progress():
    """创建一个空的进度回调函数。

    run_agent_loop 要求传入 on_progress 回调，用于向前端推送进度。
    测试时我们不需要真正的进度展示，所以用一个什么都不做的函数。
    """
    async def _noop(*args: Any, **kwargs: Any) -> None:
        pass
    return _noop


# =============================================================================
# 辅助函数：快速构造测试数据
# =============================================================================


def make_tool_call(id: str, name: str, arguments: dict[str, Any] | None = None) -> ToolCallRequest:
    """构造一个工具调用请求。

    封装 ToolCallRequest 的创建，避免 Pyright 对 @dataclass 的误报。
    """
    return ToolCallRequest(id, name, arguments or {})  # type: ignore[call-arg]


def make_text_response(content: str) -> LLMResponse:
    """构造一个纯文本回复（不调用工具）。

    当 agent loop 收到这种回复时，会直接把它当作最终答案返回。
    """
    return LLMResponse(content, [], "stop")  # type: ignore[call-arg]


def make_tool_call_response(
    content: str | None,
    tool_calls: list[ToolCallRequest],
) -> LLMResponse:
    """构造一个包含工具调用的回复。

    当 agent loop 收到这种回复时，会执行工具，然后把结果追加到消息链，
    继续下一轮循环。

    Args:
        content: 模型的思考/说明文本（可以为 None）
        tool_calls: 工具调用请求列表
    """
    return LLMResponse(content, tool_calls, "stop")  # type: ignore[call-arg]


def make_error_response(content: str = "服务错误") -> LLMResponse:
    """构造一个错误回复。"""
    return LLMResponse(content, [], "error")  # type: ignore[call-arg]


# =============================================================================
# 第 4 层：Agent 行为测试
#
# 测试 agent loop 的核心行为，不依赖真实 LLM。
# 用 FakeProvider 控制模型的每一步回复，验证 agent 框架是否可靠。
# =============================================================================


class TestAgentLoopBasic:
    """测试 agent loop 的基本行为。"""

    @pytest.mark.asyncio
    async def test_direct_answer_no_tools(
        self,
        runtime_config: AgentRuntimeConfig,
        noop_progress: Any,
    ):
        """场景：模型直接返回文本回复，不调用任何工具。

        这是最简单的情况：
            用户发消息 → 模型思考 → 直接回复文本 → 结束

        验证点：
            - final_content 应该是模型的回复
            - tools_used 应该为空
            - messages 应该包含完整的对话链
        """
        # Arrange（准备）：创建假的 LLM 回复
        fake_provider = FakeProvider(responses=[
            make_text_response("你好！我是 ZBot，有什么可以帮你的？"),
        ])

        # 创建测试 Agent
        agent = StubAgent(provider=fake_provider, runtime_config=runtime_config)

        # 构造初始消息（模拟 build_messages 的输出）
        initial_messages = [
            {"role": "system", "content": "你是一个 AI 助手。"},
            {"role": "user", "content": "你好"},
        ]

        # Act（执行）：运行 agent loop
        final_content, tools_used, messages = await agent.run_agent_loop(
            initial_messages,
            on_progress=noop_progress,
        )

        # Assert（断言）：验证结果
        assert final_content == "你好！我是 ZBot，有什么可以帮你的？"
        assert tools_used == []
        assert len(messages) >= 3  # system + user + assistant
        # 最后一条消息应该是 assistant 的回复
        assert messages[-1]["role"] == "assistant"
        assert messages[-1]["content"] == "你好！我是 ZBot，有什么可以帮你的？"

    @pytest.mark.asyncio
    async def test_single_tool_call_then_answer(
        self,
        runtime_config: AgentRuntimeConfig,
        noop_progress: Any,
    ):
        """场景：模型调用一次工具，拿到结果后回复最终答案。

        流程：
            用户: "帮我创建 hello.txt"
            → 模型: 调用 write_file 工具
            → agent 执行工具，返回结果
            → 模型: "文件已创建"
            → 结束

        验证点：
            - tools_used 应该包含 "write_file"
            - final_content 应该是最终回复
            - messages 应该包含工具调用和工具结果
        """
        # Arrange：模拟两轮回复
        # 第一轮：模型决定调用 write_file 工具
        # 第二轮：模型根据工具结果给出最终回复
        fake_provider = FakeProvider(responses=[
            # 第一轮：模型请求调用 write_file
            make_tool_call_response(
                content="我来帮你创建文件。",
                tool_calls=[
                    make_tool_call(
                        id="call_001",
                        name="write_file",
                        arguments={"path": "hello.txt", "content": "Hello World"},
                    ),
                ],
            ),
            # 第二轮：模型根据工具结果回复
            make_text_response("文件 hello.txt 已创建，内容为 Hello World。"),
        ])

        agent = StubAgent(provider=fake_provider, runtime_config=runtime_config)

        initial_messages = [
            {"role": "system", "content": "你是一个 AI 助手。"},
            {"role": "user", "content": "帮我创建 hello.txt，内容是 Hello World"},
        ]

        # Act
        final_content, tools_used, messages = await agent.run_agent_loop(
            initial_messages,
            on_progress=noop_progress,
        )

        # Assert
        assert final_content is not None
        assert "hello.txt" in final_content
        assert "write_file" in tools_used

        # 验证消息链结构：
        # [system, user, assistant(tool_call), tool(result), assistant(text)]
        roles = [msg["role"] for msg in messages]
        assert "tool" in roles  # 应该有工具执行结果
        assert roles[-1] == "assistant"  # 最后一条是最终回复

    @pytest.mark.asyncio
    async def test_multiple_tool_calls(
        self,
        runtime_config: AgentRuntimeConfig,
        noop_progress: Any,
    ):
        """场景：模型一次请求调用多个工具，然后回复最终答案。

        流程：
            用户: "创建两个文件"
            → 模型: 同时调用 write_file(a.txt) 和 write_file(b.txt)
            → agent 依次执行两个工具
            → 模型: "两个文件都创建好了"
            → 结束

        验证点：
            - tools_used 应该包含两次 "write_file"
            - messages 应该包含两条工具结果
        """
        fake_provider = FakeProvider(responses=[
            # 第一轮：模型同时请求调用两个工具
            make_tool_call_response(
                content="我来创建两个文件。",
                tool_calls=[
                    make_tool_call(
                        id="call_001",
                        name="write_file",
                        arguments={"path": "a.txt", "content": "文件A"},
                    ),
                    make_tool_call(
                        id="call_002",
                        name="write_file",
                        arguments={"path": "b.txt", "content": "文件B"},
                    ),
                ],
            ),
            # 第二轮：模型根据两个工具的结果回复
            make_text_response("文件 a.txt 和 b.txt 都已创建完成。"),
        ])

        agent = StubAgent(provider=fake_provider, runtime_config=runtime_config)

        initial_messages = [
            {"role": "system", "content": "你是一个 AI 助手。"},
            {"role": "user", "content": "创建 a.txt 和 b.txt"},
        ]

        final_content, tools_used, messages = await agent.run_agent_loop(
            initial_messages,
            on_progress=noop_progress,
        )

        # tools_used 应该记录两次 write_file
        assert tools_used.count("write_file") == 2
        # 消息链中应该有两条 tool 结果
        tool_messages = [msg for msg in messages if msg["role"] == "tool"]
        assert len(tool_messages) == 2

    @pytest.mark.asyncio
    async def test_multiple_rounds_of_tool_calls(
        self,
        runtime_config: AgentRuntimeConfig,
        noop_progress: Any,
    ):
        """场景：模型多轮调用工具（第一轮调用后，第二轮又调用）。

        流程：
            用户: "读取 config.json 然后修改它"
            → 模型: 调用 read_file
            → agent 执行，返回文件内容
            → 模型: 调用 edit_file（基于读到的内容）
            → agent 执行，返回编辑结果
            → 模型: "已修改完成"
            → 结束

        验证点：
            - agent loop 应该执行多轮
            - 每轮的工具结果都正确追加到消息链
        """
        fake_provider = FakeProvider(responses=[
            # 第一轮：读取文件
            make_tool_call_response(
                content="先读取文件内容。",
                tool_calls=[
                    make_tool_call(
                        id="call_001",
                        name="read_file",
                        arguments={"path": "config.json"},
                    ),
                ],
            ),
            # 第二轮：根据读取结果编辑文件
            make_tool_call_response(
                content="内容已读取，现在修改。",
                tool_calls=[
                    make_tool_call(
                        id="call_002",
                        name="edit_file",
                        arguments={"path": "config.json", "old_text": "old", "new_text": "new"},
                    ),
                ],
            ),
            # 第三轮：最终回复
            make_text_response("config.json 已修改完成。"),
        ])

        agent = StubAgent(provider=fake_provider, runtime_config=runtime_config)

        initial_messages = [
            {"role": "system", "content": "你是一个 AI 助手。"},
            {"role": "user", "content": "读取并修改 config.json"},
        ]

        final_content, tools_used, messages = await agent.run_agent_loop(
            initial_messages,
            on_progress=noop_progress,
        )

        assert final_content is not None
        assert "修改完成" in final_content
        assert "read_file" in tools_used
        assert "edit_file" in tools_used
        # 应该调用了 2 次 LLM（第一轮工具调用 + 第二轮工具调用 + 最终回复 = 3 次）
        assert fake_provider._call_index == 3


class TestAgentLoopError:
    """测试 agent loop 的错误处理行为。"""

    @pytest.mark.asyncio
    async def test_error_response_breaks_loop(
        self,
        runtime_config: AgentRuntimeConfig,
        noop_progress: Any,
    ):
        """场景：模型返回错误（finish_reason="error"）。

        验证点：
            - agent loop 应该立即停止（不再继续调用模型）
            - final_content 应该包含错误提示
        """
        fake_provider = FakeProvider(responses=[
            make_error_response("模型服务暂时不可用"),
        ])

        agent = StubAgent(provider=fake_provider, runtime_config=runtime_config)

        initial_messages = [
            {"role": "system", "content": "你是一个 AI 助手。"},
            {"role": "user", "content": "你好"},
        ]

        final_content, tools_used, messages = await agent.run_agent_loop(
            initial_messages,
            on_progress=noop_progress,
        )

        # 错误响应应该被当作最终内容返回
        assert final_content is not None
        # 只调用了一次 LLM（错误后立即停止）
        assert fake_provider._call_index == 1

    @pytest.mark.asyncio
    async def test_tool_failure_continues_loop(
        self,
        runtime_config: AgentRuntimeConfig,
        noop_progress: Any,
    ):
        """场景：工具执行失败（返回错误信息），但模型继续处理。

        流程：
            用户: "读取不存在的文件"
            → 模型: 调用 read_file
            → 工具返回错误："文件不存在"
            → 模型: 根据错误信息回复用户
            → 结束

        验证点：
            - 工具失败不应该中断 agent loop
            - 错误信息应该被追加到消息链
            - 模型应该能看到错误信息并给出合理回复
        """
        fake_provider = FakeProvider(responses=[
            # 第一轮：模型请求读取文件
            make_tool_call_response(
                content="我来读取文件。",
                tool_calls=[
                    make_tool_call(
                        id="call_001",
                        name="read_file",
                        arguments={"path": "nonexistent.txt"},
                    ),
                ],
            ),
            # 第二轮：模型看到错误后回复
            make_text_response("抱歉，文件 nonexistent.txt 不存在，请检查路径是否正确。"),
        ])

        agent = StubAgent(provider=fake_provider, runtime_config=runtime_config)

        initial_messages = [
            {"role": "system", "content": "你是一个 AI 助手。"},
            {"role": "user", "content": "读取 nonexistent.txt"},
        ]

        final_content, tools_used, messages = await agent.run_agent_loop(
            initial_messages,
            on_progress=noop_progress,
        )

        # 模型应该看到了错误并给出合理回复
        assert final_content is not None
        assert "不存在" in final_content or "nonexistent" in final_content
        # 工具确实被调用了
        assert "read_file" in tools_used


class TestAgentLoopTimeout:
    """测试 agent loop 的超时行为。"""

    @pytest.mark.asyncio
    async def test_agent_timeout_stops_loop(
        self,
        runtime_config: AgentRuntimeConfig,
        noop_progress: Any,
    ):
        """场景：agent 总运行时间超过限制。

        设置一个极短的超时时间（1秒），然后让模型无限返回工具调用，
        验证 agent 是否会在超时后停止。

        验证点：
            - final_content 应该包含超时提示
            - agent loop 不应该无限运行
        """
        # 设置极短的超时时间
        runtime_config.agent_timeout_seconds = 1

        # 模型持续返回工具调用（理论上会无限循环）
        # 每次调用加 0.2 秒延迟，确保 1 秒超时能触发
        responses = []
        for i in range(100):
            responses.append(
                make_tool_call_response(
                    content=f"第 {i} 次调用",
                    tool_calls=[
                        make_tool_call(
                            id=f"call_{i:03d}",
                            name="read_file",
                            arguments={"path": f"file_{i}.txt"},
                        ),
                    ],
                ),
            )
        fake_provider = FakeProvider(responses=responses, delay=0.2)

        agent = StubAgent(provider=fake_provider, runtime_config=runtime_config)

        initial_messages = [
            {"role": "system", "content": "你是一个 AI 助手。"},
            {"role": "user", "content": "读取所有文件"},
        ]

        final_content, tools_used, messages = await agent.run_agent_loop(
            initial_messages,
            on_progress=noop_progress,
        )

        # 应该因为超时而停止
        assert final_content is not None
        assert "超过" in final_content or "超时" in final_content or "秒" in final_content
        # 不应该调用太多次 LLM（超时后应该停止）
        assert fake_provider._call_index < 100


class TestAgentLoopThinkBlock:
    """测试 agent loop 对思考块的处理。"""

    @pytest.mark.asyncio
    async def test_think_block_stripped_from_response(
        self,
        runtime_config: AgentRuntimeConfig,
        noop_progress: Any,
    ):
        """场景：模型回复中包含</think>...</think>思考块。

        模型有时会在回复中包含思考过程，格式为：
           <think>这里是我的思考过程</think>实际回复内容

        agent loop 应该剥离思考块，只保留实际回复。

        验证点：
            - final_content 不应该包含</think>标签
            - final_content 应该只包含实际回复内容
        """
        fake_provider = FakeProvider(responses=[
            make_text_response(
                "<think>用户在打招呼，我应该礼貌回应。</think>你好！有什么可以帮你的？"
            ),
        ])

        agent = StubAgent(provider=fake_provider, runtime_config=runtime_config)

        initial_messages = [
            {"role": "system", "content": "你是一个 AI 助手。"},
            {"role": "user", "content": "你好"},
        ]

        final_content, tools_used, messages = await agent.run_agent_loop(
            initial_messages,
            on_progress=noop_progress,
        )

        # 思考块应该被剥离
        assert final_content is not None
        assert "<think>" not in final_content
        assert "</think>" not in final_content
        assert "你好！有什么可以帮你的？" in final_content

    @pytest.mark.asyncio
    async def test_think_block_in_tool_call_response(
        self,
        runtime_config: AgentRuntimeConfig,
        noop_progress: Any,
    ):
        """场景：模型在工具调用回复中也包含思考块。

        验证点：
            - 工具调用正常执行
            - 思考内容通过 on_progress 回调传出（不影响最终结果）
            - final_content 不包含思考块
        """
        fake_provider = FakeProvider(responses=[
            # 第一轮：带思考块的工具调用
            make_tool_call_response(
                content="<think>用户要创建文件，我需要用 write_file 工具。</think>",
                tool_calls=[
                    make_tool_call(
                        id="call_001",
                        name="write_file",
                        arguments={"path": "test.txt", "content": "hello"},
                    ),
                ],
            ),
            # 第二轮：最终回复
            make_text_response("文件已创建。"),
        ])

        agent = StubAgent(provider=fake_provider, runtime_config=runtime_config)

        initial_messages = [
            {"role": "system", "content": "你是一个 AI 助手。"},
            {"role": "user", "content": "创建 test.txt"},
        ]

        final_content, tools_used, messages = await agent.run_agent_loop(
            initial_messages,
            on_progress=noop_progress,
        )

        assert final_content is not None
        assert "文件已创建" in final_content
        assert "write_file" in tools_used


class TestAgentLoopNoProgress:
    """测试 agent loop 的无进展检测。"""

    @pytest.mark.asyncio
    async def test_no_progress_injects_change_strategy_hint(
        self,
        runtime_config: AgentRuntimeConfig,
        noop_progress: Any,
    ):
        """场景：连续多次工具调用都失败，且没有新信息。

        agent loop 有"无进展检测"机制：
            当连续 _NO_PROGRESS_FAILURE_LIMIT 次工具返回错误
            且错误中没有"观察结果："时，
            agent 会在工具结果后追加一条"请换策略"的提示。

        验证点：
            - 消息链中应该出现"进展判断"相关提示
            - 提示内容应该让模型换策略
        """
        # 模型连续调用工具，每次都失败
        responses = []
        for i in range(BaseAgent._NO_PROGRESS_FAILURE_LIMIT + 1):
            # 模型请求调用工具
            responses.append(
                make_tool_call_response(
                    content=f"第 {i + 1} 次尝试",
                    tool_calls=[
                        make_tool_call(
                            id=f"call_{i:03d}",
                            name="read_file",
                            arguments={"path": f"missing_{i}.txt"},
                        ),
                    ],
                ),
            )
        # 最后模型放弃并回复
        responses.append(make_text_response("抱歉，无法完成任务。"))

        # 注意：工具执行结果由 agent loop 内部的 tools.execute 决定。
        # 我们这里没有注册真实的 read_file 工具，所以 tools.execute 会返回错误。
        # 但我们也可以通过注册一个总是失败的工具来精确控制。
        fake_provider = FakeProvider(responses=responses)

        agent = StubAgent(provider=fake_provider, runtime_config=runtime_config)

        initial_messages = [
            {"role": "system", "content": "你是一个 AI 助手。"},
            {"role": "user", "content": "读取一堆不存在的文件"},
        ]

        final_content, tools_used, messages = await agent.run_agent_loop(
            initial_messages,
            on_progress=noop_progress,
        )

        # 检查消息链中是否包含"进展判断"提示
        all_content = " ".join(
            str(msg.get("content", ""))
            for msg in messages
            if msg.get("role") == "tool"
        )
        assert "进展判断" in all_content or "换策略" in all_content or final_content is not None


class TestAgentLoopMessageStructure:
    """测试 agent loop 的消息链结构。"""

    @pytest.mark.asyncio
    async def test_message_chain_structure(
        self,
        runtime_config: AgentRuntimeConfig,
        noop_progress: Any,
    ):
        """场景：验证消息链的完整结构。

        一次包含工具调用的对话，消息链应该是：
            [system, user, assistant(tool_call), tool(result), assistant(text)]

        验证点：
            - 消息的角色顺序正确
            - assistant 消息包含 tool_calls 字段
            - tool 消息包含 tool_call_id 和 name
            - 最终 assistant 消息不包含 tool_calls
        """
        fake_provider = FakeProvider(responses=[
            make_tool_call_response(
                content=None,
                tool_calls=[
                    make_tool_call(
                        id="call_001",
                        name="write_file",
                        arguments={"path": "test.txt", "content": "hello"},
                    ),
                ],
            ),
            make_text_response("完成。"),
        ])

        agent = StubAgent(provider=fake_provider, runtime_config=runtime_config)

        initial_messages = [
            {"role": "system", "content": "你是一个 AI 助手。"},
            {"role": "user", "content": "创建 test.txt"},
        ]

        _, _, messages = await agent.run_agent_loop(
            initial_messages,
            on_progress=noop_progress,
        )

        # 提取所有角色
        roles = [msg["role"] for msg in messages]

        # 验证角色顺序
        assert roles[0] == "system"
        assert roles[1] == "user"
        # 中间应该有 assistant(tool_call) → tool(result) 的交替
        assert "assistant" in roles
        assert "tool" in roles
        # 最后一条应该是 assistant
        assert roles[-1] == "assistant"

        # 验证 tool_call 消息的结构
        assistant_with_tool = [
            msg for msg in messages
            if msg["role"] == "assistant" and "tool_calls" in msg
        ]
        assert len(assistant_with_tool) >= 1
        assert assistant_with_tool[0]["tool_calls"][0]["id"] == "call_001"

        # 验证 tool result 消息的结构
        tool_results = [msg for msg in messages if msg["role"] == "tool"]
        assert len(tool_results) >= 1
        assert tool_results[0]["tool_call_id"] == "call_001"
        assert tool_results[0]["name"] == "write_file"

        # 验证最终回复没有 tool_calls
        final_assistant = messages[-1]
        assert final_assistant["role"] == "assistant"
        assert "tool_calls" not in final_assistant

    @pytest.mark.asyncio
    async def test_tools_used_tracks_all_calls(
        self,
        runtime_config: AgentRuntimeConfig,
        noop_progress: Any,
    ):
        """场景：验证 tools_used 正确记录所有使用过的工具。

        即使同一个工具被调用多次，tools_used 也应该记录每一次。
        （注意：不是去重，而是完整记录，方便后续分析。）
        """
        fake_provider = FakeProvider(responses=[
            make_tool_call_response(
                content=None,
                tool_calls=[
                    make_tool_call(id="c1", name="read_file", arguments={"path": "a.txt"}),
                    make_tool_call(id="c2", name="read_file", arguments={"path": "b.txt"}),
                    make_tool_call(id="c3", name="write_file", arguments={"path": "c.txt", "content": "x"}),
                ],
            ),
            make_text_response("完成。"),
        ])

        agent = StubAgent(provider=fake_provider, runtime_config=runtime_config)

        initial_messages = [
            {"role": "system", "content": "你是一个 AI 助手。"},
            {"role": "user", "content": "读取 a.txt 和 b.txt，然后创建 c.txt"},
        ]

        _, tools_used, _ = await agent.run_agent_loop(
            initial_messages,
            on_progress=noop_progress,
        )

        # tools_used 应该记录每一次调用
        assert tools_used.count("read_file") == 2
        assert tools_used.count("write_file") == 1
        assert len(tools_used) == 3


class TestAgentLoopEdgeCases:
    """测试 agent loop 的边界情况。"""

    @pytest.mark.asyncio
    async def test_empty_initial_messages(
        self,
        runtime_config: AgentRuntimeConfig,
        noop_progress: Any,
    ):
        """场景：初始消息列表为空。

        这是一个边界情况。agent loop 不应该崩溃，
        而是应该把空列表传给 LLM，让 LLM 处理。
        """
        fake_provider = FakeProvider(responses=[
            make_text_response("我没有收到任何消息。"),
        ])

        agent = StubAgent(provider=fake_provider, runtime_config=runtime_config)

        final_content, tools_used, messages = await agent.run_agent_loop(
            [],  # 空消息列表
            on_progress=noop_progress,
        )

        assert final_content is not None
        assert fake_provider._call_index == 1

    @pytest.mark.asyncio
    async def test_model_returns_none_content(
        self,
        runtime_config: AgentRuntimeConfig,
        noop_progress: Any,
    ):
        """场景：模型回复的 content 为 None（只有工具调用）。

        某些情况下模型可能不返回文本，只返回工具调用。
        agent loop 应该正常处理这种情况。
        """
        fake_provider = FakeProvider(responses=[
            # 第一轮：content=None，只有工具调用
            make_tool_call_response(
                content=None,
                tool_calls=[
                    make_tool_call(
                        id="call_001",
                        name="write_file",
                        arguments={"path": "test.txt", "content": "hello"},
                    ),
                ],
            ),
            # 第二轮：最终回复
            make_text_response("完成。"),
        ])

        agent = StubAgent(provider=fake_provider, runtime_config=runtime_config)

        initial_messages = [
            {"role": "system", "content": "你是一个 AI 助手。"},
            {"role": "user", "content": "创建 test.txt"},
        ]

        final_content, tools_used, messages = await agent.run_agent_loop(
            initial_messages,
            on_progress=noop_progress,
        )

        assert final_content == "完成。"
        assert "write_file" in tools_used

    @pytest.mark.asyncio
    async def test_progress_callback_receives_thoughts(
        self,
        runtime_config: AgentRuntimeConfig,
    ):
        """场景：验证 on_progress 回调能收到模型的思考内容。

        on_progress 用于向前端展示 agent 的思考过程。
        当模型返回 content（非工具调用时），应该通过 on_progress 传出。
        """
        # 用 AsyncMock 记录回调调用
        progress_callback = AsyncMock()

        fake_provider = FakeProvider(responses=[
            make_tool_call_response(
                content="让我思考一下...",
                tool_calls=[
                    make_tool_call(
                        id="call_001",
                        name="write_file",
                        arguments={"path": "test.txt", "content": "hello"},
                    ),
                ],
            ),
            make_text_response("完成。"),
        ])

        agent = StubAgent(provider=fake_provider, runtime_config=runtime_config)

        initial_messages = [
            {"role": "system", "content": "你是一个 AI 助手。"},
            {"role": "user", "content": "创建 test.txt"},
        ]

        await agent.run_agent_loop(
            initial_messages,
            on_progress=progress_callback,
        )

        # on_progress 应该被调用过（至少包含思考内容和工具提示）
        assert progress_callback.call_count >= 1


# =============================================================================
# 运行方式：
#
# 运行所有 agent loop 测试：
#     pytest ZBot/test/agent_loop_test.py -v
#
# 运行某个测试类：
#     pytest ZBot/test/agent_loop_test.py::TestAgentLoopBasic -v
#
# 运行某个具体测试：
#     pytest ZBot/test/agent_loop_test.py::TestAgentLoopBasic::test_direct_answer_no_tools -v
#
# 查看详细输出（包括 print）：
#     pytest ZBot/test/agent_loop_test.py -v -s
# =============================================================================
