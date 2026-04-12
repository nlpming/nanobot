"""
Notes MCP Server — 笔记管理 MCP 服务器

提供工具：
  - create_note(title, content)  创建/覆盖笔记
  - list_notes()                 列出所有笔记（文件名 + 首行预览）
  - read_note(title)             读取笔记全文
  - delete_note(title)           删除笔记
  - search_notes(query)          在所有笔记中搜索关键词

笔记保存为 Markdown 文件（.md），存放在 --notes-dir 指定的目录
（默认 ~/.nanobot/workspace/notes）。

用法：
  python notes_server.py                        # stdio 模式（nanobot 默认）
  python notes_server.py --notes-dir /your/dir  # 指定笔记目录

nanobot config.json 配置示例：
  {
    "tools": {
      "mcpServers": {
        "notes": {
          "command": "python",
          "args": ["/path/to/examples/mcp/notes_server.py",
                   "--notes-dir", "~/.nanobot/workspace/notes"]
        }
      }
    }
  }
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


# ---------------------------------------------------------------------------
# 业务逻辑层（可独立测试，不依赖 MCP SDK）
# ---------------------------------------------------------------------------

class NoteStore:
    """Manages markdown notes in a directory."""

    def __init__(self, notes_dir: Path) -> None:
        self.notes_dir = notes_dir
        self.notes_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, title: str) -> Path:
        """Convert a title to a safe filename."""
        safe = re.sub(r'[^\w\s\-]', '', title).strip()
        safe = re.sub(r'\s+', '-', safe).lower()
        if not safe:
            raise ValueError(f"Invalid note title: {title!r}")
        return self.notes_dir / f"{safe}.md"

    def create(self, title: str, content: str) -> str:
        """Create or overwrite a note. Returns the file path."""
        path = self._path(title)
        path.write_text(f"# {title}\n\n{content}", encoding="utf-8")
        return str(path)

    def list_notes(self) -> list[dict[str, str]]:
        """Return all notes with title and first-line preview."""
        results = []
        for md_file in sorted(self.notes_dir.glob("*.md")):
            text = md_file.read_text(encoding="utf-8")
            lines = [l for l in text.splitlines() if l.strip()]
            title = lines[0].lstrip("# ").strip() if lines else md_file.stem
            preview = lines[1].strip() if len(lines) > 1 else ""
            results.append({"title": title, "preview": preview, "file": md_file.name})
        return results

    def read(self, title: str) -> str:
        """Read a note. Raises FileNotFoundError if not found."""
        path = self._path(title)
        if not path.exists():
            raise FileNotFoundError(f"Note not found: {title!r}")
        return path.read_text(encoding="utf-8")

    def delete(self, title: str) -> bool:
        """Delete a note. Returns True if deleted, False if not found."""
        path = self._path(title)
        if path.exists():
            path.unlink()
            return True
        return False

    def search(self, query: str) -> list[dict[str, str]]:
        """Search all notes for a keyword. Returns matching notes with snippets."""
        q = query.lower()
        results = []
        for md_file in sorted(self.notes_dir.glob("*.md")):
            text = md_file.read_text(encoding="utf-8")
            if q in text.lower():
                # Find the first matching line as snippet
                snippet = next(
                    (line.strip() for line in text.splitlines() if q in line.lower()),
                    "",
                )
                title = md_file.stem.replace("-", " ").title()
                results.append({"title": title, "snippet": snippet, "file": md_file.name})
        return results


# ---------------------------------------------------------------------------
# MCP 层（包装 NoteStore 工具，注册到 FastMCP）
# ---------------------------------------------------------------------------

def build_mcp_server(store: NoteStore):
    """Create and configure the FastMCP server with NoteStore tools."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("notes")

    @mcp.tool()
    def create_note(title: str, content: str) -> str:
        """创建或覆盖一条笔记。title 为笔记标题，content 为 Markdown 正文。"""
        path = store.create(title, content)
        return f"Note '{title}' saved to {path}"

    @mcp.tool()
    def list_notes() -> str:
        """列出所有笔记，每条包含标题和首行预览。"""
        notes = store.list_notes()
        if not notes:
            return "No notes found."
        lines = [f"- **{n['title']}**: {n['preview']}" if n["preview"] else f"- **{n['title']}**"
                 for n in notes]
        return f"{len(notes)} note(s):\n" + "\n".join(lines)

    @mcp.tool()
    def read_note(title: str) -> str:
        """读取指定笔记的完整内容。"""
        try:
            return store.read(title)
        except FileNotFoundError as e:
            return f"Error: {e}"

    @mcp.tool()
    def delete_note(title: str) -> str:
        """删除指定笔记。"""
        deleted = store.delete(title)
        return f"Note '{title}' deleted." if deleted else f"Note '{title}' not found."

    @mcp.tool()
    def search_notes(query: str) -> str:
        """在所有笔记中搜索关键词，返回匹配的笔记列表和片段。"""
        results = store.search(query)
        if not results:
            return f"No notes matching '{query}'."
        lines = [f"- **{r['title']}**: …{r['snippet']}…" for r in results]
        return f"{len(results)} match(es) for '{query}':\n" + "\n".join(lines)

    return mcp


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Notes MCP Server")
    parser.add_argument(
        "--notes-dir",
        default="~/.nanobot/workspace/notes",
        help="Directory for storing notes (default: ~/.nanobot/workspace/notes)",
    )
    args = parser.parse_args()

    notes_dir = Path(args.notes_dir).expanduser()
    store = NoteStore(notes_dir)
    mcp = build_mcp_server(store)
    mcp.run()


if __name__ == "__main__":
    main()
