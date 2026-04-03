---
name: summarize
description: 对网页链接、播客和本地文件进行文本摘要提取或转录（可作为“转录YouTube/视频”的优质兜底方案）。
homepage: https://summarize.sh
metadata: {"nanobot":{"emoji":"🧾","requires":{"bins":["summarize"]},"install":[{"id":"brew","kind":"brew","formula":"steipete/tap/summarize","bins":["summarize"],"label":"安装 summarize（brew 方式）"}]}}
---

# 文本摘要工具

一款快速命令行工具，可对网页链接、本地文件和 YouTube 链接生成摘要。

## 使用场景（触发语句）

当用户提出以下任一需求时，立即使用该技能：
- “使用 summarize.sh”
- “这个链接/视频讲了什么？”
- “为这个网页链接/文章生成摘要”
- “转录这个 YouTube/视频内容”（尽力提取字幕，无需依赖 `yt-dlp`）

## 快速上手

```bash
summarize "https://example.com" --model google/gemini-3-flash-preview
summarize "/path/to/file.pdf" --model google/gemini-3-flash-preview
summarize "https://youtu.be/dQw4w9WgXcQ" --youtube auto
```

## YouTube 场景：摘要与字幕转录
仅针对链接，尽力提取视频字幕：
```bash
summarize "https://youtu.be/dQw4w9WgXcQ" --youtube auto --extract-only
```

如果用户需要转录文本但内容过长，可先返回精简摘要，再询问需要展开的段落或时间范围。

## 模型与密钥配置
为你选择的服务商设置对应 API 密钥：
- OpenAI：`OPENAI_API_KEY`
- Anthropic：`ANTHROPIC_API_KEY`
- xAI：`XAI_API_KEY`
- Google：`GEMINI_API_KEY`（别名：`GOOGLE_GENERATIVE_AI_API_KEY`、`GOOGLE_API_KEY`）

未指定模型时，默认使用 `google/gemini-3-flash-preview`。

## 常用参数
- `--length short|medium|long|xl|xxl|<字符数>`：控制摘要长度
- `--max-output-tokens <数量>`：设置最大输出令牌数
- `--extract-only`：仅提取原文（仅支持链接）
- `--json`：输出机器可读的 JSON 格式
- `--firecrawl auto|off|always`：兜底内容提取方案
- `--youtube auto`：YouTube 兜底方案（配置 `APIFY_API_TOKEN` 后生效）

## 配置文件
可选配置文件路径：`~/.summarize/config.json`

```json
{ "model": "openai/gpt-5.2" }
```

可选第三方服务：
- 针对访问受限网站：配置 `FIRECRAWL_API_KEY`
- 作为 YouTube 兜底方案：配置 `APIFY_API_TOKEN`