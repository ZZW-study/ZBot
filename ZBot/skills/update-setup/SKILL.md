---
name: update-setup
description: "nanobot 升级技能的一次性设置向导。触发词：setup update、configure update、设置更新、初始化更新。"
---

# 更新设置

为当前工作区生成一个个性化升级技能。

## 第 1 步：检查是否已存在

使用 `read_file` 检查工作区中是否已经存在 `skills/update/SKILL.md`。

如果已经存在，询问用户：“升级技能已经存在。是否重新配置？”等待用户回复。如果用户说不，就停在这里。

## 第 2 步：当前版本和安装线索

使用 `exec` 运行 `nanobot --version`，告诉用户当前版本。

然后用 `exec` 收集安装线索。下面这些命令是尽力而为；如果某条失败，继续执行，并展示有用输出：

```
command -v nanobot || true
python -m pip show nanobot-ai || true
pipx list | sed -n '/nanobot-ai/,+3p' || true
uv tool list | sed -n '/nanobot-ai/,+3p' || true
```

用一小段话总结发现。线索只能用来推测可能的安装方式，不能当作确认结果。

## 第 3 步：确认必要输入

关键：在用户明确确认安装方式之前，不要写入 `skills/update/SKILL.md`。安装方式必须来自用户回答或确认，不能只靠推断。如果拿不到清楚答案，就停止，并让用户在知道 nanobot 是如何安装后重新运行这个设置。

在回复中逐个询问下面的问题。每次等待用户回答后，再进入下一个问题。如果拿不到清楚答案，就停止，不写入技能。

**问题 1：安装方式**

```
question: "I found these install clues: <SUMMARY>. Which update method should this workspace use?"
options: ["uv", "pipx", "pip", "source (git clone)", "not sure"]
```

如果用户选择 `not sure`，解释各选项差异后停止。不要生成升级技能。

如果用户选择 `source (git clone)`，询问本地源码路径：`question: "Where is your nanobot source checkout? Enter an absolute path or a path relative to this workspace:"`。

**问题 2：可选依赖**

```
question: "Which optional dependencies do you need? List names separated by spaces, or reply 'none'. Available: api, wecom, weixin, msteams, matrix, discord, langsmith, pdf"
```

解析用户回复。如果用户说 “none” 或类似表达，将 extras 设为空。否则收集有效名称。

**问题 3：代理**

```
question: "Do you need an HTTP proxy to reach PyPI or GitHub?"
options: ["no", "yes"]
```

如果用户选择 yes，再询问代理 URL：`question: "Enter proxy URL (e.g. http://127.0.0.1:7890):"`。

## 第 4 步：生成技能

构建 extras 字符串。如果用户选择了依赖，格式为 `[dep1,dep2,...]`。如果没有选择，完全省略方括号。

根据安装方式确定升级命令：

| 方式 | 命令 |
|------|------|
| uv | `uv tool install "nanobot-ai[EXTRAS]" --force` |
| pipx | `pipx install --force "nanobot-ai[EXTRAS]"` |
| pip | `python -m pip install --upgrade "nanobot-ai[EXTRAS]"` |
| source | `cd <SOURCE_CHECKOUT> && git pull && python -m pip install -e ".[EXTRAS]"` |

对于源码安装，如果用户选择了 extras，把 extras 放进 editable install 命令。如果源码路径包含空格，要给路径加引号。

根据安装方式确定预检命令：

| 方式 | 预检命令 |
|------|----------|
| uv | `command -v uv` |
| pipx | `command -v pipx` |
| pip | `python -m pip --version` |
| source | `test -d <SOURCE_CHECKOUT> && test -d <SOURCE_CHECKOUT>/.git && test -f <SOURCE_CHECKOUT>/pyproject.toml` |

对于源码安装，如果源码路径包含空格，预检命令里也要给路径加引号。

构建技能内容。如果配置了代理，在升级命令前加入 `export http_proxy=URL` 和 `export https_proxy=URL`。

使用 `write_file` 写入 `skills/update/SKILL.md`，内容如下：

```
---
name: update
description: "Upgrade nanobot to the latest version. Triggers: upgrade nanobot, update nanobot, 升级nanobot, 更新nanobot."
---

# Update Nanobot

1. （如果配置了代理）设置代理：`export http_proxy=URL && export https_proxy=URL`
2. 使用 `exec` 运行预检命令：<PREFLIGHT_CHECK>。如果失败，停止并告诉用户重新运行 `update-setup`，因为保存的安装方式已经不匹配当前环境。
3. 使用 `exec` 运行升级命令：<UPGRADE_COMMAND>
4. 使用 `exec` 验证：`nanobot --version`
5. 告诉用户新版本。说明：“运行 `/restart` 重启 nanobot 并应用更新。如果当前渠道没有 `/restart`，请手动重启 nanobot 进程。”
```

## 第 5 步：确认

告诉用户：“升级技能已创建。需要更新时，说 ‘upgrade nanobot’ 即可。”
