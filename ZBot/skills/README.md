# ZBot 技能库

本目录包含用于扩展 ZBot 功能的内置技能。

## 技能格式

每个技能都是一个独立目录，内含 `SKILL.md` 文件，文件包含：
- YAML 前置元数据（名称、描述、元信息配置）
- 供智能体使用的 Markdown 指令说明

## 版权声明

这些技能改编自 [OpenClaw](https://github.com/openclaw/openclaw) 的技能系统。
技能格式与元数据结构遵循 OpenClaw 规范，以保证兼容性。

## 可用技能

| 技能 | 说明 |
| ---- | ---- |
| `github` | 通过 `gh` CLI 与 GitHub 平台交互 |
| `weather` | 使用 wttr.in 和 Open-Meteo 获取天气信息 |
| `summarize` | 对网页链接、本地文件和 YouTube 视频生成摘要 |
| `tmux` | 远程控制 tmux 会话 |
| `clawhub` | 从 ClawHub 仓库搜索并安装技能 |
| `skill-creator` | 创建全新的自定义技能 |