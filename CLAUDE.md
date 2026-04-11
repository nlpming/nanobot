# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies (all extras for full test suite)
uv sync --all-extras

# Run all tests
uv run pytest tests/

# Run a single test file
uv run pytest tests/agent/test_runner.py

# Run a single test by name
uv run pytest tests/agent/test_runner.py::test_name

# Lint
uv run ruff check nanobot/

# Format/fix lint issues
uv run ruff check --fix nanobot/

# Run the CLI
uv run nanobot
```

## Architecture

nanobot is a lightweight personal AI assistant framework. The core flow is:

**Channel → MessageBus → AgentLoop → LLMProvider → Tools → MessageBus → Channel**

### Key modules

- **`nanobot/bus/`** — Central message bus (`MessageBus`) with `InboundMessage`/`OutboundMessage` event types. All channels and the agent loop communicate exclusively through this bus.

- **`nanobot/agent/loop.py`** — `AgentLoop`: receives messages from the bus, builds context (history + memory + skills), calls the LLM, executes tool calls, and sends responses back. Core cycle: up to `max_iterations` tool-call rounds per user message.

- **`nanobot/agent/runner.py`** — `AgentRunner`: handles a single LLM inference call + streaming. Separated from loop orchestration.

- **`nanobot/agent/context.py`** — `ContextBuilder`: assembles the message history, injects memory/skills/templates into the system prompt.

- **`nanobot/agent/tools/`** — Agent tools (each extends `Tool` ABC with `name`, `description`, `parameters`, `execute`): `shell`, `filesystem`, `web`, `message`, `cron`, `spawn` (subagents), `mcp`.

- **`nanobot/channels/`** — Chat platform integrations (Telegram, Slack, Discord, Feishu, DingTalk, QQ, WeChat, WeCom, Matrix, Email, WhatsApp). Each extends `BaseChannel` and puts `InboundMessage`s on the bus. The `ChannelManager` (`channels/manager.py`) routes `OutboundMessage`s back to the right channel.

- **`nanobot/providers/`** — LLM provider abstraction. `LLMProvider` base class with `LLMResponse`/`ToolCallRequest` types. Provider selection is auto-detected from model name via `providers/registry.py` (`PROVIDERS` list). Adding a new provider requires: (1) a `ProviderSpec` in `registry.py`, (2) a field in `ProvidersConfig` in `config/schema.py`.

- **`nanobot/config/schema.py`** — Pydantic `Config` root with nested `AgentsConfig`, `ProvidersConfig`, `ChannelsConfig`, `ToolsConfig`, `GatewayConfig`. Env prefix: `NANOBOT_`, nested delimiter: `__`. Config also accepts camelCase keys (alias generator).

- **`nanobot/session/manager.py`** — Per-conversation session management (message history, context window).

- **`nanobot/agent/memory.py`** — `MemoryConsolidator`: token-based memory consolidation for long conversations.

- **`nanobot/cron/service.py`** — `CronService`: scheduled task execution.

- **`nanobot/heartbeat/service.py`** — Periodic background agent invocations.

- **`nanobot/skills/`** — Built-in skills as directories with `SKILL.md` files (YAML frontmatter + markdown instructions). Skills are injected into the system prompt. Available: `github`, `weather`, `summarize`, `tmux`, `clawhub`, `cron`, `memory`, `skill-creator`.

- **`nanobot/command/`** — Slash command routing (`/status`, `/restart`, etc.) via `CommandRouter`.

### Configuration

Config is loaded from `~/.nanobot/config.json` (default workspace: `~/.nanobot/workspace`). Provider selection is auto from model name prefix — e.g. `anthropic/claude-*` → Anthropic, `deepseek/*` → DeepSeek. Model format: `provider/model-name` or just `model-name`.

### Adding a channel plugin

See `docs/CHANNEL_PLUGIN_GUIDE.md`. Channels register via `nanobot.channels` entry point group.

### Tests

`pytest-asyncio` with `asyncio_mode = "auto"` — all async tests run automatically. Test files mirror the source structure under `tests/`.
