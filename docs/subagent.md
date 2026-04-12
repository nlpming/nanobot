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
                                ├── 加载自定义 agent 定义（如有）
                                ├── 构建独立 ToolRegistry（可按 agent 定义过滤）
                                ├── 构建 system prompt（通用或自定义）
                                ├── AgentRunner.run()  ← 独立 LLM 循环，最多 15 轮
                                └── _announce_result()
                                      └── bus.publish_inbound()  ← 注入 system 消息触发主 Agent
                                            └── AgentLoop 接收，LLM 总结结果回复用户
```

---

## 调用 Subagent（`spawn` 工具）

主 Agent 的 LLM 通过调用 `spawn` 工具派生 Subagent：

```json
{
  "tool": "spawn",
  "arguments": {
    "task": "搜索 Python 异步编程最佳实践，整理成 markdown 文件保存到 workspace/async_guide.md",
    "agent": "code-reviewer",
    "label": "async-guide"
  }
}
```

**参数说明：**

| 参数 | 必填 | 说明 |
|------|------|------|
| `task` | ✅ | 完整的任务描述，直接作为 `user` 消息传给 Subagent LLM |
| `agent` | ❌ | 自定义 agent 名称（见下文），省略则使用通用 Subagent |
| `label` | ❌ | 短标签，用于展示和日志（默认取 task 前 30 字符） |

**返回值（主 Agent 立即收到）：**
```
Subagent [async-guide] started (id: a3f2c1d8) (agent: code-reviewer). I'll notify you when it completes.
```

---

## 默认 Subagent

不指定 `agent` 参数时，使用通用 Subagent。

### 可用工具

| 工具 | 说明 |
|------|------|
| `read_file` | 读文件 |
| `write_file` | 写文件 |
| `edit_file` | 编辑文件 |
| `list_dir` | 列目录 |
| `exec` | 执行 shell 命令 |
| `web_search` | 网络搜索 |
| `web_fetch` | 抓取网页 |

> **注意**：Subagent **没有** `message`（不能直接发消息给用户）和 `spawn`（不能递归派生）。

### System Prompt 构成

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

与主 Agent 的区别：**无 Memory**（不注入 MEMORY.md / HISTORY.md）、**无 bootstrap 文件**（AGENTS.md / SOUL.md）、**最大迭代次数为 15**（主 Agent 默认 40）。

---

## 自定义 Agent

通过编写 Markdown 文件可以定义专用 Agent，覆盖模型、工具集和系统提示。

### 文件位置

| 优先级 | 路径 | 说明 |
|--------|------|------|
| 高 | `{workspace}/agents/<name>.md` | 项目级，覆盖同名全局 agent |
| 低 | `~/.nanobot/agents/<name>.md` | 全局，所有项目共享 |

文件名（不含 `.md` 后缀）即 agent 名称，也是 `spawn` 工具 `agent` 参数的值。

### 文件格式

```markdown
---
name: agent-name
description: 何时应该使用该 agent（LLM 根据此字段判断）
model: anthropic/claude-haiku-4-5    # 可选，覆盖默认模型
tools:                                # 可选，省略则使用全部默认工具
  - read_file
  - list_dir
---

# Agent 角色

系统提示正文（会替换通用 Subagent 的 system prompt）。
```

### Frontmatter 字段说明

| 字段 | 必填 | 说明 |
|------|------|------|
| `name` | ✅ | Agent 名称，与文件名一致 |
| `description` | ✅ | LLM 用来判断何时使用该 agent，应描述专长和使用场景 |
| `model` | ❌ | 覆盖默认模型，可用更小/更快的模型节省成本 |
| `tools` | ❌ | 限制可用工具列表，省略则拥有全部默认工具 |

### 可选工具名称

在 `tools` 字段中可以使用以下工具名：

```
read_file   write_file   edit_file   list_dir
exec        web_search   web_fetch
```

### System Prompt 结构（自定义 Agent）

```
# Agent: <name>
[运行时上下文：当前时间等]

<AGENT.md 正文>

## Workspace
/path/to/workspace

## Skills
[可用 skills 列表]
```

自定义 agent 的正文**完整替换**通用 Subagent 的 prompt，但运行时上下文和 workspace 路径仍会自动附加。

---

## 示例：代码审查 Agent

**文件路径：** `{workspace}/agents/code-reviewer.md`

```markdown
---
name: code-reviewer
description: 对代码进行安全漏洞、性能问题和最佳实践的专项审查
model: anthropic/claude-haiku-4-5
tools:
  - read_file
  - list_dir
---

# 代码审查专家

你是一位专业的代码审查专家，专注于发现代码中的问题并给出改进建议。

## 审查维度

1. **安全性** — SQL 注入、XSS、命令注入、敏感信息泄露、不安全的依赖
2. **性能** — N+1 查询、不必要的计算、内存泄漏、阻塞调用
3. **可维护性** — 命名规范、函数职责、重复代码、注释缺失
4. **健壮性** — 边界条件、错误处理、类型安全

## 输出格式

每个问题按如下结构报告：

\`\`\`
[严重程度: 严重/警告/建议] 文件:行号
问题描述
修复建议
\`\`\`

## 注意事项

- 只读取和分析文件，不修改任何代码
- 最后给出总体评分（1-10）和优先修复清单
```

**调用方式：**

```
spawn(task="审查 nanobot/agent/subagent.py，重点关注安全性和错误处理", agent="code-reviewer")
```

---

## 可用 Agent 列表展示

`SpawnTool` 的工具描述会**动态**包含当前所有可用的自定义 agent：

```xml
Available custom agents:
<agents>
  <agent>
    <name>code-reviewer</name>
    <description>对代码进行安全漏洞、性能问题和最佳实践的专项审查</description>
    <model>anthropic/claude-haiku-4-5</model>
  </agent>
</agents>
```

LLM 看到此列表后，可以在合适时机自动选择对应 agent。

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

## 关键源文件

| 文件 | 职责 |
|------|------|
| `nanobot/agent/agents.py` | `AgentLoader`：发现和加载自定义 agent 定义，解析 frontmatter，生成摘要 |
| `nanobot/agent/subagent.py` | `SubagentManager`：派生、执行、结果回传，应用自定义 agent 配置 |
| `nanobot/agent/tools/spawn.py` | `SpawnTool`：暴露给 LLM 的 `spawn` 工具，动态展示可用 agent 列表 |
| `{workspace}/agents/*.md` | 项目级自定义 agent 定义 |
| `~/.nanobot/agents/*.md` | 全局自定义 agent 定义 |
