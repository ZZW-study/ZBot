---
name: cron
description: "创建提醒和周期性任务。"
---

# Cron

使用 `cron` 工具创建提醒或周期性任务。

## 三种模式

1. **提醒**：消息会直接发送给用户。
2. **任务**：消息是一段任务描述，Agent 到时执行并发送结果。
3. **一次性任务**：在指定时间运行一次，然后自动删除。

## 示例

固定间隔提醒：
```
cron(action="add", message="Time to take a break!", every_seconds=1200)
```

动态任务（每次由 Agent 执行）：
```
cron(action="add", message="Check HKUDS/nanobot GitHub stars and report", every_seconds=600)
```

一次性定时任务（根据当前时间计算 ISO datetime）：
```
cron(action="add", message="Remind me about the meeting", at="<ISO datetime>")
```

带时区的 cron：
```
cron(action="add", message="Morning standup", cron_expr="0 9 * * 1-5", tz="America/Vancouver")
```

列出和删除：
```
cron(action="list")
cron(action="remove", job_id="abc123")
```

## 时间表达

| 用户说法 | 参数 |
|----------|------|
| 每 20 分钟 | every_seconds: 1200 |
| 每小时 | every_seconds: 3600 |
| 每天早上 8 点 | cron_expr: "0 8 * * *" |
| 工作日下午 5 点 | cron_expr: "0 17 * * 1-5" |
| 每天温哥华时间早上 9 点 | cron_expr: "0 9 * * *", tz: "America/Vancouver" |
| 某个具体时间 | at: ISO datetime 字符串（根据当前时间计算） |

## 时区

和 `cron_expr` 一起使用 `tz`，可以按指定 IANA 时区调度。如果不传 `tz`，则使用服务器本地时区。
