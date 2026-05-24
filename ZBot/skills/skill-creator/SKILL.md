---
name: skill-creator
description: "创建或更新 AgentSkills。用于设计、组织、打包带有 scripts、references、assets 的技能。"
---

# 技能创建器

这个技能用于指导你创建高质量技能。

## 什么是技能

技能是模块化、自包含的能力包，用专门的知识、工作流和工具扩展 Agent 的能力。可以把技能理解成某个领域或任务的“入门手册”：它让通用 Agent 变成具备过程性知识的专用 Agent，而这些过程性知识通常不是任何模型都能完整掌握的。

### 技能提供什么

1. 专门工作流：面向特定领域的多步骤流程。
2. 工具集成：使用特定文件格式或 API 的说明。
3. 领域知识：公司内部知识、schema、业务逻辑。
4. 打包资源：用于复杂或重复任务的脚本、参考资料和资产。

## 核心原则

### 简洁是关键

上下文窗口是公共资源。技能会和 system prompt、历史对话、其他技能元数据、用户真实请求一起共享上下文窗口。

**默认假设：Agent 已经很聪明。** 只加入 Agent 本来不知道、但确实需要的上下文。写每一段时都要问自己：“Agent 真的需要这段解释吗？”“这段内容值得消耗这些 token 吗？”

优先使用简洁示例，而不是冗长解释。

### 设置合适的自由度

技能的具体程度要匹配任务的脆弱性和变化程度：

**高自由度（文本说明）：** 适合多种做法都合理、决策依赖上下文、需要启发式判断的任务。

**中自由度（伪代码或带参数脚本）：** 适合已有推荐模式，但允许一定变化，或者配置会影响行为的任务。

**低自由度（具体脚本、少量参数）：** 适合容易出错、需要一致性、必须按特定顺序执行的任务。

可以这样理解：如果 Agent 在走一座两边是悬崖的窄桥，就需要明确护栏（低自由度）；如果是在开阔地里前进，就可以允许多条路线（高自由度）。

## 技能结构

每个技能由必需的 `SKILL.md` 和可选的打包资源组成：

```text
skill-name/
├── SKILL.md（必需）
│   ├── YAML frontmatter 元数据（必需）
│   │   ├── name:（必需）
│   │   └── description:（必需）
│   └── Markdown 使用说明（必需）
└── Bundled Resources（可选）
    ├── scripts/          - 可执行代码（Python/Bash 等）
    ├── references/       - 需要时加载进上下文的参考文档
    └── assets/           - 输出中会用到的文件（模板、图标、字体等）
```

### SKILL.md（必需）

每个 `SKILL.md` 都由两部分组成：

- **Frontmatter（YAML）：** 包含 `name` 和 `description` 字段。Agent 主要依靠这两个字段判断技能是否应该被使用，所以 `description` 必须清楚、完整地说明技能做什么、什么时候用。
- **Body（Markdown）：** 技能触发后才会加载的使用说明和操作指南。

### 打包资源（可选）

#### scripts/

`scripts/` 用于保存可执行代码（Python、Bash 等），适合需要确定性可靠性，或者经常被重复编写的任务。

适合加入脚本的场景：
- 同一段代码会被反复重写。
- 任务需要稳定、可复现的执行结果。
- 操作比较脆弱，手写容易错。

示例：
- `scripts/rotate_pdf.py`：用于 PDF 旋转任务。

优点：
- 节省 token。
- 行为更确定。
- 可以在不读入上下文的情况下直接执行。

注意：脚本有时仍然需要被 Agent 读取，用于修补或适配当前环境。

#### references/

`references/` 用于保存需要时才加载进上下文的文档和参考资料，帮助 Agent 正确思考和执行。

适合加入参考资料的场景：
- 数据库 schema。
- API 文档。
- 领域知识。
- 公司政策。
- 详细工作流指南。

示例：
- `references/finance.md`：财务 schema。
- `references/mnda.md`：公司 NDA 模板。
- `references/policies.md`：公司政策。
- `references/api_docs.md`：API 规格。

优点：
- 保持 `SKILL.md` 简洁。
- 只有 Agent 判断需要时才加载。
- 避免把大量细节常驻上下文。

最佳实践：
- 如果参考文件很大（超过 10k words），在 `SKILL.md` 中写明可用的 `grep` 搜索模式。
- 说明什么时候应该先用 `grep(output_mode="files_with_matches")`、`grep(output_mode="count")`、`grep(fixed_strings=true)`。
- 结果很多时，提示使用 `head_limit` / `offset` 分页。

避免重复：
- 同一信息不要同时写在 `SKILL.md` 和 references 里。
- 详细信息优先放进 references。
- `SKILL.md` 只保留必要流程、触发规则和导航说明。

#### assets/

`assets/` 用于保存不需要读入上下文、但会被最终输出使用的文件。

适合加入资产的场景：
- 最终产物需要复制或修改某些模板。
- 需要品牌图标、字体、图片、样例文件。
- 需要前端模板、PPT 模板、文档模板等。

示例：
- `assets/logo.png`：品牌资源。
- `assets/slides.pptx`：PowerPoint 模板。
- `assets/frontend-template/`：HTML/React 样板项目。
- `assets/font.ttf`：字体。

优点：
- 把输出资源和说明文档分离。
- Agent 可以使用文件，而不必把文件内容全部塞进上下文。

## 不应该放进技能的内容

技能应该只包含直接支持其功能的必要文件。不要创建无关文档或辅助文件，例如：

- `README.md`
- `INSTALLATION_GUIDE.md`
- `QUICK_REFERENCE.md`
- `CHANGELOG.md`
- 其他和执行技能无直接关系的说明文件

技能应该只包含 AI Agent 完成任务所需的信息。不要放创建过程说明、测试过程说明、面向用户的长文档等。额外文档只会增加混乱。

## 渐进式披露设计

技能使用三层加载机制来节省上下文：

1. **元数据（name + description）**：始终在上下文中，约 100 words。
2. **SKILL.md 正文**：技能触发后才加载，建议小于 5k words。
3. **打包资源**：Agent 需要时才加载或执行，脚本可以不进入上下文直接运行。

### 渐进式披露模式

`SKILL.md` 正文只保留核心内容，最好控制在 500 行以内。如果接近这个限制，把细节拆到其他文件里。

拆分文件时，必须在 `SKILL.md` 里明确引用这些文件，并说明什么时候读取它们。否则 Agent 可能不知道这些文件存在。

**核心原则：** 当一个技能支持多个变体、框架或选项时，`SKILL.md` 只放核心流程和选择指南。把具体变体的细节、模式、示例和配置放进单独的 reference 文件。

### 模式 1：高层指南 + references

```markdown
# PDF 处理

## 快速开始

用 pdfplumber 提取文本：
[代码示例]

## 高级功能

- **表单填写**：完整指南见 [FORMS.md](FORMS.md)
- **API 参考**：所有方法见 [REFERENCE.md](REFERENCE.md)
- **示例**：常见模式见 [EXAMPLES.md](EXAMPLES.md)
```

Agent 只在需要表单、API 参考或示例时，才加载对应文件。

### 模式 2：按领域组织

如果技能覆盖多个领域，按领域拆分，避免加载无关上下文：

```text
bigquery-skill/
├── SKILL.md（概览和导航）
└── reference/
    ├── finance.md（收入、账单指标）
    ├── sales.md（商机、销售管道）
    ├── product.md（API 使用、功能）
    └── marketing.md（活动、归因）
```

当用户询问销售指标时，Agent 只读取 `sales.md`。

如果技能支持多个云厂商或框架，也按变体拆分：

```text
cloud-deploy/
├── SKILL.md（工作流 + provider 选择）
└── references/
    ├── aws.md（AWS 部署模式）
    ├── gcp.md（GCP 部署模式）
    └── azure.md（Azure 部署模式）
```

用户选择 AWS 时，Agent 只读取 `aws.md`。

### 模式 3：条件细节

基础内容放在 `SKILL.md`，高级内容链接到 references：

```markdown
# DOCX Processing

## Creating documents

Use docx-js for new documents. See [DOCX-JS.md](DOCX-JS.md).

## Editing documents

For simple edits, modify the XML directly.

**For tracked changes**: See [REDLINING.md](REDLINING.md)
**For OOXML details**: See [OOXML.md](OOXML.md)
```

只有用户需要修订痕迹或 OOXML 细节时，Agent 才读取对应文件。

### 重要规则

- **避免深层嵌套 references**：reference 文件尽量只比 `SKILL.md` 深一层。所有 reference 都应能从 `SKILL.md` 直接找到。
- **长 reference 要有目录**：超过 100 行的 reference 文件，顶部应放目录，方便 Agent 预览范围。

## 技能创建流程

创建技能一般包含这些步骤：

1. 通过具体示例理解技能。
2. 规划可复用的技能内容（scripts、references、assets）。
3. 初始化技能（运行 `init_skill.py`）。
4. 编辑技能（实现资源并编写 `SKILL.md`）。
5. 打包技能（运行 `package_skill.py`）。
6. 根据真实使用反馈迭代。

按顺序执行这些步骤。只有在明确不适用时才跳过。

## 技能命名

- 只使用小写字母、数字和连字符；把用户提供的标题规范化为 hyphen-case，例如 `"Plan Mode"` -> `plan-mode`。
- 生成名称时，长度控制在 64 个字符以内。
- 优先使用简短、动词导向的名称，描述动作。
- 如果能提高可读性或触发准确性，可以按工具命名空间命名，例如 `gh-address-comments`、`linear-address-issue`。
- 技能目录名要和技能名完全一致。

## 第 1 步：通过具体示例理解技能

只有当技能的使用模式已经非常清楚时，才跳过这一步。即使是修改已有技能，这一步通常也有价值。

要创建有效技能，需要先理解它会如何被使用。这个理解可以来自用户给出的例子，也可以来自你生成的例子，再由用户反馈确认。

例如，创建 `image-editor` 技能时，可以问：

- “这个 image-editor 技能应该支持哪些功能？编辑、旋转，还有别的吗？”
- “能给几个这个技能会被如何使用的例子吗？”
- “我能想到用户可能会说‘去掉这张图里的红眼’或‘旋转这张图’。你还希望支持哪些说法？”
- “用户说什么时应该触发这个技能？”

不要一次问太多问题。先问最重要的问题，必要时再追问。

当你已经清楚技能应支持什么功能时，结束这一步。

## 第 2 步：规划可复用内容

把具体例子转化成有效技能时，对每个例子做分析：

1. 如果从零开始完成这个例子，该怎么做？
2. 哪些 scripts、references、assets 能让未来重复执行更高效？

示例：创建 `pdf-editor` 技能，处理“帮我旋转这个 PDF”：

1. 旋转 PDF 每次都要重写类似代码。
2. 应该保存一个 `scripts/rotate_pdf.py`。

示例：创建 `frontend-webapp-builder` 技能，处理“给我做一个 todo app”或“做一个步数 dashboard”：

1. 写前端 webapp 每次都需要类似 HTML/React 样板。
2. 应该保存一个 `assets/hello-world/` 模板，里面包含样板项目文件。

示例：创建 `big-query` 技能，处理“今天有多少用户登录？”：

1. 查询 BigQuery 每次都要重新发现表结构和关系。
2. 应该保存 `references/schema.md`，记录表结构。

最终要产出一份资源清单：需要哪些 scripts、references、assets。

## 第 3 步：初始化技能

现在可以实际创建技能。

只有当技能已经存在、只需要迭代或打包时，才跳过这一步。

从零创建新技能时，始终运行 `init_skill.py`。这个脚本会生成一个模板技能目录，包含技能需要的基础结构，能让创建流程更高效、可靠。

在 `nanobot` 中，自定义技能应放在当前工作区的 `skills/` 目录下，例如 `<workspace>/skills/my-skill/SKILL.md`，这样运行时会自动发现。

用法：

```bash
scripts/init_skill.py <skill-name> --path <output-directory> [--resources scripts,references,assets] [--examples]
```

示例：

```bash
scripts/init_skill.py my-skill --path ./workspace/skills
scripts/init_skill.py my-skill --path ./workspace/skills --resources scripts,references
scripts/init_skill.py my-skill --path ./workspace/skills --resources scripts --examples
```

脚本会：

- 在指定路径创建技能目录。
- 生成带正确 frontmatter 和 TODO 占位符的 `SKILL.md` 模板。
- 根据 `--resources` 创建资源目录。
- 如果传入 `--examples`，添加示例文件。

初始化后，按需修改 `SKILL.md` 并添加资源。如果使用了 `--examples`，要替换或删除占位文件。

## 第 4 步：编辑技能

编辑新生成或已有技能时，要记住：这个技能是给另一个 Agent 实例使用的。写入对 Agent 有帮助、且不明显的信息。重点考虑哪些过程性知识、领域细节、可复用资源能帮助另一个 Agent 更有效地完成任务。

### 学习成熟设计模式

根据技能需求参考这些指南：

- **多步骤流程**：参考 `references/workflows.md`，了解顺序工作流和条件逻辑。
- **特定输出格式或质量标准**：参考 `references/output-patterns.md`，了解模板和示例模式。

这些文件包含有效技能设计的成熟实践。

### 从可复用资源开始

实现时，先创建前面规划出的 `scripts/`、`references/`、`assets/` 文件。这个步骤可能需要用户输入。

例如创建 `brand-guidelines` 技能时，用户可能需要提供品牌资源或模板，存入 `assets/`；也可能需要提供文档，存入 `references/`。

新增脚本必须实际运行测试，确认没有 bug，且输出符合预期。如果有很多类似脚本，测试代表性样本即可，兼顾信心和时间。

如果使用了 `--examples`，删除不需要的占位文件。只创建真正需要的资源目录。

### 更新 SKILL.md

**写作规则：** 使用命令式或不定式表达，让 Agent 知道应该怎么做。

#### Frontmatter

YAML frontmatter 至少包含 `name` 和 `description`：

- `name`：技能名。
- `description`：技能的主要触发机制，帮助 Agent 判断什么时候使用这个技能。
  - 同时说明技能做什么，以及具体的触发场景。
  - 所有“什么时候使用”信息都应写在 `description` 里，而不是正文里。正文只有触发后才加载，所以正文里的 “When to Use This Skill” 对触发没有帮助。
  - 例如 `docx` 技能的 description 可以写：“Comprehensive document creation, editing, and analysis with support for tracked changes, comments, formatting preservation, and text extraction. Use when the agent needs to work with professional documents (.docx files) for: (1) Creating new documents, (2) Modifying or editing content, (3) Working with tracked changes, (4) Adding comments, or any other document tasks”

保持 frontmatter 简洁。在 `nanobot` 中，必要时也支持 `metadata` 和 `always`，但不要添加不必要字段。

#### Body

正文写技能使用说明和打包资源说明。

正文应该包含：

- 核心工作流。
- 使用哪些脚本、参考资料、资产。
- 何时读取 reference 文件。
- 常见坑。
- 验证步骤。

正文不应该包含：

- 和执行无关的背景故事。
- 面向普通用户的宣传文案。
- 可以放进 references 的大量细节。

## 第 5 步：打包技能

技能开发完成后，需要打包成可分发的 `.skill` 文件给用户。打包流程会先自动验证技能是否满足要求。

```bash
scripts/package_skill.py <path/to/skill-folder>
```

也可以指定输出目录：

```bash
scripts/package_skill.py <path/to/skill-folder> ./dist
```

打包脚本会：

1. **自动验证**：
   - YAML frontmatter 格式和必需字段。
   - 技能命名规范和目录结构。
   - description 是否完整、质量是否足够。
   - 文件组织和资源引用是否合理。

2. **验证通过后打包**：
   - 创建以技能名命名的 `.skill` 文件，例如 `my-skill.skill`。
   - `.skill` 文件本质是 zip 文件，只是扩展名为 `.skill`。
   - 文件会保留正确目录结构。

安全限制：如果目录里存在 symlink，打包会拒绝并失败。

如果验证失败，脚本会报告错误并退出，不会创建包。修复错误后再运行打包命令。

## 第 6 步：迭代

技能测试后，用户可能会要求改进。很多时候，这发生在刚使用完技能之后，此时上下文里还保留着技能表现如何。

**迭代流程：**

1. 在真实任务中使用技能。
2. 注意哪里卡住、低效或容易出错。
3. 判断应该更新 `SKILL.md` 还是打包资源。
4. 实现修改并再次测试。

迭代时优先 patch 已有技能，而不是创建重复技能。只有当没有现有技能合理覆盖这个任务类别时，才创建新技能。
