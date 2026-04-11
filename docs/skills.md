# nanobot Skills 机制

## 核心概念

Skill 是一个目录，包含一个 `SKILL.md` 文件（必须）和可选的附属资源。它以"说明书"的形式扩展 Agent 能力，告诉 LLM 如何使用某个工具、执行某类任务，或持有某个领域的专有知识。

---

## 目录结构

```
skill-name/
├── SKILL.md              # 必须，frontmatter + 正文说明
├── scripts/              # 可选，可执行脚本（Python/Bash 等）
├── references/           # 可选，参考文档（按需加载到 context）
└── assets/               # 可选，输出用资源（模板、图片、字体等）
```

### SKILL.md 格式

```markdown
---
name: skill-name
description: 技能描述。应说明该技能做什么，以及在什么情况下触发使用。
homepage: https://...                          # 可选
metadata: {"nanobot":{"emoji":"🔧","requires":{"bins":["curl"],"env":["API_KEY"]}}}  # 可选
always: true                                   # 可选，设为 true 则全文常驻 context
---

# 技能正文

正文是给 LLM 阅读的实际使用说明，在技能触发后才会加载到 context。
```

**frontmatter 字段说明：**

| 字段 | 必填 | 说明 |
|------|------|------|
| `name` | ✅ | skill 名称，与目录名一致 |
| `description` | ✅ | 触发机制：LLM 通过此字段判断何时读取该 skill |
| `metadata` | ❌ | JSON 字符串，支持 `emoji`、`requires`（`bins`/`env` 依赖检查） |
| `always` | ❌ | 设为 `true` 则正文常驻 system prompt（不需手动触发） |
| `homepage` | ❌ | 技能相关主页链接，仅供展示 |

---

## 存放位置

`SkillsLoader` 从两个位置加载 skill，**workspace 优先级高于内置**：

| 类型 | 路径 | 说明 |
|------|------|------|
| 内置 skill | `nanobot/skills/<skill-name>/` | 随包发布，如 `weather`、`github`、`memory` |
| 用户自定义 skill | `~/.nanobot/workspace/skills/<skill-name>/` | 用户创建，可覆盖同名内置 skill |

同名 skill 以 workspace 版本为准，内置版本被忽略。

---

## 注入 System Prompt 的流程

`ContextBuilder.build_system_prompt()`（`nanobot/agent/context.py`）在每次构建 system prompt 时按以下顺序处理 skill：

```
build_system_prompt()
  │
  ├── 1. _get_identity()          # 基础身份 + 运行时信息
  ├── 2. _load_bootstrap_files()  # AGENTS.md / SOUL.md / USER.md / TOOLS.md
  ├── 3. memory.get_memory_context()   # MEMORY.md 长期记忆
  │
  ├── 4. skills.get_always_skills()         # 找出 always=true 的 skill
  │       └── load_skills_for_context()     # 去掉 frontmatter，全文注入
  │             → 注入为 "# Active Skills" 块（全文常驻）
  │
  └── 5. skills.build_skills_summary()      # 所有 skill 的摘要（XML）
            → 注入为 "# Skills" 块（仅 name + description + path）
```

### 两种注入模式对比

| 模式 | 触发条件 | 注入内容 | token 消耗 |
|------|----------|----------|------------|
| **Active Skills**（全文）| `always: true` | 完整 SKILL.md 正文 | 高（常驻） |
| **Skills Summary**（摘要）| 所有 skill | `<skill>` XML 摘要（name + description + path） | 低（仅元数据） |

### Skills Summary 示例（注入到 system prompt 的格式）

```xml
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

LLM 看到摘要后，需要用 `read_file` 工具读取 `<location>` 路径才能获取 skill 正文。

---

## Progressive Disclosure（渐进加载）设计

Skill 采用三层加载机制节省 context：

```
Level 1 — 元数据（name + description）
  └── 始终在 context 中，约 ~100 tokens
        ↓ LLM 判断需要使用该 skill
Level 2 — SKILL.md 正文
  └── LLM 调用 read_file 读取，建议 < 500 行
        ↓ 需要更详细资料
Level 3 — scripts / references / assets
  └── LLM 按需调用 read_file 或 exec 读取/执行
```

---

## 内置 Skills 一览

| Skill | always | 说明 |
|-------|--------|------|
| `memory` | ✅ | 两层记忆系统（MEMORY.md + HISTORY.md），常驻 context |
| `github` | ❌ | 使用 `gh` CLI 操作 GitHub |
| `weather` | ❌ | wttr.in + Open-Meteo 查询天气（需要 `curl`） |
| `summarize` | ❌ | 总结 URL、文件、YouTube 视频 |
| `tmux` | ❌ | 远程控制 tmux 会话 |
| `cron` | ❌ | 定时任务管理 |
| `clawhub` | ❌ | 从 ClawHub 公共注册表搜索和安装 skill |
| `skill-creator` | ❌ | 创建新 skill 的完整指导流程 |

---

## 创建自定义 Skill

### 方式一：手动创建

```
~/.nanobot/workspace/skills/my-skill/
└── SKILL.md
```

```markdown
---
name: my-skill
description: 描述此 skill 做什么，以及用户说什么话时应触发。
---

# My Skill

## 使用方法
...
```

### 方式二：使用 skill-creator（推荐）

触发内置的 `skill-creator` skill（让 Agent 读取该 skill 后，按 6 步流程创建）：

```
# 初始化 skill 目录结构
python scripts/init_skill.py my-skill --path ~/.nanobot/workspace/skills

# 编辑 SKILL.md 和资源文件后打包
python scripts/package_skill.py ~/.nanobot/workspace/skills/my-skill
```

### 方式三：通过 ClawHub 安装

```bash
npx --yes clawhub@latest search "web scraping" --limit 5
npx --yes clawhub@latest install <slug> --workdir ~/.nanobot/workspace
```

安装后重启会话生效。

---

## 依赖检查（requirements）

`metadata` 中的 `requires` 字段用于声明依赖，`SkillsLoader._check_requirements()` 在构建摘要前检查：

```json
{"nanobot": {"requires": {"bins": ["curl", "gh"], "env": ["GITHUB_TOKEN"]}}}
```

- `bins`：检查系统 PATH 中是否存在该命令（`shutil.which()`）
- `env`：检查环境变量是否已设置

依赖未满足的 skill 在摘要中标记为 `available="false"` 并显示缺失项，但仍出现在摘要中（LLM 可提示用户安装）。

---

## 关键源文件

| 文件 | 职责 |
|------|------|
| `nanobot/agent/skills.py` | `SkillsLoader`：发现、加载、过滤、生成摘要 |
| `nanobot/agent/context.py` | `ContextBuilder.build_system_prompt()`：将 skill 注入 system prompt |
| `nanobot/skills/*/SKILL.md` | 内置 skill 定义 |
| `~/.nanobot/workspace/skills/*/SKILL.md` | 用户自定义 skill |
