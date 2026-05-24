---
name: summarize
description: "从 URL、播客和本地文件中总结或提取文本/转录内容，也适合兜底处理“转录这个 YouTube/视频”。"
homepage: https://summarize.sh
metadata: {"nanobot":{"emoji":"🧾","requires":{"bins":["summarize"]},"install":[{"id":"brew","kind":"brew","formula":"steipete/tap/summarize","bins":["summarize"],"label":"Install summarize (brew)"}]}}
---

# Summarize

用于总结 URL、本地文件和 YouTube 链接的快速 CLI。

## 什么时候使用（触发短语）

当用户提出以下请求时，立即使用这个技能：
- “使用 summarize.sh”
- “这个链接/视频讲了什么？”
- “总结这个 URL/文章”
- “转录这个 YouTube/视频”（尽力提取转录内容，不需要 `yt-dlp`）

## 快速开始

```bash
summarize "https://example.com" --model google/gemini-3-flash-preview
summarize "/path/to/file.pdf" --model google/gemini-3-flash-preview
summarize "https://youtu.be/dQw4w9WgXcQ" --youtube auto
```

## YouTube：总结和转录

尽力提取转录内容（仅限 URL）：

```bash
summarize "https://youtu.be/dQw4w9WgXcQ" --youtube auto --extract-only
```

如果用户要求转录但内容很长，先返回简洁总结，再询问要展开哪个片段或时间范围。

## 模型和 key

为所选 provider 设置 API key：
- OpenAI: `OPENAI_API_KEY`
- Anthropic: `ANTHROPIC_API_KEY`
- xAI: `XAI_API_KEY`
- Google: `GEMINI_API_KEY` (aliases: `GOOGLE_GENERATIVE_AI_API_KEY`, `GOOGLE_API_KEY`)

如果没有设置模型，默认使用 `google/gemini-3-flash-preview`。

## 常用参数

- `--length short|medium|long|xl|xxl|<chars>`
- `--max-output-tokens <count>`
- `--extract-only`（仅 URL）
- `--json`（机器可读）
- `--firecrawl auto|off|always`（兜底提取）
- `--youtube auto`（如果设置了 `APIFY_API_TOKEN`，可用 Apify 兜底）

## 配置

可选配置文件：`~/.summarize/config.json`

```json
{ "model": "openai/gpt-5.2" }
```

可选服务：
- `FIRECRAWL_API_KEY`：用于处理受阻网站。
- `APIFY_API_TOKEN`：用于 YouTube 兜底。
