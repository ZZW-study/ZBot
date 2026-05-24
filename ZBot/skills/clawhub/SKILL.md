---
name: clawhub
description: "从公共技能注册表 ClawHub 搜索和安装 Agent 技能。"
homepage: https://clawhub.ai
metadata: {"nanobot":{"emoji":"🦞"}}
---

# ClawHub

ClawHub 是 AI Agent 的公共技能注册表，支持用自然语言搜索技能（向量搜索）。

## 什么时候使用

当用户提出下面这类请求时，使用这个技能：
- “找一个能做……的技能”
- “搜索技能”
- “安装一个技能”
- “有哪些技能可用？”
- “更新我的技能”

## 搜索

```bash
npx --yes clawhub@latest search "web scraping" --limit 5
```

## 安装

```bash
npx --yes clawhub@latest install <slug> --workdir ~/.nanobot/workspace
```

把 `<slug>` 替换成搜索结果里的技能名称。这个命令会把技能安装到 `~/.nanobot/workspace/skills/`，nanobot 会从这里加载工作区技能。务必带上 `--workdir`。

## 更新

```bash
npx --yes clawhub@latest update --all --workdir ~/.nanobot/workspace
```

## 列出已安装技能

```bash
npx --yes clawhub@latest list --workdir ~/.nanobot/workspace
```

## 注意事项

- 需要 Node.js，`npx` 会随 Node.js 一起提供。
- 搜索和安装不需要 API key。
- 只有发布技能时才需要登录：`npx --yes clawhub@latest login`。
- `--workdir ~/.nanobot/workspace` 很重要。没有它，技能会安装到当前目录，而不是 nanobot 工作区。
- 安装完成后，提醒用户开启一个新会话来加载新技能。
