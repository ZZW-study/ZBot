---
name: weather
description: 获取当前天气与预报（无需 API 密钥）。
homepage: https://wttr.in/:help
metadata: {"ZBot":{"emoji":"🌤️","requires":{"bins":["curl"]}}}
---
# 天气查询

## wttr.in（主用方案）

简洁单行查询：

```bash
curl -s "wttr.in/London?format=3"
# 输出示例：London: ⛅️ +8°C
```

紧凑格式：

```bash
curl -s "wttr.in/London?format=%l:+%c+%t+%h+%w"
# 输出示例：London: ⛅️ +8°C 71% ↙5km/h
```

完整天气预报：

```bash
curl -s "wttr.in/London?T"
```

格式占位符：
`%c` 天气状况 · `%t` 温度 · `%h` 湿度 · `%w` 风速 · `%l` 地点 · `%m` 月相

使用技巧：

- 空格需 URL 编码：`wttr.in/New+York`
- 支持机场代码：`wttr.in/JFK`
- 单位切换：`?m`（公制）`?u`（美制）
- 仅看今日：`?1` · 仅看当前：`?0`

## Open-Meteo（备用方案，JSON 格式）

免费无密钥，适合程序化调用：

```bash
curl -s "https://api.open-meteo.com/v1/forecast?latitude=51.5&longitude=-0.12&current_weather=true"
```

先查询城市经纬度，再发起请求。返回包含温度、风速、天气代码的 JSON 数据。

文档：https://open-meteo.com/en/docs
