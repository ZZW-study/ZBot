---
name: github
description: "使用 `gh` CLI 和 GitHub 交互。处理 issue、PR、CI run 和高级查询时，使用 `gh issue`、`gh pr`、`gh run`、`gh api`。"
metadata: {"nanobot":{"emoji":"🐙","requires":{"bins":["gh"]},"install":[{"id":"brew","kind":"brew","formula":"gh","bins":["gh"],"label":"Install GitHub CLI (brew)"},{"id":"apt","kind":"apt","package":"gh","bins":["gh"],"label":"Install GitHub CLI (apt)"}]}}
---

# GitHub 技能

使用 `gh` CLI 和 GitHub 交互。不在 git 仓库目录里时，始终指定 `--repo owner/repo`，也可以直接使用 URL。

## Pull Request

检查某个 PR 的 CI 状态：
```bash
gh pr checks 55 --repo owner/repo
```

列出最近的 workflow run：
```bash
gh run list --repo owner/repo --limit 10
```

查看某个 run，并确认哪些步骤失败：
```bash
gh run view <run-id> --repo owner/repo
```

只查看失败步骤的日志：
```bash
gh run view <run-id> --repo owner/repo --log-failed
```

## 使用 API 做高级查询

当其他子命令拿不到需要的数据时，可以使用 `gh api`。

获取 PR 的指定字段：
```bash
gh api repos/owner/repo/pulls/55 --jq '.title, .state, .user.login'
```

## JSON 输出

大多数命令都支持 `--json` 输出结构化数据。可以用 `--jq` 过滤：

```bash
gh issue list --repo owner/repo --json number,title --jq '.[] | "\(.number): \(.title)"'
```
