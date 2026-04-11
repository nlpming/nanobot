---
name: code-review
description: >
  审查代码质量、潜在 bug、性能问题和可维护性。
  当用户提交 PR、询问"帮我看看这段代码"、
  或提到"代码审查/code review"时自动触发。
argument-hint: "[文件路径或 PR 编号]"
allowed-tools: Read Grep Glob Bash(git *)
effort: medium
---

# Code Review Skill

审查 $ARGUMENTS 的代码质量。

## 审查流程

1. **读取代码**：用 Read 工具读取目标文件
2. **运行 git diff**：了解本次变更范围
3. **对照清单审查**：见 [CHECKLIST.md](CHECKLIST.md)
4. **生成报告**：执行脚本生成结构化上下文

```bash
python ${CLAUDE_SKILL_DIR}/scripts/summary.py "$ARGUMENTS"
```

## 输出格式

按以下结构输出审查结果：

- 🔴 **严重问题**：需要立即修复的 bug 或安全漏洞
- 🟡 **改进建议**：性能、可读性、重构机会
- 🟢 **做得好的地方**：值得肯定的实践

如需参考具体示例，见 [EXAMPLES.md](EXAMPLES.md)。
