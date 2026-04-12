# nanobot Cron 与 Heartbeat

---

## 核心区别

| | Cron | Heartbeat |
|---|---|---|
| **任务来源** | agent/用户通过对话创建，存于 `jobs.json` | 用户手动编辑 `HEARTBEAT.md` |
| **调度精度** | 精确：一次性时间戳、固定间隔、cron 表达式 | 固定轮询间隔（默认 30 分钟） |
| **"要不要执行"** | 时间到了就执行，无条件 | LLM 读取 HEARTBEAT.md 后自主判断 |
| **结果推送** | 可选 `deliver=true` 推送到指定 channel | 执行后再经 LLM 评估，值得通知才推送 |
| **持久化** | `workspace/cron/jobs.json`，重启后自动恢复 | `workspace/HEARTBEAT.md`，手动维护 |
| **适合场景** | 定时提醒、定期报告、延迟一次性任务 | 条件监控、智能提醒、"如果…则…"逻辑 |

---

## Cron

### 工作原理

1. `CronService` 启动时加载 `jobs.json`，计算每个 job 的 `next_run_at_ms`
2. 用 `asyncio` 定时器（精确到最近一个 job 的触发时间）唤醒
3. 到期的 job 触发 `on_job` 回调 → 将 `payload.message` 作为 prompt 发给 agent loop
4. 执行完后计算下次运行时间，更新状态写回磁盘

### 三种调度模式

| 模式 | 参数 | 说明 |
|------|------|------|
| `every` | `every_seconds` | 固定间隔重复，如每 20 分钟 |
| `cron` | `cron_expr` + 可选 `tz` | 标准 5 字段 cron 表达式 |
| `at` | `at`（ISO 时间） | 一次性，执行后自动删除 |

### 通过对话创建 Cron

直接告诉 nanobot，agent 会调用内置 `cron` 工具：

```
每隔 20 分钟提醒我喝水
→ cron(action="add", message="该喝水了！", every_seconds=1200)

每天早上 9 点发一个天气预报
→ cron(action="add", message="查询今日北京天气并汇报", cron_expr="0 9 * * *", tz="Asia/Shanghai")

工作日下午 5 点提醒下班
→ cron(action="add", message="下班时间到！", cron_expr="0 17 * * 1-5", tz="Asia/Shanghai")

30 分钟后提醒我开会
→ cron(action="add", message="会议提醒", at="<ISO datetime>")

查看所有定时任务
→ cron(action="list")

删除某个任务
→ cron(action="remove", job_id="abc123")
```

### 直接编辑 jobs.json

`~/.nanobot/workspace/cron/jobs.json` 结构如下，修改后 `CronService` 会自动检测文件变更并热重载：

```json
{
  "version": 1,
  "jobs": [
    {
      "id": "a1b2c3d4",
      "name": "每日天气播报",
      "enabled": true,
      "schedule": {
        "kind": "cron",
        "expr": "0 8 * * *",
        "tz": "Asia/Shanghai"
      },
      "payload": {
        "kind": "agent_turn",
        "message": "查询今日北京天气并汇报",
        "deliver": true,
        "channel": "telegram",
        "to": "12345678"
      },
      "state": {},
      "createdAtMs": 1744000000000,
      "updatedAtMs": 1744000000000,
      "deleteAfterRun": false
    }
  ]
}
```

**关键字段说明：**

| 字段 | 说明 |
|------|------|
| `schedule.kind` | `"every"` / `"cron"` / `"at"` |
| `schedule.everyMs` | 间隔毫秒（`every` 模式） |
| `schedule.expr` | cron 表达式（`cron` 模式） |
| `schedule.tz` | IANA 时区，如 `"Asia/Shanghai"`（仅 `cron` 模式） |
| `schedule.atMs` | 触发时间戳 ms（`at` 模式） |
| `payload.message` | 触发时作为 prompt 发给 agent loop |
| `payload.deliver` | `true` 时将 agent 响应推送给用户 |
| `payload.channel` | 推送目标渠道，如 `"telegram"` |
| `payload.to` | 推送目标 ID（chat_id / 手机号等） |
| `deleteAfterRun` | `true` 时执行一次后自动删除（`at` 模式默认开启） |

### 配置项

Cron 无独立配置节，依赖 agent 配置中的模型与 workspace 路径，存储路径固定为：

```
{workspace}/cron/jobs.json
```

---

## Heartbeat

### 工作原理

按固定间隔（默认 30 分钟）轮询，分两阶段执行：

```
每 interval_s 秒
  │
  ├─ 读取 HEARTBEAT.md
  │   └─ 文件为空 → 直接跳过
  │
  ├─ Phase 1 — 决策（轻量 LLM 调用）
  │   发送 HEARTBEAT.md 内容给 LLM，要求调用 heartbeat 工具
  │   返回 action = "skip" 或 "run"
  │   └─ skip → 结束本轮
  │
  └─ Phase 2 — 执行（完整 agent loop）
      将 tasks 描述作为 prompt 发给 agent loop
      执行完后再经 LLM 评估：结果是否值得通知用户？
      └─ 值得通知 → 推送到 on_notify 回调（发送到渠道）
         不值得   → 静默丢弃
```

### 自定义 HEARTBEAT.md

在 `~/.nanobot/workspace/HEARTBEAT.md` 中描述你希望 agent 定期关注的事项。格式自由，LLM 会阅读并判断是否有需要处理的任务。

**示例 1 — 简单监控**

```markdown
# 我的待办关注

## 每日提醒
- 每天早上检查一次 GitHub Trending，汇报今日热门 Python 项目

## 条件触发
- 如果当前时间是工作日上午 9 点到 10 点之间，发送今日工作计划提醒
```

**示例 2 — 项目监控**

```markdown
# 项目巡检

检查以下内容，如有异常则汇报：
- workspace/scraper.py 对应的 GitHub repo 有无新 issue
- 服务器磁盘使用率（通过 shell 命令查询）是否超过 80%

如果没有异常，静默跳过，不需要通知我。
```

**示例 3 — 智能提醒**

```markdown
# 健康提醒

每隔一段时间提醒用户：
- 如果距上次提醒超过 2 小时，提醒喝水
- 如果是下午 3 点左右，提醒站起来活动 5 分钟

注意：判断"距上次提醒多久"可以通过读取 memory/HISTORY.md 来估算。
```

### 配置

在 `~/.nanobot/config.json` 的 `gateway.heartbeat` 节中配置：

```json
{
  "gateway": {
    "heartbeat": {
      "enabled": true,
      "interval_s": 1800
    }
  }
}
```

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `enabled` | `true` | 是否启用 heartbeat |
| `interval_s` | `1800`（30 分钟） | 轮询间隔，单位秒 |
| `keep_recent_messages` | `8` | 执行时携带的最近消息数 |

> Heartbeat 仅在 `nanobot gateway` 模式下运行，`nanobot agent`（CLI 模式）不启动 HeartbeatService。

---

## 选择建议

- **需要精确时间触发** → 用 Cron（`every` / `cron` / `at`）
- **需要 LLM 判断"现在该不该做"** → 用 Heartbeat + HEARTBEAT.md
- **两者可以组合**：用 Cron 定期触发固定任务，用 Heartbeat 处理需要上下文判断的弹性提醒

---

## 关键源文件

| 文件 | 职责 |
|------|------|
| `nanobot/cron/service.py` | `CronService`：调度循环、job 持久化、执行回调 |
| `nanobot/cron/types.py` | `CronJob` / `CronSchedule` / `CronPayload` 数据结构 |
| `nanobot/agent/tools/cron.py` | `CronTool`：agent 调用的 `cron` 工具（add/list/remove） |
| `nanobot/skills/cron/SKILL.md` | Cron skill 说明，agent 读取后了解如何使用 cron 工具 |
| `nanobot/heartbeat/service.py` | `HeartbeatService`：决策 + 执行两阶段循环 |
| `nanobot/config/schema.py` | `HeartbeatConfig`：enabled / interval_s / keep_recent_messages |
| `{workspace}/cron/jobs.json` | Cron 持久化存储 |
| `{workspace}/HEARTBEAT.md` | Heartbeat 任务描述文件（用户手动编辑） |
