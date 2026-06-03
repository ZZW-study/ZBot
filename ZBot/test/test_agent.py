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