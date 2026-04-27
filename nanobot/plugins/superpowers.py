"""Superpowers plugin for nanobot.

Adapts the superpowers.js opencode plugin for nanobot's Python plugin system.

What it does:
  1. config hook   — registers the superpowers skills directory as an extra skill dir.
  2. chat_messages_transform hook — injects the using-superpowers bootstrap block
     into the first user message of each conversation (once per session, idempotent).

Configuration:
  Set NANOBOT_SUPERPOWERS_DIR to the superpowers repo/cache root, e.g.
      export NANOBOT_SUPERPOWERS_DIR=/Users/me/PycharmProjects/superpowers
  or in ~/.nanobot/config.json:
      {"plugins": {"modules": ["nanobot.plugins.superpowers"]}}

  Auto-discovery order:
    1. $NANOBOT_SUPERPOWERS_DIR
    2. $HOME/.claude/plugins/cache/claude-plugins-official/superpowers/<latest>/
    3. $HOME/PycharmProjects/superpowers/
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from nanobot.plugin.base import Plugin, PluginHooks, PluginInput

log = logging.getLogger(__name__)

_MARKER = "EXTREMELY_IMPORTANT"

_TOOL_MAPPING = """**Tool Mapping for nanobot:**
When skills reference Claude Code tools you don't have, substitute nanobot equivalents:
- `TodoWrite` / Task tracking → use nanobot's internal task system or memory
- `Skill` tool → use `read_file` on the SKILL.md path listed in the skills summary
- `Read`, `Write`, `Edit`, `Bash` → your native `read_file`, `write_file`, `exec_shell` tools
"""


class SuperpowersPlugin(Plugin):
    """Registers superpowers skills and injects bootstrap context into conversations."""

    async def initialize(self, plugin_input: PluginInput) -> PluginHooks:
        skills_dir = _find_skills_dir()
        if skills_dir is None:
            log.warning(
                "superpowers plugin: skills directory not found. "
                "Set NANOBOT_SUPERPOWERS_DIR to the superpowers root."
            )
        else:
            log.info("superpowers plugin: skills dir = %s", skills_dir)

        async def config_hook(cfg) -> None:
            if skills_dir is None:
                return
            if not hasattr(cfg, "_extra_skill_dirs"):
                cfg._extra_skill_dirs = []
            if str(skills_dir) not in cfg._extra_skill_dirs:
                cfg._extra_skill_dirs.append(str(skills_dir))

        async def messages_transform(_input: dict, output: dict) -> None:
            bootstrap = _get_bootstrap(skills_dir)
            if not bootstrap:
                return
            msgs: list[dict] = output.get("messages", [])
            if not msgs:
                return
            first_user = next((m for m in msgs if m.get("role") == "user"), None)
            if first_user is None:
                return
            content = first_user.get("content", "")
            if isinstance(content, str):
                if _MARKER not in content:
                    first_user["content"] = bootstrap + "\n\n" + content
            elif isinstance(content, list):
                already = any(
                    _MARKER in p.get("text", "")
                    for p in content
                    if isinstance(p, dict)
                )
                if not already:
                    content.insert(0, {"type": "text", "text": bootstrap})

        return PluginHooks(
            config=config_hook,
            chat_messages_transform=messages_transform,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_skills_dir() -> Path | None:
    """Locate the superpowers skills directory using auto-discovery."""
    candidates: list[Path] = []

    # 1. Explicit env var
    env_dir = os.environ.get("NANOBOT_SUPERPOWERS_DIR")
    if env_dir:
        candidates.append(Path(env_dir).expanduser())

    # 2. Claude Code plugin cache: ~/.claude/plugins/cache/claude-plugins-official/superpowers/<version>/
    cache_root = Path.home() / ".claude" / "plugins" / "cache" / "claude-plugins-official" / "superpowers"
    if cache_root.exists():
        versions = sorted(
            (d for d in cache_root.iterdir() if d.is_dir()),
            key=lambda d: _version_key(d.name),
            reverse=True,
        )
        candidates.extend(versions)

    # 3. Common dev location
    candidates.append(Path.home() / "PycharmProjects" / "superpowers")

    for root in candidates:
        skills = root / "skills"
        if skills.exists() and skills.is_dir():
            return skills

    return None


def _version_key(v: str) -> tuple[int, ...]:
    """Convert a semver string like '5.0.7' to a sortable tuple."""
    parts = re.split(r"[.\-]", v)
    result = []
    for p in parts:
        try:
            result.append(int(p))
        except ValueError:
            result.append(0)
    return tuple(result)


def _strip_frontmatter(content: str) -> str:
    """Remove YAML frontmatter block from a SKILL.md file."""
    match = re.match(r"^---\n.*?\n---\n", content, re.DOTALL)
    if match:
        return content[match.end():]
    return content


def _get_bootstrap(skills_dir: Path | None) -> str | None:
    """Build the bootstrap block to inject into the first user message."""
    if skills_dir is None:
        return None
    skill_path = skills_dir / "using-superpowers" / "SKILL.md"
    if not skill_path.exists():
        log.warning("superpowers plugin: using-superpowers/SKILL.md not found at %s", skill_path)
        return None

    full_content = skill_path.read_text(encoding="utf-8")
    body = _strip_frontmatter(full_content).strip()

    return (
        f"<{_MARKER}>\n"
        "You have superpowers.\n\n"
        "**IMPORTANT: The using-superpowers skill content is included below. "
        "It is ALREADY LOADED — you are currently following it. "
        "Do NOT use the skill tool to load 'using-superpowers' again — that would be redundant.**\n\n"
        f"{body}\n\n"
        f"{_TOOL_MAPPING}\n"
        f"</{_MARKER}>"
    )
