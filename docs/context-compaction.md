# nanobot 上下文自动压缩（Context Compaction）机制

## 核心概念

当对话历史积累到一定长度，prompt tokens 超出预算时，nanobot 自动触发上下文压缩：将旧对话提炼为摘要持久化到文件，从 session 中移除，从而腾出 context 空间继续对话。

---

## 触发时机

每条消息处理时，`maybe_consolidate_by_tokens(session)` 被调用两次：

| 时机 | 方式 | 说明 |
|------|------|------|
| LLM 调用前 | 同步等待 | 确保 prompt 在预算内才发送 |
| 响应返回后 | 后台任务 | 异步清理，不阻塞用户 |

**预算公式：**

```
budget = context_window_tokens - max_completion_tokens - 1024（safety buffer）
target = budget // 2   ← 压缩后的目标水位
```

超过 `budget` 时开始压缩，循环执行直到 tokens 低于 `target`，最多 5 轮（`_MAX_CONSOLIDATION_ROUNDS`）。

---

## 压缩流程

```
检测到 prompt tokens > budget
  │
  └── pick_consolidation_boundary()
        找从 last_consolidated 往后、移除 tokens 足够多的下一个 user turn 边界
        确保始终以完整对话轮次（user + assistant）为单位压缩
  │
  └── 取 messages[last_consolidated : boundary]
        │
        └── MemoryStore.consolidate()
              │
              ├── 构造 LLM 请求：
              │     system: "You are a memory consolidation agent.
              │              Call the save_memory tool with your consolidation."
              │     user:   当前 MEMORY.md 内容 + 待压缩的格式化对话
              │     tool_choice: {"name": "save_memory"}（强制调用）
              │
              ├── LLM 返回 save_memory 工具调用，包含两个字段：
              │     history_entry  — 带时间戳的一段摘要，起始格式：[YYYY-MM-DD HH:MM]
              │     memory_update  — 完整更新后的 MEMORY.md 内容
              │
              ├── history_entry  → 追加到 memory/HISTORY.md
              └── memory_update  → 覆盖写 memory/MEMORY.md（若有变化）
  │
  └── session.last_consolidated = boundary（滑动游标前移）
  └── 保存 session
  └── 重估 tokens，未达 target 则继续下一轮
```

---

## 两层持久化记忆

| 文件 | 内容 | 是否注入 context |
|------|------|----------------|
| `memory/MEMORY.md` | 长期事实：用户偏好、项目背景、重要约定 | **是**，每次对话注入 system prompt |
| `memory/HISTORY.md` | 追加式事件日志，每条带时间戳 | **否**，只通过 `grep`/`read_file` 按需搜索 |

`MEMORY.md` 由 LLM 在每次压缩时负责更新（合并旧内容 + 新提取的事实）；`HISTORY.md` 只追加，永不修改。

---

## Session 游标机制

```
session.messages          [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]   ← 只追加，永不删除
                                          ↑
session.last_consolidated = 5            │
                                         └── get_history() 返回 [5..9]
                                             （只有未压缩部分送入 LLM）
```

- `session.messages`：完整历史，只追加，从不删除
- `session.last_consolidated`：压缩边界索引，持久化到 session 文件
- `get_history()` 返回 `messages[last_consolidated:]`

重启后从磁盘恢复 `last_consolidated`，不会重复压缩已处理的消息。

---

## 降级策略

LLM 压缩调用连续失败 3 次后，自动降级为 **raw-archive**：

- 跳过 LLM 调用
- 将原始消息文本直接写入 `HISTORY.md`，标记为 `[RAW]`
- 重置失败计数

确保即使 LLM 不可用，对话仍能继续而不卡死。

---

## 关键源文件

| 文件 | 职责 |
|------|------|
| `nanobot/agent/memory.py` | `MemoryConsolidator`（触发逻辑）+ `MemoryStore`（LLM 压缩 + 文件持久化） |
| `nanobot/agent/loop.py` | 两处调用入口（`_process_message` 第 454、491 行） |
| `nanobot/agent/context.py` | `ContextBuilder`：将 MEMORY.md 注入 system prompt |
| `nanobot/session/manager.py` | `Session`：`messages` 列表 + `last_consolidated` 游标 |
| `tests/agent/test_loop_consolidation_tokens.py` | 触发阈值与循环逻辑测试 |
| `tests/agent/test_consolidate_offset.py` | 游标持久化与跳过已压缩消息测试 |
| `tests/agent/test_memory_consolidation_types.py` | LLM 返回格式兼容性 + 降级策略测试 |
