#!/usr/bin/env python3
"""生成代码审查摘要报告 - 收集 git 上下文供 Claude 使用"""

import sys
import subprocess
from pathlib import Path
from datetime import datetime


def run(cmd: list) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True).stdout.strip()
    except Exception:
        return ""


def get_git_stats(filepath: str) -> dict:
    diff_stat = run(["git", "diff", "HEAD~1", "--stat", "--", filepath])
    diff_content = run(["git", "diff", "HEAD~1", "--", filepath])
    recent_commits = run(["git", "log", "--oneline", "-5", "--", filepath])
    branch = run(["git", "branch", "--show-current"])
    return {
        "diff_stat": diff_stat or "（无变更或非 git 仓库）",
        "diff_content": diff_content[:3000] if diff_content else "（无 diff）",
        "recent_commits": recent_commits or "（无提交记录）",
        "branch": branch or "unknown",
    }


def count_lines(filepath: str) -> int:
    try:
        p = Path(filepath)
        if p.is_file():
            return len(p.read_text(encoding="utf-8", errors="ignore").splitlines())
    except Exception:
        pass
    return 0


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "."
    stats = get_git_stats(target)
    lines = count_lines(target)

    print(f"""
╔══════════════════════════════════════╗
║         代码审查上下文摘要           ║
╚══════════════════════════════════════╝

目标：       {target}
总行数：     {lines if lines else "（目录）"}
当前分支：   {stats['branch']}
审查时间：   {datetime.now().strftime('%Y-%m-%d %H:%M')}

── 最近 5 次提交 ──────────────────────
{stats['recent_commits']}

── Git 变更摘要 ────────────────────────
{stats['diff_stat']}

── Diff 内容（前 3000 字符）────────────
{stats['diff_content']}
""")


if __name__ == "__main__":
    main()
