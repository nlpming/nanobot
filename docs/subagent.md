# nanobot Subagent 机制

## 核心概念

Subagent 是主 Agent 在后台派生的独立执行单元，用于处理复杂或耗时的任务。主 Agent 通过 `spawn` 工具触发，Subagent 完成后通过消息总线回传结果给主 Agent。

---

## 调用流程

```
用户消息
  └── AgentLoop (主 Agent)
        └── LLM 决定调用 spawn 工具
              └── SpawnTool.execute()
                    └── SubagentManager.spawn()
                          └── asyncio.create_task(_run_subagent())  ← 后台异步运行
                                ├── 构建独立 ToolRegistry
                                ├── 构建 subagent system prompt
                                ├── AgentRunner.run()  ← 独立 LLM 循环，最多 15 轮
                                └── _announce_result()
                                      └── bus.publish_inbound()  ← 注入 system 消息触发主 Agent
                                            └── AgentLoop 接收，LLM 总结结果回复用户
```

---

## 定义 Subagent

Subagent **不需要开发者单独定义**，它复用通用的 `AgentRunner` + `ToolRegistry`，通过 `_build_subagent_prompt()` 构建专属 system prompt。

### Subagent 拥有的工具

`SubagentManager._run_subagent()` 为每次执行单独构建一套工具（**不共享**主 Agent 的 registry）：

| 工具 | 说明 |
|------|------|
| `read_file` | 读文件 |
| `write_file` | 写文件 |
| `edit_file` | 编辑文件 |
| `list_dir` | 列目录 |
| `exec` | 执行 shell 命令 |
| `web_search` | 网络搜索 |
| `web_fetch` | 抓取网页 |

> **注意**：Subagent **没有** `message`（不能直接发送消息给用户）和 `spawn`（不能递归派生子 Subagent）。

### Subagent System Prompt 构成

由 `_build_subagent_prompt()` 生成，包含：

```
# Subagent
[运行时上下文：当前时间等]

You are a subagent spawned by the main agent to complete a specific task.
Stay focused on the assigned task...

## Workspace
/path/to/workspace

## Skills
[可用 skills 列表，通过 read_file 读取 SKILL.md 使用]
```

与主 Agent 的区别：**无 Memory**（MEMORY.md / HISTORY.md 不注入）、**无 bootstrap 文件**（AGENTS.md / SOUL.md）、**最大迭代次数为 15**（主 Agent 默认 40）。

---

## 调用 Subagent（`spawn` 工具）

主 Agent 的 LLM 通过调用 `spawn` 工具来派生 Subagent：

```json
{
  "tool": "spawn",
  "arguments": {
    "task": "搜索 Python 异步编程最佳实践，整理成 markdown 文件保存到 workspace/async_guide.md",
    "label": "async-guide"
  }
}
```

**参数说明：**

| 参数 | 必填 | 说明 |
|------|------|------|
| `task` | ✅ | 完整的任务描述，直接作为 `user` 消息传给 Subagent LLM |
| `label` | ❌ | 短标签，用于展示和日志（默认取 task 前 30 字符） |

**返回值（主 Agent 立即收到）：**
```
Subagent [async-guide] started (id: a3f2c1d8). I'll notify you when it completes.
```

---

## 结果回传机制

Subagent 执行完毕后，`_announce_result()` 将结果封装为一条 `InboundMessage` 注入消息总线：

```python
InboundMessage(
    channel="system",
    sender_id="subagent",
    chat_id="telegram:12345678",   # 继承主 Agent 的 origin
    content="""[Subagent 'async-guide' completed successfully]

Task: 搜索 Python 异步编程最佳实践...

Result:
<subagent 的最终回复>

Summarize this naturally for the user. Keep it brief (1-2 sentences)..."""
)
```

主 Agent 的 `AgentLoop` 接收到这条消息后，LLM 会将结果总结成自然语言回复用户。

---

## 生命周期与取消

- Subagent 以 `asyncio.Task` 形式在后台并发运行，不阻塞主 Agent 处理其他消息
- 每个 Subagent 分配一个 8 位 UUID 作为 `task_id`，按 `session_key` 分组管理
- 用户发送 `/stop` 时，`cancel_by_session()` 会取消该会话下所有正在运行的 Subagent
- `fail_on_tool_error=True`：任意工具报错则停止，将已完成步骤和错误一并上报（部分进度格式化由 `_format_partial_progress()` 处理）

---

## 扩展：自定义 Subagent 行为

如需自定义（例如在 skill 中派生专用 Subagent），目前只能通过 `spawn` 工具的 `task` 参数传递详细指令。框架层面暂无注入自定义工具或 prompt 的扩展点——Subagent 的工具集和 system prompt 硬编码在 `SubagentManager._run_subagent()` 中。
