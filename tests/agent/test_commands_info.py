"""Tests for /skills, /agents, /mcp slash commands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nanobot.bus.events import InboundMessage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ctx(loop, content="/skills"):
    from nanobot.command.router import CommandContext

    msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content=content)
    return CommandContext(msg=msg, session=None, key=msg.session_key, raw=content, loop=loop)


def _make_loop(tmp_path: Path):
    """Minimal loop stub with real workspace path."""
    loop = MagicMock()
    loop.workspace = tmp_path
    loop._mcp_servers = {}
    loop.tools.tool_names = []
    return loop


def _write_agent(agents_dir: Path, name: str, content: str) -> None:
    agents_dir.mkdir(parents=True, exist_ok=True)
    (agents_dir / f"{name}.md").write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# /skills
# ---------------------------------------------------------------------------

class TestCmdSkills:
    @pytest.mark.asyncio
    async def test_no_skills_message(self, tmp_path):
        from nanobot.command.builtin import cmd_skills

        loop = _make_loop(tmp_path)
        with patch("nanobot.agent.skills.SkillsLoader.list_skills", return_value=[]):
            out = await cmd_skills(_make_ctx(loop, "/skills"))

        assert "No skills found" in out.content

    @pytest.mark.asyncio
    async def test_lists_skill_names(self, tmp_path):
        from nanobot.agent.skills import SkillsLoader
        from nanobot.command.builtin import cmd_skills

        # Create a real workspace skill
        skill_dir = tmp_path / "skills" / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: A test skill\n---\nContent",
            encoding="utf-8",
        )

        loop = _make_loop(tmp_path)
        out = await cmd_skills(_make_ctx(loop, "/skills"))

        assert "my-skill" in out.content
        assert "A test skill" in out.content

    @pytest.mark.asyncio
    async def test_workspace_icon_shown(self, tmp_path):
        from nanobot.command.builtin import cmd_skills

        skill_dir = tmp_path / "skills" / "ws-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: ws-skill\ndescription: workspace skill\n---\n",
            encoding="utf-8",
        )

        loop = _make_loop(tmp_path)
        out = await cmd_skills(_make_ctx(loop, "/skills"))

        assert "📁" in out.content  # workspace icon

    @pytest.mark.asyncio
    async def test_always_skill_tagged(self, tmp_path):
        from nanobot.command.builtin import cmd_skills

        skill_dir = tmp_path / "skills" / "always-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: always-skill\ndescription: always loaded\nalways: true\n---\n",
            encoding="utf-8",
        )

        loop = _make_loop(tmp_path)
        out = await cmd_skills(_make_ctx(loop, "/skills"))

        assert "always" in out.content

    @pytest.mark.asyncio
    async def test_render_as_text_metadata(self, tmp_path):
        from nanobot.command.builtin import cmd_skills

        loop = _make_loop(tmp_path)
        with patch("nanobot.agent.skills.SkillsLoader.list_skills", return_value=[]):
            out = await cmd_skills(_make_ctx(loop, "/skills"))

        assert out.metadata.get("render_as") == "text"


# ---------------------------------------------------------------------------
# /agents
# ---------------------------------------------------------------------------

class TestCmdAgents:
    @pytest.mark.asyncio
    async def test_no_agents_shows_path_hint(self, tmp_path):
        from nanobot.command.builtin import cmd_agents

        loop = _make_loop(tmp_path)
        out = await cmd_agents(_make_ctx(loop, "/agents"))

        assert "No custom agents found" in out.content
        assert "agents" in out.content  # shows where to put them

    @pytest.mark.asyncio
    async def test_lists_agent_name_and_description(self, tmp_path):
        from nanobot.command.builtin import cmd_agents

        _write_agent(
            tmp_path / "agents",
            "code-reviewer",
            "---\nname: code-reviewer\ndescription: Reviews code\nmodel: claude-haiku\n---\nPrompt",
        )
        loop = _make_loop(tmp_path)
        out = await cmd_agents(_make_ctx(loop, "/agents"))

        assert "code-reviewer" in out.content
        assert "Reviews code" in out.content

    @pytest.mark.asyncio
    async def test_shows_model(self, tmp_path):
        from nanobot.command.builtin import cmd_agents

        _write_agent(
            tmp_path / "agents",
            "fast-agent",
            "---\nname: fast-agent\ndescription: Fast\nmodel: anthropic/claude-haiku-4-5\n---\n",
        )
        loop = _make_loop(tmp_path)
        out = await cmd_agents(_make_ctx(loop, "/agents"))

        assert "anthropic/claude-haiku-4-5" in out.content

    @pytest.mark.asyncio
    async def test_shows_tools_restriction(self, tmp_path):
        from nanobot.command.builtin import cmd_agents

        _write_agent(
            tmp_path / "agents",
            "readonly-agent",
            "---\nname: readonly-agent\ndescription: Read only\ntools:\n  - read_file\n  - list_dir\n---\n",
        )
        loop = _make_loop(tmp_path)
        out = await cmd_agents(_make_ctx(loop, "/agents"))

        assert "read_file" in out.content
        assert "list_dir" in out.content

    @pytest.mark.asyncio
    async def test_multiple_agents_all_listed(self, tmp_path):
        from nanobot.command.builtin import cmd_agents

        agents_dir = tmp_path / "agents"
        for name in ("agent-a", "agent-b", "agent-c"):
            _write_agent(agents_dir, name, f"---\nname: {name}\ndescription: desc\n---\n")

        loop = _make_loop(tmp_path)
        out = await cmd_agents(_make_ctx(loop, "/agents"))

        for name in ("agent-a", "agent-b", "agent-c"):
            assert name in out.content

    @pytest.mark.asyncio
    async def test_render_as_text_metadata(self, tmp_path):
        from nanobot.command.builtin import cmd_agents

        loop = _make_loop(tmp_path)
        out = await cmd_agents(_make_ctx(loop, "/agents"))

        assert out.metadata.get("render_as") == "text"


# ---------------------------------------------------------------------------
# /mcp
# ---------------------------------------------------------------------------

class TestCmdMcp:
    @pytest.mark.asyncio
    async def test_no_servers_configured(self, tmp_path):
        from nanobot.command.builtin import cmd_mcp

        loop = _make_loop(tmp_path)
        loop._mcp_servers = {}
        out = await cmd_mcp(_make_ctx(loop, "/mcp"))

        assert "No MCP servers configured" in out.content

    @pytest.mark.asyncio
    async def test_connected_server_shows_tools(self, tmp_path):
        from nanobot.command.builtin import cmd_mcp

        loop = _make_loop(tmp_path)
        loop._mcp_servers = {"github": MagicMock()}
        loop.tools.tool_names = ["mcp_github_search_repos", "mcp_github_create_issue"]

        out = await cmd_mcp(_make_ctx(loop, "/mcp"))

        assert "github" in out.content
        assert "search_repos" in out.content
        assert "create_issue" in out.content
        assert "✅" in out.content

    @pytest.mark.asyncio
    async def test_disconnected_server_shown(self, tmp_path):
        from nanobot.command.builtin import cmd_mcp

        loop = _make_loop(tmp_path)
        loop._mcp_servers = {"filesystem": MagicMock()}
        loop.tools.tool_names = []  # no tools registered = not connected

        out = await cmd_mcp(_make_ctx(loop, "/mcp"))

        assert "filesystem" in out.content
        assert "❌" in out.content

    @pytest.mark.asyncio
    async def test_multiple_servers(self, tmp_path):
        from nanobot.command.builtin import cmd_mcp

        loop = _make_loop(tmp_path)
        loop._mcp_servers = {"github": MagicMock(), "slack": MagicMock()}
        loop.tools.tool_names = ["mcp_github_list_prs"]  # slack not connected

        out = await cmd_mcp(_make_ctx(loop, "/mcp"))

        assert "github" in out.content
        assert "slack" in out.content
        assert "✅" in out.content
        assert "❌" in out.content

    @pytest.mark.asyncio
    async def test_tool_count_displayed(self, tmp_path):
        from nanobot.command.builtin import cmd_mcp

        loop = _make_loop(tmp_path)
        loop._mcp_servers = {"myserver": MagicMock()}
        loop.tools.tool_names = [
            "mcp_myserver_tool_a",
            "mcp_myserver_tool_b",
            "mcp_myserver_tool_c",
        ]

        out = await cmd_mcp(_make_ctx(loop, "/mcp"))

        assert "3 tools" in out.content

    @pytest.mark.asyncio
    async def test_render_as_text_metadata(self, tmp_path):
        from nanobot.command.builtin import cmd_mcp

        loop = _make_loop(tmp_path)
        out = await cmd_mcp(_make_ctx(loop, "/mcp"))

        assert out.metadata.get("render_as") == "text"


# ---------------------------------------------------------------------------
# /help updated
# ---------------------------------------------------------------------------

class TestCmdHelp:
    @pytest.mark.asyncio
    async def test_help_includes_new_commands(self, tmp_path):
        from nanobot.command.builtin import cmd_help

        loop = _make_loop(tmp_path)
        out = await cmd_help(_make_ctx(loop, "/help"))

        assert "/skills" in out.content
        assert "/agents" in out.content
        assert "/mcp" in out.content
