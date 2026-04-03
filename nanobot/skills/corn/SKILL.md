---
name: cron
description: 定时提醒与循环任务调度
---

# Cron
使用 `cron` 工具设置提醒或循环执行任务。

## 三种模式
1. **提醒** - 消息直接发送给用户
2. **任务** - 消息为任务描述，智能体执行后返回结果
3. **单次执行** - 在指定时间运行一次后自动删除

## 示例
固定提醒：
```
cron(action="add", message="休息时间到啦！", every_seconds=1200)
```

动态任务（智能体每次自动执行）：
```
cron(action="add", message="查看 HKUDS/nanobot 的 GitHub Star 数量并汇报", every_seconds=600)
```

单次定时任务（根据当前时间计算 ISO 格式时间）：
```
cron(action="add", message="提醒我开会", at="<ISO datetime>")
```

带时区的定时任务：
```
cron(action="add", message="早会", cron_expr="0 9 * * 1-5", tz="America/Vancouver")
```

查看/删除任务：
```
cron(action="list")
cron(action="remove", job_id="abc123")
```

## 时间表达式
| 用户表述 | 参数写法 |
|----------|----------|
| 每20分钟 | every_seconds: 1200 |
| 每小时 | every_seconds: 3600 |
| 每天早上8点 | cron_expr: "0 8 * * *" |
| 工作日下午5点 | cron_expr: "0 17 * * 1-5" |
| 温哥华时间每天早上9点 | cron_expr: "0 9 * * *", tz: "America/Vancouver" |
| 指定具体时间 | at: ISO 格式时间字符串（根据当前时间计算） |

## 时区设置
配合 `cron_expr` 使用 `tz` 参数，可按 IANA 标准时区执行。
不指定 `tz` 时，默认使用服务器本地时区。