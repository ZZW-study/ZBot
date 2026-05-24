---
name: weather
description: "获取当前天气和天气预报，不需要 API key。"
homepage: https://wttr.in/:help
metadata: {"nanobot":{"emoji":"🌤️","requires":{"bins":["curl"]}}}
---

# 天气

两个免费服务，都不需要 API key。

## wttr.in（首选）

快速一行命令：
```bash
curl -s "wttr.in/London?format=3"
# Output: London: ⛅️ +8°C
```

紧凑格式：
```bash
curl -s "wttr.in/London?format=%l:+%c+%t+%h+%w"
# Output: London: ⛅️ +8°C 71% ↙5km/h
```

完整预报：
```bash
curl -s "wttr.in/London?T"
```

格式代码：`%c` 天气状况 · `%t` 温度 · `%h` 湿度 · `%w` 风 · `%l` 地点 · `%m` 月相

提示：
- 空格要 URL 编码：`wttr.in/New+York`
- 支持机场代码：`wttr.in/JFK`
- 单位：`?m`（公制）`?u`（美制）
- 只看今天：`?1`；只看当前：`?0`
- PNG：`curl -s "wttr.in/Berlin.png" -o /tmp/weather.png`

## Open-Meteo（兜底，JSON）

免费、无需 key，适合程序化使用：
```bash
curl -s "https://api.open-meteo.com/v1/forecast?latitude=51.5&longitude=-0.12&current_weather=true"
```

先找到城市坐标，再查询。返回包含温度、风速、天气代码的 JSON。

文档：https://open-meteo.com/en/docs
