# nanobot System Prompt 组成结构

system prompt 由 `ContextBuilder.build_system_prompt()` 在每次 LLM 调用前动态组装，各部分以 `\n\n---\n\n` 分隔，按顺序拼接。

---

## 完整结构

```
┌─────────────────────────────────────────────┐
│  1. Identity（身份 & 行为准则）               │  必须，硬编码
├─────────────────────────────────────────────┤
│  2. Bootstrap Files（自定义覆盖文件）          │  可选，存在则注入
├─────────────────────────────────────────────┤
│  3. Memory（长期记忆）                        │  可选，MEMORY.md 非空则注入
├─────────────────────────────────────────────┤
│  4. Active Skills（常驻技能全文）             │  可选，always=true 的 skill
├─────────────────────────────────────────────┤
│  5. Skills Summary（技能摘要索引）             │  可选，有 skill 则注入
└─────────────────────────────────────────────┘
```

每个 user 消息前还有一个额外的 **Runtime Context** 块（不在 system prompt 内，注入到 user 消息头部）。

---

## 各部分详解

### 1. Identity（必须）

**来源：** `_get_identity()` 硬编码  
**内容：**

```markdown
# nanobot 🐈

You are nanobot, a helpful AI assistant.

## Runtime
macOS arm64, Python 3.14.3

## Workspace
Your workspace is at: /Users/mac/.nanobot/workspace
- Long-term memory: .../memory/MEMORY.md
- History log: .../memory/HISTORY.md
- Custom skills: .../skills/{skill-name}/SKILL.md

## Platform Policy (POSIX)
- Prefer UTF-8 and standard shell tools.
- Use file tools when simpler or more reliable than shell commands.

## nanobot Guidelines
- State intent before tool calls, but NEVER predict results before receiving them.
- Before modifying a file, read it first.
- ...（6 条行为准则）

Reply directly with text for conversations. Only use 'message' tool to send to specific channel.
IMPORTANT: To send files, you MUST call the 'message' tool with 'media' parameter...
```

包含运行平台（macOS/Windows/Linux）、workspace 路径、平台相关策略、核心行为准则。

---

### 2. Bootstrap Files（可选）

**来源：** workspace 根目录下的固定文件名，按序加载：

| 文件 | 用途 |
|------|------|
| `AGENTS.md` | 子 agent 行为说明、协作规则 |
| `SOUL.md` | 角色个性、语气风格定义 |
| `USER.md` | 用户背景、偏好描述 |
| `TOOLS.md` | 工具使用约定、自定义说明 |

文件不存在则跳过；存在则以 `## <filename>` 为标题注入。

**格式示例：**
```markdown
## SOUL.md

你叫小喵，说话风格活泼，喜欢用 emoji...

## USER.md

用户是一名后端工程师，熟悉 Python 和 Go...
```

---

### 3. Memory（可选）

**来源：** `{workspace}/memory/MEMORY.md`  
**加载方式：** `MemoryStore.get_memory_context()` — 文件非空则注入  
**格式：**

```markdown
# Memory

## Long-term Memory
## 项目
- 用户正在开发 Python 爬虫，文件位于 workspace/scraper.py

## 用户偏好
- 倾向于使用 pytest 而非 unittest
```

每次上下文压缩后由 LLM 更新写入，下次对话自动带上。  
> `HISTORY.md` **不注入** system prompt，只通过 `grep`/`read_file` 按需搜索。

---

### 4. Active Skills（可选）

**来源：** `{workspace}/skills/` 或内置 `nanobot/skills/` 中 `always: true` 的 skill  
**加载方式：** `SkillsLoader.get_always_skills()` → `load_skills_for_context()`（去除 frontmatter）  
**格式：**

```markdown
# Active Skills

### Skill: memory

## Structure
- `memory/MEMORY.md` — Long-term facts...
- `memory/HISTORY.md` — Append-only event log...

## When to Update MEMORY.md
...
```

内置 `memory` skill 默认 `always: true`，因此常驻 context。每个 `always` skill 的全文都会直接注入，占用固定 tokens。

---

### 5. Skills Summary（可选）

**来源：** 所有可发现的 skill（含不可用的）  
**加载方式：** `SkillsLoader.build_skills_summary()` → XML 格式  
**格式：**

```markdown
# Skills

The following skills extend your capabilities. To use a skill, read its SKILL.md file
using the read_file tool. Skills with available="false" need dependencies installed first.

<skills>
  <skill available="true">
    <name>weather</name>
    <description>Get current weather and forecasts (no API key required).</description>
    <location>/path/to/skills/weather/SKILL.md</location>
  </skill>
  <skill available="false">
    <name>github</name>
    <description>Interact with GitHub using the gh CLI.</description>
    <location>/path/to/skills/github/SKILL.md</location>
    <requires>CLI: gh</requires>
  </skill>
</skills>
```

LLM 读到摘要后，需主动调用 `read_file` 读取对应 SKILL.md 才能获取完整用法。`available="false"` 的 skill 仍显示，方便 LLM 提示用户安装依赖。

---

### Runtime Context（注入 user 消息头部，非 system prompt）

**来源：** `_build_runtime_context()` — 每条 user 消息前动态生成  
**格式：**

```
[Runtime Context — metadata only, not instructions]
Current Time: 2026-04-12 18:30 CST
Channel: telegram
Chat ID: 12345678
```

注入到每条 user 消息的最前面（与 user 文本合并为一条消息），避免部分 provider 不支持连续 system 消息的问题。保存到 session 时会自动去除此块。

---

## 组装顺序与分隔符

```python
# context.py: build_system_prompt()
parts = [
    _get_identity(),           # 1. 必须
    bootstrap,                 # 2. 可选
    "# Memory\n\n{memory}",   # 3. 可选
    "# Active Skills\n\n...", # 4. 可选
    "# Skills\n\n...",        # 5. 可选
]
return "\n\n---\n\n".join(parts)
```

各部分用 `---` 分隔，便于 LLM 区分结构边界。

---

## Token 占用参考

| 部分 | 典型 token 量 | 说明 |
|------|--------------|------|
| Identity | ~500 | 固定，随平台/workspace 路径略有变化 |
| Bootstrap Files | 0 ~ 数千 | 取决于用户自定义文件大小 |
| Memory | 0 ~ 2,000 | 随对话积累增长 |
| Active Skills | ~300/skill | memory skill 约 300 tokens |
| Skills Summary | ~50/skill | 每个 skill 的 XML 摘要 |

可用 `/context` 命令查看当前 system prompt 的实际 token 占用分布。

---

## 关键源文件

| 文件 | 职责 |
|------|------|
| `nanobot/agent/context.py` | `ContextBuilder`：组装 system prompt 和完整消息列表 |
| `nanobot/agent/memory.py` | `MemoryStore.get_memory_context()`：读取 MEMORY.md |
| `nanobot/agent/skills.py` | `SkillsLoader`：加载 skill 全文和摘要 |
| `{workspace}/AGENTS.md` 等 | Bootstrap 自定义文件 |
| `{workspace}/memory/MEMORY.md` | 持久化长期记忆 |
| `nanobot/skills/*/SKILL.md` | 内置 skill 定义 |
