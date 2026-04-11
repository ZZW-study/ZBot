---
name: clawhub
description: 从公共技能仓库 ClawHub 搜索并安装智能体技能
homepage: https://clawhub.ai
metadata: {"ZBot":{"emoji":"🦞"}}
---

# ClawHub
面向 AI 智能体的公共技能仓库，支持自然语言搜索（向量搜索）。

## 使用场景
当用户提出以下任意请求时，使用该技能：
- “查找用于……的技能”
- “搜索技能”
- “安装一个技能”
- “有哪些可用的技能？”
- “更新我的技能”

## 搜索
```bash
npx --yes clawhub@latest search "web scraping" --limit 5
```

## 安装
```bash
npx --yes clawhub@latest install <slug> --workdir ~/.ZBot/workspace
```
将 `<slug>` 替换为搜索结果中的技能名称。该命令会将技能安装至 `~/.ZBot/workspace/skills/` 目录，ZBot 会从此目录加载工作区技能。**必须携带 `--workdir` 参数**。

## 更新
```bash
npx --yes clawhub@latest update --all --workdir ~/.ZBot/workspace
```

## 列出已安装技能
```bash
npx --yes clawhub@latest list --workdir ~/.ZBot/workspace
```

## 注意事项
- 需要安装 Node.js（`npx` 随 Node.js 自带）。
- 搜索与安装操作无需 API 密钥。
- 仅在发布技能时需要登录（`npx --yes clawhub@latest login`）。
- `--workdir ~/.ZBot/workspace` 为关键参数，缺少该参数时技能会安装至当前目录，而非 ZBot 工作区。
- 安装完成后，提醒用户新建会话以加载技能。