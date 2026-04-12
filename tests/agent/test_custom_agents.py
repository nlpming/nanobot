"""Tests for custom subagent definitions and AgentLoader."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

AGENT_MD = """\
---
name: code-reviewer
description: 对代码进行安全漏洞和性能问题的专项审查
model: anthropic/claude-haiku-4-5
tools:
  - read_file
  - list_dir
---

# 代码审查专家

你是一位专业的代码审查专家。审查维度：安全性、性能、可维护性。
"""

AGENT_MD_NO_MODEL = """\
---
name: summarizer
description: 对文档进行摘要
tools:
  - read_file
  - web_fetch
---

你是一位摘要专家，擅长提取关键信息。
"""

AGENT_MD_ALL_TOOLS = """\
---
name: researcher
description: 网络调研专家
---

你是一位调研专家，可以使用所有工具。
"""


def _make_agents_dir(tmp_path: Path, contents: dict[str, str]) -> Path:
    """Create agents directory with given files."""
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    for name, content in contents.items():
        (agents_dir / name).write_text(content, encoding="utf-8")
    return agents_dir


# ---------------------------------------------------------------------------
# AgentLoader: basic loading
# ---------------------------------------------------------------------------

class TestAgentLoader:
    def test_list_agents_empty(self, tmp_path):
        from nanobot.agent.agents import AgentLoader
        loader = AgentLoader(tmp_path)
        assert loader.list_agents() == []

    def test_list_agents_finds_md_files(self, tmp_path):
        from nanobot.agent.agents import AgentLoader
        _make_agents_dir(tmp_path, {
            "code-reviewer.md": AGENT_MD,
            "summarizer.md": AGENT_MD_NO_MODEL,
        })
        loader = AgentLoader(tmp_path)
        names = [a["name"] for a in loader.list_agents()]
        assert "code-reviewer" in names
        assert "summarizer" in names

    def test_load_agent_parses_metadata(self, tmp_path):
        from nanobot.agent.agents import AgentLoader
        _make_agents_dir(tmp_path, {"code-reviewer.md": AGENT_MD})
        loader = AgentLoader(tmp_path)

        agent = loader.load_agent("code-reviewer")
        assert agent is not None
        assert agent["name"] == "code-reviewer"
        assert agent["description"] == "对代码进行安全漏洞和性能问题的专项审查"
        assert agent["model"] == "anthropic/claude-haiku-4-5"
        assert agent["tools"] == ["read_file", "list_dir"]

    def test_load_agent_strips_frontmatter_from_system_prompt(self, tmp_path):
        from nanobot.agent.agents import AgentLoader
        _make_agents_dir(tmp_path, {"code-reviewer.md": AGENT_MD})
        loader = AgentLoader(tmp_path)

        agent = loader.load_agent("code-reviewer")
        assert "---" not in agent["system_prompt"]
        assert "代码审查专家" in agent["system_prompt"]

    def test_load_agent_none_model_when_not_specified(self, tmp_path):
        from nanobot.agent.agents import AgentLoader
        _make_agents_dir(tmp_path, {"summarizer.md": AGENT_MD_NO_MODEL})
        loader = AgentLoader(tmp_path)

        agent = loader.load_agent("summarizer")
        assert agent["model"] is None

    def test_load_agent_none_tools_when_not_specified(self, tmp_path):
        from nanobot.agent.agents import AgentLoader
        _make_agents_dir(tmp_path, {"researcher.md": AGENT_MD_ALL_TOOLS})
        loader = AgentLoader(tmp_path)

        agent = loader.load_agent("researcher")
        assert agent["tools"] is None

    def test_load_agent_returns_none_for_missing(self, tmp_path):
        from nanobot.agent.agents import AgentLoader
        loader = AgentLoader(tmp_path)
        assert loader.load_agent("nonexistent") is None

    def test_workspace_agents_override_global(self, tmp_path):
        from nanobot.agent.agents import AgentLoader

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        global_dir = tmp_path / "global"
        global_dir.mkdir()

        (workspace / "agents").mkdir()
        (workspace / "agents" / "my-agent.md").write_text(
            "---\nname: my-agent\ndescription: workspace version\n---\nworkspace prompt",
            encoding="utf-8",
        )
        (global_dir / "my-agent.md").write_text(
            "---\nname: my-agent\ndescription: global version\n---\nglobal prompt",
            encoding="utf-8",
        )

        loader = AgentLoader(workspace)
        # Patch global_agents to our test global dir
        loader.global_agents = global_dir

        agent = loader.load_agent("my-agent")
        assert agent["description"] == "workspace version"
        assert agent["system_prompt"] == "workspace prompt"

    def test_global_agent_used_when_no_workspace_agent(self, tmp_path):
        from nanobot.agent.agents import AgentLoader

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        global_dir = tmp_path / "global"
        global_dir.mkdir()

        (global_dir / "global-only.md").write_text(
            "---\nname: global-only\ndescription: only in global\n---\nglobal content",
            encoding="utf-8",
        )

        loader = AgentLoader(workspace)
        loader.global_agents = global_dir

        agent = loader.load_agent("global-only")
        assert agent is not None
        assert agent["description"] == "only in global"


# ---------------------------------------------------------------------------
# AgentLoader: build_agents_summary
# ---------------------------------------------------------------------------

class TestAgentsSummary:
    def test_summary_empty_when_no_agents(self, tmp_path):
        from nanobot.agent.agents import AgentLoader
        loader = AgentLoader(tmp_path)
        assert loader.build_agents_summary() == ""

    def test_summary_contains_agent_names(self, tmp_path):
        from nanobot.agent.agents import AgentLoader
        _make_agents_dir(tmp_path, {
            "code-reviewer.md": AGENT_MD,
            "summarizer.md": AGENT_MD_NO_MODEL,
        })
        loader = AgentLoader(tmp_path)
        summary = loader.build_agents_summary()

        assert "<agents>" in summary
        assert "code-reviewer" in summary
        assert "summarizer" in summary
        assert "对代码进行安全漏洞和性能问题的专项审查" in summary

    def test_summary_is_valid_xml_structure(self, tmp_path):
        from nanobot.agent.agents import AgentLoader
        _make_agents_dir(tmp_path, {"code-reviewer.md": AGENT_MD})
        loader = AgentLoader(tmp_path)
        summary = loader.build_agents_summary()

        assert summary.startswith("<agents>")
        assert summary.endswith("</agents>")
        assert "<agent>" in summary
        assert "</agent>" in summary


# ---------------------------------------------------------------------------
# SpawnTool: agent parameter
# ---------------------------------------------------------------------------

class TestSpawnToolWithAgent:
    def _make_spawn_tool(self, tmp_path: Path):
        from nanobot.agent.agents import AgentLoader
        from nanobot.agent.tools.spawn import SpawnTool

        manager = MagicMock()
        manager.agents = AgentLoader(tmp_path)
        manager.spawn = AsyncMock(return_value="Subagent started.")
        tool = SpawnTool(manager=manager)
        return tool, manager

    @pytest.mark.asyncio
    async def test_execute_passes_agent_to_manager(self, tmp_path):
        from nanobot.agent.tools.spawn import SpawnTool

        tool, manager = self._make_spawn_tool(tmp_path)
        await tool.execute(task="review main.py", agent="code-reviewer", label="review")

        manager.spawn.assert_awaited_once_with(
            task="review main.py",
            agent="code-reviewer",
            label="review",
            origin_channel="cli",
            origin_chat_id="direct",
            session_key="cli:direct",
        )

    @pytest.mark.asyncio
    async def test_execute_without_agent_passes_none(self, tmp_path):
        tool, manager = self._make_spawn_tool(tmp_path)
        await tool.execute(task="do something")

        manager.spawn.assert_awaited_once_with(
            task="do something",
            agent=None,
            label=None,
            origin_channel="cli",
            origin_chat_id="direct",
            session_key="cli:direct",
        )

    def test_description_includes_agents_summary(self, tmp_path):
        _make_agents_dir(tmp_path, {"code-reviewer.md": AGENT_MD})
        tool, _ = self._make_spawn_tool(tmp_path)
        assert "code-reviewer" in tool.description
        assert "Available custom agents" in tool.description

    def test_description_no_extra_section_when_no_agents(self, tmp_path):
        tool, _ = self._make_spawn_tool(tmp_path)
        assert "Available custom agents" not in tool.description

    def test_parameters_include_agent_field(self, tmp_path):
        tool, _ = self._make_spawn_tool(tmp_path)
        params = tool.parameters
        assert "agent" in params["properties"]
        assert params["properties"]["agent"]["type"] == "string"
        # agent is optional — not in required list
        assert "agent" not in params.get("required", [])


# ---------------------------------------------------------------------------
# SubagentManager: spawn with custom agent
# ---------------------------------------------------------------------------

class TestSubagentManagerCustomAgent:
    def _make_manager(self, tmp_path: Path):
        from nanobot.agent.subagent import SubagentManager
        from nanobot.bus.queue import MessageBus

        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "default-model"
        mgr = SubagentManager(provider=provider, workspace=tmp_path, bus=bus)
        return mgr, bus

    @pytest.mark.asyncio
    async def test_spawn_returns_error_for_unknown_agent(self, tmp_path):
        mgr, _ = self._make_manager(tmp_path)
        result = await mgr.spawn(task="do something", agent="nonexistent-agent")
        assert "not found" in result
        assert "nonexistent-agent" in result
        # No background task should have been created
        assert mgr.get_running_count() == 0

    @pytest.mark.asyncio
    async def test_spawn_with_custom_agent_uses_agent_model(self, tmp_path, monkeypatch):
        from nanobot.providers.base import LLMResponse

        _make_agents_dir(tmp_path, {"code-reviewer.md": AGENT_MD})
        mgr, bus = self._make_manager(tmp_path)
        mgr._announce_result = AsyncMock()

        used_models: list[str] = []

        async def fake_chat(*, messages, model, **kwargs):
            used_models.append(model)
            return LLMResponse(content="审查完毕", tool_calls=[])

        mgr.provider.chat_with_retry = fake_chat

        await mgr._run_subagent(
            "t1", "review code", "review", {"channel": "test", "chat_id": "c1"},
            agent_def=mgr.agents.load_agent("code-reviewer"),
        )

        assert used_models[0] == "anthropic/claude-haiku-4-5"

    @pytest.mark.asyncio
    async def test_spawn_with_custom_agent_uses_agent_system_prompt(self, tmp_path, monkeypatch):
        from nanobot.providers.base import LLMResponse

        _make_agents_dir(tmp_path, {"code-reviewer.md": AGENT_MD})
        mgr, bus = self._make_manager(tmp_path)
        mgr._announce_result = AsyncMock()

        captured_messages: list = []

        async def fake_chat(*, messages, **kwargs):
            captured_messages.extend(messages)
            return LLMResponse(content="done", tool_calls=[])

        mgr.provider.chat_with_retry = fake_chat

        agent_def = mgr.agents.load_agent("code-reviewer")
        await mgr._run_subagent(
            "t1", "review code", "review", {"channel": "test", "chat_id": "c1"},
            agent_def=agent_def,
        )

        system_msg = next((m for m in captured_messages if m["role"] == "system"), None)
        assert system_msg is not None
        assert "代码审查专家" in system_msg["content"]
        assert "Agent: code-reviewer" in system_msg["content"]

    @pytest.mark.asyncio
    async def test_spawn_with_custom_agent_restricts_tools(self, tmp_path, monkeypatch):
        from nanobot.providers.base import LLMResponse

        _make_agents_dir(tmp_path, {"code-reviewer.md": AGENT_MD})
        mgr, bus = self._make_manager(tmp_path)
        mgr._announce_result = AsyncMock()

        async def fake_chat(*, messages, tools, **kwargs):
            return LLMResponse(content="done", tool_calls=[])

        mgr.provider.chat_with_retry = fake_chat

        captured_registries: list = []
        original_run = mgr.runner.run

        async def fake_run(spec):
            captured_registries.append(spec.tools)
            from nanobot.agent.runner import AgentRunResult
            return AgentRunResult(
                final_content="done", messages=[], tools_used=[],
                tool_events=[], usage={}, stop_reason="end_turn",
            )

        mgr.runner.run = fake_run

        agent_def = mgr.agents.load_agent("code-reviewer")
        await mgr._run_subagent(
            "t1", "review code", "review", {"channel": "test", "chat_id": "c1"},
            agent_def=agent_def,
        )

        assert len(captured_registries) == 1
        registry = captured_registries[0]
        tool_names = {t.name for t in registry._tools.values()}
        # Only allowed tools registered
        assert "read_file" in tool_names
        assert "list_dir" in tool_names
        # Tools not in the agent's list should be absent
        assert "exec" not in tool_names
        assert "web_search" not in tool_names
        assert "web_fetch" not in tool_names

    @pytest.mark.asyncio
    async def test_spawn_default_agent_uses_all_tools(self, tmp_path):
        mgr, bus = self._make_manager(tmp_path)
        mgr._announce_result = AsyncMock()

        captured_registries: list = []

        async def fake_run(spec):
            captured_registries.append(spec.tools)
            from nanobot.agent.runner import AgentRunResult
            return AgentRunResult(
                final_content="done", messages=[], tools_used=[],
                tool_events=[], usage={}, stop_reason="end_turn",
            )

        mgr.runner.run = fake_run

        await mgr._run_subagent(
            "t1", "do task", "task", {"channel": "test", "chat_id": "c1"},
            agent_def=None,
        )

        registry = captured_registries[0]
        tool_names = {t.name for t in registry._tools.values()}
        assert "read_file" in tool_names
        assert "exec" in tool_names
        assert "web_search" in tool_names
        assert "web_fetch" in tool_names

    @pytest.mark.asyncio
    async def test_spawn_default_agent_falls_back_to_default_model(self, tmp_path):
        from nanobot.providers.base import LLMResponse

        mgr, bus = self._make_manager(tmp_path)
        mgr._announce_result = AsyncMock()

        used_models: list[str] = []

        async def fake_chat(*, messages, model, **kwargs):
            used_models.append(model)
            return LLMResponse(content="done", tool_calls=[])

        mgr.provider.chat_with_retry = fake_chat

        await mgr._run_subagent(
            "t1", "do task", "task", {"channel": "test", "chat_id": "c1"},
            agent_def=None,
        )

        assert used_models[0] == "default-model"

    @pytest.mark.asyncio
    async def test_spawn_label_includes_agent_name(self, tmp_path):
        _make_agents_dir(tmp_path, {"code-reviewer.md": AGENT_MD})
        mgr, _ = self._make_manager(tmp_path)
        mgr._run_subagent = AsyncMock()

        result = await mgr.spawn(
            task="review the code", agent="code-reviewer", session_key="test:c1"
        )

        assert "code-reviewer" in result
        assert mgr.get_running_count() == 1
