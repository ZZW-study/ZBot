---
name: github
description: "通过 `gh` 命令行工具与 GitHub 交互。使用 `gh issue`、`gh pr`、`gh run` 和 `gh api` 处理议题、拉取请求、CI 运行记录及高级查询。"
metadata: {"nanobot":{"emoji":"🐙","requires":{"bins":["gh"]},"install":[{"id":"brew","kind":"brew","formula":"gh","bins":["gh"],"label":"安装 GitHub CLI (brew)"},{"id":"apt","kind":"apt","package":"gh","bins":["gh"],"label":"安装 GitHub CLI (apt)"}]}}
---

# GitHub 技能
使用 `gh` 命令行工具与 GitHub 进行交互。当不在 Git 目录下时，必须指定 `--repo owner/repo`，也可以直接使用仓库 URL。

## 拉取请求
查看 PR 的 CI 状态：
```bash
gh pr checks 55 --repo owner/repo
```

列出最近的工作流运行记录：
```bash
gh run list --repo owner/repo --limit 10
```

查看某次运行并定位失败步骤：
```bash
gh run view <run-id> --repo owner/repo
```

仅查看失败步骤的日志：
```bash
gh run view <run-id> --repo owner/repo --log-failed
```

## 用于高级查询的 API
`gh api` 命令可用于获取其他子命令无法直接获取的数据。

获取 PR 指定字段信息：
```bash
gh api repos/owner/repo/pulls/55 --jq '.title, .state, .user.login'
```

## JSON 格式输出
大部分命令支持 `--json` 参数以结构化输出，可配合 `--jq` 进行结果过滤：
```bash
gh issue list --repo owner/repo --json number,title --jq '.[] | "\(.number): \(.title)"'
```