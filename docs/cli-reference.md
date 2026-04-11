# nanobot 命令行参考

## 全局选项

```bash
nanobot --version        # 显示版本号
nanobot --help           # 显示帮助
nanobot <command> --help # 查看子命令帮助
```

---

## nanobot onboard — 初始化配置

```bash
nanobot onboard [OPTIONS]
```

创建或更新 `~/.nanobot/config.json` 并初始化 workspace。

| 选项 | 简写 | 说明 |
|------|------|------|
| `--wizard` | | 启动交互式配置向导（推荐首次使用） |
| `--config PATH` | `-c` | 指定 config 文件路径 |
| `--workspace PATH` | `-w` | 指定 workspace 目录 |

```bash
nanobot onboard                    # 创建默认配置
nanobot onboard --wizard           # 交互式向导（推荐）
nanobot onboard --config ~/.nanobot-feishu/config.json  # 多实例配置
```

> 若 config 已存在，选择 **N**（默认）保留现有值并补充新字段，选择 **y** 重置为默认值。

---

## nanobot agent — 命令行对话

```bash
nanobot agent [OPTIONS]
```

直接在终端与 Agent 交互（CLI 模式）。

| 选项 | 简写 | 说明 |
|------|------|------|
| `--message TEXT` | `-m` | 发送单条消息后退出（非交互模式） |
| `--session TEXT` | `-s` | 会话 ID，默认 `cli:direct` |
| `--config PATH` | `-c` | 指定 config 文件 |
| `--workspace PATH` | `-w` | 指定 workspace 目录 |
| `--markdown/--no-markdown` | | 是否渲染 Markdown，默认开启 |
| `--logs/--no-logs` | | 是否显示运行时日志，默认关闭 |

```bash
nanobot agent                          # 进入交互模式
nanobot agent -m "查询北京今天天气"     # 单条消息，执行完退出
nanobot agent --no-markdown            # 纯文本输出
nanobot agent --logs                   # 显示调试日志
nanobot agent -s "myproject"           # 使用指定会话 ID
nanobot agent -c ~/.nanobot-work/config.json  # 使用指定配置
```

### 交互模式内置命令

在 `nanobot agent` 交互模式下输入以下命令：

| 命令 | 说明 |
|------|------|
| `/new` | 开启新会话（清除当前对话历史） |
| `/stop` | 取消当前正在执行的任务 |
| `/restart` | 重启 nanobot 进程 |
| `/status` | 显示运行状态（模型、token 用量、uptime） |
| `/context` | 显示 context window token 占用明细 |
| `/help` | 显示所有可用命令 |
| `exit` / `quit` / `/exit` / `:q` | 退出交互模式 |

---

## nanobot gateway — 启动网关服务

```bash
nanobot gateway [OPTIONS]
```

启动完整的 gateway 服务，接入 Telegram、飞书、Discord 等渠道。

| 选项 | 简写 | 说明 |
|------|------|------|
| `--port INT` | `-p` | 监听端口，默认 `18790` |
| `--config PATH` | `-c` | 指定 config 文件 |
| `--workspace PATH` | `-w` | 指定 workspace 目录 |
| `--verbose` | `-v` | 显示详细日志 |

```bash
nanobot gateway                              # 默认端口启动
nanobot gateway --port 18792                 # 指定端口（多实例时用）
nanobot gateway --verbose                    # 显示详细日志
nanobot gateway -c ~/.nanobot-feishu/config.json --port 18792
```

---

## nanobot status — 查看配置状态

```bash
nanobot status
```

显示当前 config 路径、workspace、模型设置，以及各 LLM provider 的 API Key 配置情况。

```
🐈 nanobot Status

Config: ~/.nanobot/config.json ✓
Workspace: ~/.nanobot/workspace ✓
Model: anthropic/claude-opus-4-5
OpenRouter: ✓
Anthropic: not set
...
```

---

## nanobot channels — 渠道管理

### channels login — 渠道登录

```bash
nanobot channels login <channel> [OPTIONS]
```

通过扫码或交互方式登录需要认证的渠道（微信、WhatsApp）。

| 选项 | 简写 | 说明 |
|------|------|------|
| `--force` | `-f` | 强制重新认证，忽略已有凭证 |

```bash
nanobot channels login weixin          # 微信登录（扫二维码）
nanobot channels login whatsapp        # WhatsApp 登录（扫二维码）
nanobot channels login weixin --force  # 强制重新登录
```

---

## nanobot plugins — 插件管理

### plugins list — 列出所有渠道插件

```bash
nanobot plugins list
```

以表格形式列出所有已发现的渠道（内置 + 插件），并显示各渠道的启用状态。

---

## nanobot provider — Provider 管理

### provider login — OAuth 登录

```bash
nanobot provider login <provider>
```

对支持 OAuth 的 LLM Provider 进行认证登录。

```bash
nanobot provider login openai-codex      # OpenAI Codex OAuth 登录
nanobot provider login github-copilot    # GitHub Copilot 设备流登录
```

---

## 多实例部署

为不同渠道各自维护独立的 config 和 workspace：

```bash
# 初始化各实例配置
nanobot onboard --config ~/.nanobot-telegram/config.json \
                --workspace ~/.nanobot-telegram/workspace
nanobot onboard --config ~/.nanobot-feishu/config.json \
                --workspace ~/.nanobot-feishu/workspace

# 分别启动（使用不同端口）
nanobot gateway --config ~/.nanobot-telegram/config.json --port 18790
nanobot gateway --config ~/.nanobot-feishu/config.json   --port 18792
```

---

## 默认文件路径

| 路径 | 说明 |
|------|------|
| `~/.nanobot/config.json` | 主配置文件 |
| `~/.nanobot/workspace/` | 默认 workspace（memory、skills、cron 等） |
| `~/.nanobot/workspace/memory/MEMORY.md` | 长期记忆 |
| `~/.nanobot/workspace/memory/HISTORY.md` | 对话历史日志 |
| `~/.nanobot/workspace/skills/` | 用户自定义 skills |
| `~/.nanobot/workspace/cron/jobs.json` | 定时任务存储 |
| `~/.nanobot/workspace/debug/requests_*.jsonl` | LLM 请求调试日志 |
