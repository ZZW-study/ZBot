---
name: image-generation
description: "生成图片，并对已保存的图片产物进行连续编辑。"
---

# 图片生成

当用户要求创建、渲染、绘制、设计、生成或编辑图片时，使用 `generate_image` 工具。

如果当前工具列表里没有 `generate_image`，告诉用户当前 nanobot 实例没有启用图片生成。

## 什么时候使用

- 文生图：使用具体的 `prompt` 调用 `generate_image`。
- 图片编辑：把已保存的产物路径或用户上传图片路径放进 `reference_images`。
- 同一会话里的连续编辑：如果用户说“调亮一点”“换背景”“再试一个版本”，优先使用最近一次生成的图片产物。
- 目标不明确的编辑：如果最近有多张图片都可能是目标，先问一个简短澄清问题。
- 图片生成后，调用 `message` 工具，并把产物路径放进 `media` 参数交付给用户。

## Prompt 规则

给图片模型的 prompt 要足够具体：

- 主体和场景。
- 构图、镜头或版式。
- 风格、情绪、光照和配色。
- 必须出现在图片里的文字，逐字加引号。
- 约束，例如“保持同一角色”“保留 logo”“不要改变背景”。

## 产物规则

工具会把生成的图片作为持久产物保存到 nanobot 的 media 目录，并返回结构化元数据：

- `id`：生成图片的 ID，例如 `img_ab12cd34ef56`。
- `path`：本地文件路径，用于内部后续编辑。
- `mime`：图片 MIME 类型。
- `prompt`、`model`、`source_images`：后续编辑需要的来源信息。

普通用户回复中，不要暴露本地文件系统路径。回复保持自然，比如“好了，我已经生成了。”如果短图片 `id` 有助于用户指代某张图片，可以给出；但原始 `path` 只供内部使用，除非用户明确要求调试细节或本地产物引用。不要粘贴 base64。

后续编辑时，把之前产物的 `path` 传给 `reference_images`。如果用户上传了新图片，则使用新图片路径作为参考。

面向用户的回复中，不要包含内部回放标记，例如 `[Message Time: ...]`、`[image: /local/path]`、`generate_image(...)` 或 `message(...)`。

## 示例

生成新图片：

```text
generate_image(
  prompt="A minimal app icon for nanobot: friendly robot head, rounded square, soft blue and white palette, clean vector style, no text",
  aspect_ratio="1:1",
  image_size="1K"
)
```

编辑最近生成的产物：

```text
generate_image(
  prompt="Use the reference image. Keep the same robot and composition, but change the palette to warm orange and add a subtle sunrise background.",
  reference_images=["/home/user/.nanobot/media/generated/2026-05-08/img_ab12cd34ef56.png"],
  aspect_ratio="1:1",
  image_size="1K"
)
```
