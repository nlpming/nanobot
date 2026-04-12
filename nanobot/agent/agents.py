"""Agent loader for custom subagent definitions."""

import re
from pathlib import Path


class AgentLoader:
    """
    Loader for custom agent definitions.

    Agents are markdown files (<name>.md) with YAML frontmatter that define
    specialized subagents. Stored in:
      - {workspace}/agents/   (workspace-level, highest priority)
      - ~/.nanobot/agents/    (global/user-level)
    """

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.workspace_agents = workspace / "agents"
        self.global_agents = Path("~/.nanobot/agents").expanduser()

    def list_agents(self) -> list[dict]:
        """List all available custom agents (workspace overrides global)."""
        agents = []
        seen: set[str] = set()

        for agents_dir, source in [
            (self.workspace_agents, "workspace"),
            (self.global_agents, "global"),
        ]:
            if agents_dir.exists():
                for agent_file in sorted(agents_dir.glob("*.md")):
                    name = agent_file.stem
                    if name not in seen:
                        seen.add(name)
                        agents.append({
                            "name": name,
                            "path": str(agent_file),
                            "source": source,
                        })

        return agents

    def load_agent(self, name: str) -> dict | None:
        """
        Load an agent definition by name.

        Returns a dict with:
          - name: str
          - description: str
          - model: str | None   (None = inherit default)
          - tools: list[str] | None  (None = all default tools)
          - system_prompt: str  (frontmatter stripped)
        Returns None if the agent is not found.
        """
        content = self._read_agent_file(name)
        if content is None:
            return None

        metadata = self._parse_frontmatter(content)
        system_prompt = self._strip_frontmatter(content)

        tools = metadata.get("tools")
        if isinstance(tools, str):
            tools = [t.strip() for t in tools.split(",") if t.strip()]

        return {
            "name": metadata.get("name", name),
            "description": metadata.get("description", ""),
            "model": metadata.get("model") or None,
            "tools": tools if tools else None,
            "system_prompt": system_prompt,
        }

    def build_agents_summary(self) -> str:
        """Build an XML summary of all available custom agents."""
        agents = self.list_agents()
        if not agents:
            return ""

        def _esc(s: str) -> str:
            return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        lines = ["<agents>"]
        for a in agents:
            meta = self._parse_frontmatter_from_path(a["path"])
            lines.append("  <agent>")
            lines.append(f"    <name>{_esc(a['name'])}</name>")
            desc = _esc(meta.get("description", ""))
            if desc:
                lines.append(f"    <description>{desc}</description>")
            if meta.get("model"):
                lines.append(f"    <model>{_esc(str(meta['model']))}</model>")
            lines.append("  </agent>")
        lines.append("</agents>")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _read_agent_file(self, name: str) -> str | None:
        """Read agent file content, workspace first then global."""
        for agents_dir in (self.workspace_agents, self.global_agents):
            f = agents_dir / f"{name}.md"
            if f.exists():
                return f.read_text(encoding="utf-8")
        return None

    def _parse_frontmatter_from_path(self, path: str) -> dict:
        try:
            return self._parse_frontmatter(Path(path).read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _parse_frontmatter(self, content: str) -> dict:
        """
        Parse YAML frontmatter. Supports scalars (str/bool) and inline lists
        (`- item` syntax). Does not require PyYAML.
        """
        if not content.startswith("---"):
            return {}
        match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
        if not match:
            return {}

        result: dict = {}
        lines = match.group(1).split("\n")
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                i += 1
                continue

            if ":" in stripped:
                raw_key, _, raw_val = stripped.partition(":")
                key = raw_key.strip()
                val = raw_val.strip().strip("\"'")

                if not val:
                    # Possibly a block list
                    items: list[str] = []
                    i += 1
                    while i < len(lines) and re.match(r"^\s+-\s", lines[i]):
                        item = re.sub(r"^\s+-\s+", "", lines[i]).strip().strip("\"'")
                        items.append(item)
                        i += 1
                    if items:
                        result[key] = items
                    continue
                else:
                    if val.lower() == "true":
                        result[key] = True
                    elif val.lower() == "false":
                        result[key] = False
                    else:
                        result[key] = val
            i += 1

        return result

    def _strip_frontmatter(self, content: str) -> str:
        """Remove YAML frontmatter block from content."""
        if content.startswith("---"):
            match = re.match(r"^---\n.*?\n---\n?", content, re.DOTALL)
            if match:
                return content[match.end():].strip()
        return content
