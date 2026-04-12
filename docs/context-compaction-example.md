# nanobot 上下文压缩完整流程示例

以一次真实的长对话为例，演示从触发条件到文件持久化的完整过程。

---

## 场景设定

```
context_window_tokens  = 65,536
max_completion_tokens  = 8,192
safety_buffer          = 1,024

budget = 65,536 - 8,192 - 1,024 = 56,320 tokens
target = 56,320 // 2             = 28,160 tokens   ← 压缩后的目标
```

用户和 nanobot 已进行了一段时间的对话，session 中积累了 10 条消息：

```
session.messages (索引 0–9):
  [0] user      "帮我写一个 Python 爬虫"          ~800 tokens
  [1] assistant "好的，这里是代码：..."           ~1200 tokens
  [2] user      "加上代理支持"                    ~200 tokens
  [3] assistant "已更新，新增代理逻辑..."         ~900 tokens
  [4] user      "再加上重试机制"                  ~200 tokens
  [5] assistant "好的，加入了 tenacity 重试..."   ~1100 tokens
  [6] user      "帮我写单元测试"                  ~300 tokens
  [7] assistant "这里是测试代码..."               ~1500 tokens
  [8] user      "解释一下 mock 的用法"            ~300 tokens
  [9] assistant "mock 是用来..."                  ~800 tokens

session.last_consolidated = 0    ← 全部都是"未压缩"消息
```

---

## 第一步：触发检测

用户发来新消息 `"帮我加上日志记录"`，进入 `_process_message()`：

```python
# loop.py
await self.memory_consolidator.maybe_consolidate_by_tokens(session)
```

**估算当前 prompt tokens：**

`estimate_session_prompt_tokens()` 构造探针请求：

```
system prompt（身份 + 技能摘要 + MEMORY.md）   ~6,000 tokens
历史消息 [0..9]                                ~7,300 tokens
当前消息 "[token-probe]"                          ~10 tokens
工具定义                                        ~3,200 tokens
─────────────────────────────────────────────────────────
估算总计                                       ~16,510 tokens
```

16,510 < 56,320（budget），**未触发压缩**，继续正常处理。

---

## 若干轮之后……

对话继续，消息累积到 60 条。估算结果：

```
system prompt     ~6,000 tokens
历史消息 [0..59]  ~52,000 tokens
当前消息            ~500 tokens
工具定义           ~3,200 tokens
─────────────────────────────────
估算总计          ~61,700 tokens
```

**61,700 > 56,320（budget）** → 触发压缩。

---

## 第二步：压缩循环（Round 0）

```python
# memory.py: maybe_consolidate_by_tokens()
budget   = 56,320
target   = 28,160
estimated = 61,700   # 超出 budget

tokens_to_remove = estimated - target = 61,700 - 28,160 = 33,540 tokens
```

**`pick_consolidation_boundary()` 找边界：**

从 `last_consolidated=0` 开始，逐条累加 tokens，找第一个"移除量 ≥ 33,540"的 user turn 边界：

```
idx=0  user      800 tokens  → 累计 800    （不够）
idx=1  assistant 1200 tokens → 累计 2000
idx=2  user      ← boundary 候选，累计 2000 tokens（不够）
...
idx=36 user      ← boundary 候选，累计 34,100 tokens ✓（超过 33,540）
→ 返回 boundary = (36, 34,100)
```

**取出待压缩的消息块：**

```python
chunk = session.messages[0:36]   # 36 条消息，约 34,100 tokens
```

---

## 第三步：调用 LLM 压缩（MemoryStore.consolidate）

**构造请求：**

```
system:
  "You are a memory consolidation agent. Call the save_memory tool
   with your consolidation of the conversation."

user:
  "Process this conversation and call the save_memory tool with your consolidation.

  ## Current Long-term Memory
  (empty)

  ## Conversation to Process
  [2026-04-10 09:15] USER: 帮我写一个 Python 爬虫
  [2026-04-10 09:15] ASSISTANT: 好的，这里是代码：import requests...
  [2026-04-10 09:17] USER: 加上代理支持
  [2026-04-10 09:17] ASSISTANT [tools: write_file]: 已更新，新增代理逻辑...
  ... （共 36 条）
  [2026-04-10 10:42] USER: 解释一下异步爬虫的优势
  [2026-04-10 10:43] ASSISTANT: 异步爬虫使用 asyncio..."

tool_choice: {"type": "function", "function": {"name": "save_memory"}}
```

**LLM 返回 `save_memory` 工具调用：**

```json
{
  "history_entry": "[2026-04-10 09:15] 用户请求编写 Python 爬虫，逐步添加了代理支持（使用 requests Session + proxies 参数）、tenacity 重试机制（max_attempts=3, wait_exponential）、单元测试（pytest + unittest.mock）、日志记录（logging.basicConfig）。讨论了 mock 用法和异步爬虫（aiohttp）的优势。最终代码保存在 workspace/scraper.py。",

  "memory_update": "## 项目\n- 用户正在开发 Python 爬虫项目，文件位于 workspace/scraper.py\n- 使用 requests + tenacity + aiohttp\n- 已完成：代理、重试、日志、单元测试\n\n## 用户偏好\n- 喜欢在代码中加入完整的错误处理\n- 倾向于使用 pytest 而非 unittest"
}
```

**持久化：**

```
memory/HISTORY.md  ← 追加 history_entry
─────────────────────────────────────────────
[2026-04-10 09:15] 用户请求编写 Python 爬虫，逐步添加了代理支持...


memory/MEMORY.md   ← 覆盖写 memory_update
─────────────────────────────────────────────
## 项目
- 用户正在开发 Python 爬虫项目，文件位于 workspace/scraper.py
- 使用 requests + tenacity + aiohttp
- 已完成：代理、重试、日志、单元测试

## 用户偏好
- 喜欢在代码中加入完整的错误处理
- 倾向于使用 pytest 而非 unittest
```

---

## 第四步：更新游标，重估 tokens

```python
session.last_consolidated = 36   # 游标前移
sessions.save(session)           # 持久化到磁盘

# 重估（现在历史只剩 [36..59]，24 条消息）
estimated = 28,050 tokens
```

28,050 ≤ 28,160（target），**压缩完成，退出循环**。

---

## 第五步：正常处理用户消息

压缩后，`get_history()` 返回 `messages[36:]`（24 条），加上更新后的 MEMORY.md，重新构造 prompt：

```
system prompt（包含更新后的 MEMORY.md）    ~6,500 tokens
历史消息 [36..59]                          ~18,000 tokens
当前消息 "帮我加上日志记录"                   ~500 tokens
工具定义                                    ~3,200 tokens
─────────────────────────────────────────────────────────
总计                                       ~28,200 tokens   ✓ 在预算内
```

LLM 调用正常进行，用户无感知地继续对话。

---

## 状态变化总结

```
压缩前：
  messages       = [0, 1, 2, ..., 59]
  last_consolidated = 0
  MEMORY.md      = (empty)
  HISTORY.md     = (empty)
  estimated tokens = 61,700  ← 超出 budget

压缩后：
  messages       = [0, 1, 2, ..., 59]   ← 原始数据不变，永不删除
  last_consolidated = 36                 ← 游标前移
  MEMORY.md      = "## 项目\n..."        ← 长期事实
  HISTORY.md     = "[2026-04-10 09:15]..." ← 摘要日志
  estimated tokens = 28,050  ← 低于 target ✓
```

---

## 降级示例（LLM 连续失败）

若 LLM 连续 3 次未能调用 `save_memory`，自动降级为 raw-archive：

```
memory/HISTORY.md 追加：
─────────────────────────────────────────────
[2026-04-10 11:00] [RAW] 36 messages
[2026-04-10 09:15] USER: 帮我写一个 Python 爬虫
[2026-04-10 09:15] ASSISTANT: 好的，这里是代码...
...
```

对话照常继续，不会因记忆压缩失败而卡死。

---

## 关键参数一览

| 参数 | 默认值 | 含义 |
|------|--------|------|
| `context_window_tokens` | 65,536 | context 窗口大小 |
| `max_completion_tokens` | 8,192 | 预留给 LLM 输出的空间 |
| `_SAFETY_BUFFER` | 1,024 | tokenizer 误差缓冲 |
| `budget` | 56,320 | 触发阈值 |
| `target` | 28,160 | 压缩后的目标水位 |
| `_MAX_CONSOLIDATION_ROUNDS` | 5 | 单次触发最多压缩轮数 |
| `_MAX_FAILURES_BEFORE_RAW_ARCHIVE` | 3 | 降级前允许失败次数 |
