# nanobot 技能

这个目录包含内置技能，用来扩展 nanobot 的能力。

## 技能格式

每个技能都是一个目录，里面包含一个 `SKILL.md` 文件：
- YAML frontmatter：包含 `name`、`description`、`metadata` 等元数据。
- Markdown 正文：写给 Agent 的使用说明。

当技能需要引用很大的本地文档或日志时，优先使用 nanobot 内置的 `grep` 工具缩小搜索范围，再读取完整文件。
大范围搜索时先用 `grep(output_mode="count")` 或默认的 `files_with_matches`；
结果很多时用 `head_limit` / `offset` 分页；
需要按文件名过滤时用 `grep(glob="*.md")`。

## 来源说明

这些技能改编自 [OpenClaw](https://github.com/openclaw/openclaw) 的技能系统。
技能格式和元数据结构遵循 OpenClaw 的约定，以保持兼容性。

## 可用技能

| 技能 | 说明 |
|------|------|
| `github` | 使用 `gh` CLI 和 GitHub 交互 |
| `weather` | 使用 wttr.in 和 Open-Meteo 获取天气信息 |
| `summarize` | 总结 URL、文件和 YouTube 视频 |
| `tmux` | 远程控制 tmux 会话 |
| `clawhub` | 从 ClawHub 技能注册表搜索和安装技能 |
| `skill-creator` | 创建新技能 |
| `long-goal` | 持续目标：`long_task`、`complete_goal`、幂等目标、模块化项目工作、前置调研 |
