"""Unit tests for the nanobot plugin/hook/event system and superpowers plugin."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.plugin.base import Plugin, PluginHooks, PluginInput
from nanobot.plugin.manager import PluginManager, _find_plugin_class
from nanobot.bus.pubsub import EventBus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_event_bus():
    """Ensure EventBus singleton is fresh for each test."""
    EventBus.reset()
    yield
    EventBus.reset()


def _make_plugin_input(tmp_path: Path) -> PluginInput:
    cfg = MagicMock()
    cfg.plugins.extra_skill_dirs = []
    return PluginInput(workspace=tmp_path, config=cfg)


# ===========================================================================
# PluginHooks dataclass
# ===========================================================================

class TestPluginHooks:
    def test_all_hooks_default_none(self):
        hooks = PluginHooks()
        assert hooks.config is None
        assert hooks.event is None
        assert hooks.chat_messages_transform is None
        assert hooks.tool_execute_before is None
        assert hooks.tool_execute_after is None
        assert hooks.shell_env is None

    def test_hooks_accept_callables(self):
        async def noop(*a, **kw): pass
        hooks = PluginHooks(config=noop, tool_execute_before=noop)
        assert hooks.config is noop
        assert hooks.tool_execute_before is noop


# ===========================================================================
# Plugin base class
# ===========================================================================

class TestPluginBase:
    @pytest.mark.asyncio
    async def test_base_plugin_raises(self, tmp_path):
        with pytest.raises(NotImplementedError):
            await Plugin().initialize(_make_plugin_input(tmp_path))

    @pytest.mark.asyncio
    async def test_subclass_returns_hooks(self, tmp_path):
        class MyPlugin(Plugin):
            async def initialize(self, inp: PluginInput) -> PluginHooks:
                return PluginHooks()

        hooks = await MyPlugin().initialize(_make_plugin_input(tmp_path))
        assert isinstance(hooks, PluginHooks)


# ===========================================================================
# _find_plugin_class helper
# ===========================================================================

class TestFindPluginClass:
    def test_finds_subclass(self):
        import types
        mod = types.ModuleType("fake_mod")
        mod.__name__ = "fake_mod"

        class FakePlugin(Plugin):
            async def initialize(self, inp): return PluginHooks()

        FakePlugin.__module__ = "fake_mod"
        mod.FakePlugin = FakePlugin

        found = _find_plugin_class(mod)
        assert found is FakePlugin

    def test_returns_none_for_base_class_only(self):
        import types
        mod = types.ModuleType("empty_mod")
        mod.__name__ = "empty_mod"
        mod.Plugin = Plugin
        assert _find_plugin_class(mod) is None


# ===========================================================================
# PluginManager — load
# ===========================================================================

class TestPluginManagerLoad:
    @pytest.mark.asyncio
    async def test_load_valid_module(self, tmp_path):
        """Loading nanobot.plugins.superpowers should succeed without error."""
        pm = PluginManager()
        inp = _make_plugin_input(tmp_path)
        await pm.load(["nanobot.plugins.superpowers"], inp)
        assert len(pm._hooks) == 1

    @pytest.mark.asyncio
    async def test_load_nonexistent_module_logs_and_continues(self, tmp_path, caplog):
        import logging
        pm = PluginManager()
        inp = _make_plugin_input(tmp_path)
        with caplog.at_level(logging.ERROR, logger="nanobot.plugin.manager"):
            await pm.load(["nanobot.does.not.exist"], inp)
        assert len(pm._hooks) == 0
        assert any("import" in r.message.lower() or "failed" in r.message.lower()
                   for r in caplog.records)

    @pytest.mark.asyncio
    async def test_load_empty_list_is_noop(self, tmp_path):
        pm = PluginManager()
        await pm.load([], _make_plugin_input(tmp_path))
        assert pm._hooks == []


# ===========================================================================
# PluginManager — trigger_config
# ===========================================================================

class TestPluginManagerTriggerConfig:
    @pytest.mark.asyncio
    async def test_config_hook_called(self, tmp_path):
        called_with = []

        class MyPlugin(Plugin):
            async def initialize(self, inp):
                async def cfg_hook(c):
                    called_with.append(c)
                return PluginHooks(config=cfg_hook)

        pm = PluginManager()
        pm._hooks.append(await MyPlugin().initialize(_make_plugin_input(tmp_path)))
        fake_cfg = MagicMock()
        fake_cfg.plugins.extra_skill_dirs = []
        await pm.trigger_config(fake_cfg)
        assert called_with == [fake_cfg]

    @pytest.mark.asyncio
    async def test_extra_skill_dirs_collected_from_config_hook(self, tmp_path):
        skills = tmp_path / "skills"
        skills.mkdir()

        class MyPlugin(Plugin):
            async def initialize(self, inp):
                async def cfg_hook(c):
                    c._extra_skill_dirs = [str(skills)]
                return PluginHooks(config=cfg_hook)

        pm = PluginManager()
        pm._hooks.append(await MyPlugin().initialize(_make_plugin_input(tmp_path)))
        fake_cfg = MagicMock()
        fake_cfg.plugins.extra_skill_dirs = []
        await pm.trigger_config(fake_cfg)
        assert skills.resolve() in pm.extra_skill_dirs

    @pytest.mark.asyncio
    async def test_extra_skill_dirs_from_config_file(self, tmp_path):
        skills = tmp_path / "custom_skills"
        skills.mkdir()
        pm = PluginManager()
        fake_cfg = MagicMock()
        fake_cfg.plugins.extra_skill_dirs = [str(skills)]
        # no hooks registered — dirs come from config field
        await pm.trigger_config(fake_cfg)
        assert skills.resolve() in pm.extra_skill_dirs

    @pytest.mark.asyncio
    async def test_no_duplicate_dirs(self, tmp_path):
        skills = tmp_path / "skills"
        skills.mkdir()

        class MyPlugin(Plugin):
            async def initialize(self, inp):
                async def cfg_hook(c):
                    c._extra_skill_dirs = [str(skills), str(skills)]
                return PluginHooks(config=cfg_hook)

        pm = PluginManager()
        pm._hooks.append(await MyPlugin().initialize(_make_plugin_input(tmp_path)))
        fake_cfg = MagicMock()
        fake_cfg.plugins.extra_skill_dirs = [str(skills)]
        await pm.trigger_config(fake_cfg)
        assert pm.extra_skill_dirs.count(skills.resolve()) == 1


# ===========================================================================
# PluginManager — trigger_messages_transform
# ===========================================================================

class TestPluginManagerMessagesTransform:
    @pytest.mark.asyncio
    async def test_transform_can_modify_messages(self, tmp_path):
        class MyPlugin(Plugin):
            async def initialize(self, inp):
                async def transform(_inp, output):
                    output["messages"].append({"role": "assistant", "content": "injected"})
                return PluginHooks(chat_messages_transform=transform)

        pm = PluginManager()
        pm._hooks.append(await MyPlugin().initialize(_make_plugin_input(tmp_path)))
        msgs = [{"role": "user", "content": "hi"}]
        result = await pm.trigger_messages_transform(msgs)
        assert result[-1] == {"role": "assistant", "content": "injected"}

    @pytest.mark.asyncio
    async def test_transform_with_no_hooks_returns_original(self, tmp_path):
        pm = PluginManager()
        msgs = [{"role": "user", "content": "hi"}]
        result = await pm.trigger_messages_transform(msgs)
        assert result == msgs

    @pytest.mark.asyncio
    async def test_transform_error_does_not_crash(self, tmp_path, caplog):
        import logging

        class BadPlugin(Plugin):
            async def initialize(self, inp):
                async def transform(_inp, output):
                    raise RuntimeError("boom")
                return PluginHooks(chat_messages_transform=transform)

        pm = PluginManager()
        pm._hooks.append(await BadPlugin().initialize(_make_plugin_input(tmp_path)))
        with caplog.at_level(logging.ERROR, logger="nanobot.plugin.manager"):
            result = await pm.trigger_messages_transform([{"role": "user", "content": "x"}])
        assert result  # original messages returned unchanged


# ===========================================================================
# PluginManager — trigger_tool_before / after
# ===========================================================================

class TestPluginManagerToolHooks:
    @pytest.mark.asyncio
    async def test_tool_before_can_modify_args(self, tmp_path):
        class MyPlugin(Plugin):
            async def initialize(self, inp):
                async def before(inp, output):
                    output["args"]["extra"] = True
                return PluginHooks(tool_execute_before=before)

        pm = PluginManager()
        pm._hooks.append(await MyPlugin().initialize(_make_plugin_input(tmp_path)))
        args = await pm.trigger_tool_before("shell", "sess1", "call1", {"cmd": "ls"})
        assert args == {"cmd": "ls", "extra": True}

    @pytest.mark.asyncio
    async def test_tool_after_can_modify_result(self, tmp_path):
        class MyPlugin(Plugin):
            async def initialize(self, inp):
                async def after(inp, output):
                    output["result"] = output["result"].upper()
                return PluginHooks(tool_execute_after=after)

        pm = PluginManager()
        pm._hooks.append(await MyPlugin().initialize(_make_plugin_input(tmp_path)))
        result = await pm.trigger_tool_after("shell", "sess1", "call1", {}, "hello")
        assert result == "HELLO"

    @pytest.mark.asyncio
    async def test_tool_hooks_receive_correct_input(self, tmp_path):
        received = {}

        class MyPlugin(Plugin):
            async def initialize(self, inp):
                async def before(inp_dict, output):
                    received.update(inp_dict)
                return PluginHooks(tool_execute_before=before)

        pm = PluginManager()
        pm._hooks.append(await MyPlugin().initialize(_make_plugin_input(tmp_path)))
        await pm.trigger_tool_before("mytool", "my_session", "my_call", {"x": 1})
        assert received == {"tool": "mytool", "session_id": "my_session", "call_id": "my_call"}

    @pytest.mark.asyncio
    async def test_no_tool_hooks_returns_original(self, tmp_path):
        pm = PluginManager()
        args = await pm.trigger_tool_before("tool", "s", "c", {"a": 1})
        assert args == {"a": 1}
        result = await pm.trigger_tool_after("tool", "s", "c", {}, "raw")
        assert result == "raw"


# ===========================================================================
# PluginManager — trigger_shell_env
# ===========================================================================

class TestPluginManagerShellEnv:
    @pytest.mark.asyncio
    async def test_shell_env_merges_vars(self, tmp_path):
        class MyPlugin(Plugin):
            async def initialize(self, inp):
                async def shell_env(inp, output):
                    output["env"]["MY_VAR"] = "hello"
                return PluginHooks(shell_env=shell_env)

        pm = PluginManager()
        pm._hooks.append(await MyPlugin().initialize(_make_plugin_input(tmp_path)))
        env = await pm.trigger_shell_env("/tmp")
        assert env["MY_VAR"] == "hello"

    @pytest.mark.asyncio
    async def test_shell_env_empty_without_hooks(self):
        pm = PluginManager()
        env = await pm.trigger_shell_env("/tmp")
        assert env == {}


# ===========================================================================
# EventBus
# ===========================================================================

class TestEventBus:
    @pytest.mark.asyncio
    async def test_publish_notifies_subscriber(self):
        bus = EventBus.instance()
        received = []

        async def handler(event_type, payload):
            received.append((event_type, payload))

        bus.subscribe("tool.executed", handler)
        await bus.publish_sync("tool.executed", {"name": "shell"})
        assert received == [("tool.executed", {"name": "shell"})]

    @pytest.mark.asyncio
    async def test_wildcard_receives_all_events(self):
        bus = EventBus.instance()
        received = []

        async def handler(event_type, payload):
            received.append(event_type)

        bus.subscribe_all(handler)
        await bus.publish_sync("session.message", {})
        await bus.publish_sync("tool.executed", {})
        assert received == ["session.message", "tool.executed"]

    @pytest.mark.asyncio
    async def test_unsubscribe_stops_delivery(self):
        bus = EventBus.instance()
        received = []

        async def handler(event_type, payload):
            received.append(event_type)

        unsub = bus.subscribe("foo.event", handler)
        await bus.publish_sync("foo.event", {})
        unsub()
        await bus.publish_sync("foo.event", {})
        assert received == ["foo.event"]  # only one delivery

    @pytest.mark.asyncio
    async def test_error_in_handler_does_not_crash(self):
        bus = EventBus.instance()

        async def bad_handler(event_type, payload):
            raise RuntimeError("oops")

        bus.subscribe("crash.event", bad_handler)
        # Should not raise
        await bus.publish_sync("crash.event", {})

    def test_singleton(self):
        a = EventBus.instance()
        b = EventBus.instance()
        assert a is b

    @pytest.mark.asyncio
    async def test_reset_clears_instance(self):
        a = EventBus.instance()
        EventBus.reset()
        b = EventBus.instance()
        assert a is not b


# ===========================================================================
# SkillsLoader extra_dirs
# ===========================================================================

class TestSkillsLoaderExtraDirs:
    def test_extra_dir_skills_appear_in_list(self, tmp_path):
        from nanobot.agent.skills import SkillsLoader

        # Create a fake extra skills dir with one skill
        extra = tmp_path / "extra_skills"
        (extra / "my-skill").mkdir(parents=True)
        (extra / "my-skill" / "SKILL.md").write_text("# My Skill\n")

        loader = SkillsLoader(tmp_path, builtin_skills_dir=None, extra_dirs=[extra])
        names = [s["name"] for s in loader.list_skills(filter_unavailable=False)]
        assert "my-skill" in names

    def test_extra_dir_skill_source_is_plugin(self, tmp_path):
        from nanobot.agent.skills import SkillsLoader

        extra = tmp_path / "extra_skills"
        (extra / "my-skill").mkdir(parents=True)
        (extra / "my-skill" / "SKILL.md").write_text("# My Skill\n")

        loader = SkillsLoader(tmp_path, builtin_skills_dir=None, extra_dirs=[extra])
        skills = loader.list_skills(filter_unavailable=False)
        my_skill = next(s for s in skills if s["name"] == "my-skill")
        assert my_skill["source"] == "plugin"

    def test_workspace_skill_overrides_extra_dir(self, tmp_path):
        from nanobot.agent.skills import SkillsLoader

        # Same skill name in workspace and extra dir
        ws_skills = tmp_path / "skills" / "shared-skill"
        ws_skills.mkdir(parents=True)
        (ws_skills / "SKILL.md").write_text("# Workspace version\n")

        extra = tmp_path / "extra_skills"
        (extra / "shared-skill").mkdir(parents=True)
        (extra / "shared-skill" / "SKILL.md").write_text("# Extra version\n")

        loader = SkillsLoader(tmp_path, builtin_skills_dir=None, extra_dirs=[extra])
        skills = loader.list_skills(filter_unavailable=False)
        matched = [s for s in skills if s["name"] == "shared-skill"]
        assert len(matched) == 1
        assert matched[0]["source"] == "workspace"

    def test_load_skill_from_extra_dir(self, tmp_path):
        from nanobot.agent.skills import SkillsLoader

        extra = tmp_path / "extra_skills"
        (extra / "my-skill").mkdir(parents=True)
        (extra / "my-skill" / "SKILL.md").write_text("# Content")

        loader = SkillsLoader(tmp_path, builtin_skills_dir=None, extra_dirs=[extra])
        content = loader.load_skill("my-skill")
        assert content == "# Content"

    def test_no_extra_dirs_defaults_empty(self, tmp_path):
        from nanobot.agent.skills import SkillsLoader
        loader = SkillsLoader(tmp_path)
        assert loader.extra_dirs == []


# ===========================================================================
# Config schema — PluginsConfig
# ===========================================================================

class TestPluginsConfig:
    def test_default_plugins_config(self):
        from nanobot.config.schema import Config
        cfg = Config()
        assert cfg.plugins.modules == []
        assert cfg.plugins.extra_skill_dirs == []

    def test_plugins_config_parses_modules(self):
        from nanobot.config.schema import PluginsConfig
        pc = PluginsConfig(modules=["nanobot.plugins.superpowers"])
        assert pc.modules == ["nanobot.plugins.superpowers"]

    def test_plugins_config_camel_case(self):
        from nanobot.config.schema import PluginsConfig
        pc = PluginsConfig.model_validate({"extraSkillDirs": ["/tmp/skills"]})
        assert pc.extra_skill_dirs == ["/tmp/skills"]


# ===========================================================================
# Superpowers plugin
# ===========================================================================

class TestSuperpowersPlugin:
    def _make_skills_dir(self, tmp_path: Path) -> Path:
        """Create a minimal fake superpowers skills dir."""
        skills = tmp_path / "skills"
        using = skills / "using-superpowers"
        using.mkdir(parents=True)
        (using / "SKILL.md").write_text(
            "---\nname: using-superpowers\n---\nYou have superpowers.\n"
        )
        return skills

    @pytest.mark.asyncio
    async def test_config_hook_registers_skills_dir(self, tmp_path):
        from nanobot.plugins.superpowers import SuperpowersPlugin, _find_skills_dir

        skills = self._make_skills_dir(tmp_path)
        plugin = SuperpowersPlugin()

        # Patch _find_skills_dir to return our tmp dir
        import nanobot.plugins.superpowers as sp_mod
        original = sp_mod._find_skills_dir
        sp_mod._find_skills_dir = lambda: skills
        try:
            inp = _make_plugin_input(tmp_path)
            hooks = await plugin.initialize(inp)

            cfg = MagicMock()
            cfg.plugins.extra_skill_dirs = []
            del cfg._extra_skill_dirs  # ensure attribute absent
            type(cfg).__dict__  # trigger MagicMock attribute creation

            # Call config hook
            fake_cfg = type("FakeCfg", (), {"plugins": MagicMock(extra_skill_dirs=[])})()
            await hooks.config(fake_cfg)
            assert str(skills) in fake_cfg._extra_skill_dirs
        finally:
            sp_mod._find_skills_dir = original

    @pytest.mark.asyncio
    async def test_messages_transform_injects_bootstrap(self, tmp_path):
        import nanobot.plugins.superpowers as sp_mod
        from nanobot.plugins.superpowers import SuperpowersPlugin

        skills = self._make_skills_dir(tmp_path)
        plugin = SuperpowersPlugin()

        original = sp_mod._find_skills_dir
        sp_mod._find_skills_dir = lambda: skills
        try:
            inp = _make_plugin_input(tmp_path)
            hooks = await plugin.initialize(inp)

            messages = [
                {"role": "system", "content": "You are helpful"},
                {"role": "user", "content": "Hello"},
            ]
            output = {"messages": messages}
            await hooks.chat_messages_transform({}, output)

            first_user = next(m for m in output["messages"] if m["role"] == "user")
            assert "EXTREMELY_IMPORTANT" in first_user["content"]
            assert "You have superpowers" in first_user["content"]
        finally:
            sp_mod._find_skills_dir = original

    @pytest.mark.asyncio
    async def test_messages_transform_is_idempotent(self, tmp_path):
        import nanobot.plugins.superpowers as sp_mod
        from nanobot.plugins.superpowers import SuperpowersPlugin

        skills = self._make_skills_dir(tmp_path)
        plugin = SuperpowersPlugin()

        original = sp_mod._find_skills_dir
        sp_mod._find_skills_dir = lambda: skills
        try:
            inp = _make_plugin_input(tmp_path)
            hooks = await plugin.initialize(inp)

            messages = [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "hi"},
            ]
            output = {"messages": messages}
            await hooks.chat_messages_transform({}, output)
            await hooks.chat_messages_transform({}, output)  # second call

            first_user = next(m for m in output["messages"] if m["role"] == "user")
            # Bootstrap has <EXTREMELY_IMPORTANT> + </EXTREMELY_IMPORTANT> = 2 occurrences per injection
            count = first_user["content"].count("EXTREMELY_IMPORTANT")
            assert count == 2, f"Expected 2 (open+close tags from one injection), got {count}"
        finally:
            sp_mod._find_skills_dir = original

    @pytest.mark.asyncio
    async def test_messages_transform_handles_list_content(self, tmp_path):
        import nanobot.plugins.superpowers as sp_mod
        from nanobot.plugins.superpowers import SuperpowersPlugin

        skills = self._make_skills_dir(tmp_path)
        plugin = SuperpowersPlugin()

        original = sp_mod._find_skills_dir
        sp_mod._find_skills_dir = lambda: skills
        try:
            inp = _make_plugin_input(tmp_path)
            hooks = await plugin.initialize(inp)

            messages = [
                {"role": "user", "content": [{"type": "text", "text": "Hello"}]},
            ]
            output = {"messages": messages}
            await hooks.chat_messages_transform({}, output)

            content = output["messages"][0]["content"]
            assert isinstance(content, list)
            assert any("EXTREMELY_IMPORTANT" in p.get("text", "") for p in content)
        finally:
            sp_mod._find_skills_dir = original

    @pytest.mark.asyncio
    async def test_messages_transform_list_content_idempotent(self, tmp_path):
        import nanobot.plugins.superpowers as sp_mod
        from nanobot.plugins.superpowers import SuperpowersPlugin

        skills = self._make_skills_dir(tmp_path)
        plugin = SuperpowersPlugin()

        original = sp_mod._find_skills_dir
        sp_mod._find_skills_dir = lambda: skills
        try:
            inp = _make_plugin_input(tmp_path)
            hooks = await plugin.initialize(inp)

            messages = [{"role": "user", "content": [{"type": "text", "text": "Hi"}]}]
            output = {"messages": messages}
            await hooks.chat_messages_transform({}, output)
            await hooks.chat_messages_transform({}, output)

            markers = sum(
                1 for p in output["messages"][0]["content"]
                if "EXTREMELY_IMPORTANT" in p.get("text", "")
            )
            assert markers == 1
        finally:
            sp_mod._find_skills_dir = original

    def test_find_skills_dir_returns_none_when_not_found(self, tmp_path, monkeypatch):
        from nanobot.plugins.superpowers import _find_skills_dir
        monkeypatch.setenv("NANOBOT_SUPERPOWERS_DIR", str(tmp_path / "nonexistent"))
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        result = _find_skills_dir()
        assert result is None

    def test_find_skills_dir_uses_env_var(self, tmp_path, monkeypatch):
        from nanobot.plugins.superpowers import _find_skills_dir

        skills = tmp_path / "skills"
        skills.mkdir()
        monkeypatch.setenv("NANOBOT_SUPERPOWERS_DIR", str(tmp_path))
        result = _find_skills_dir()
        assert result == skills

    def test_get_bootstrap_returns_none_without_skill_file(self, tmp_path):
        from nanobot.plugins.superpowers import _get_bootstrap
        result = _get_bootstrap(tmp_path / "nonexistent")
        assert result is None

    def test_get_bootstrap_strips_frontmatter(self, tmp_path):
        from nanobot.plugins.superpowers import _get_bootstrap

        skills = tmp_path / "skills"
        using = skills / "using-superpowers"
        using.mkdir(parents=True)
        (using / "SKILL.md").write_text("---\nname: test\n---\nActual content here.\n")

        result = _get_bootstrap(skills)
        assert result is not None
        assert "name: test" not in result
        assert "Actual content here" in result
        assert "EXTREMELY_IMPORTANT" in result

    @pytest.mark.asyncio
    async def test_no_injection_when_skills_dir_missing(self, tmp_path, monkeypatch):
        import nanobot.plugins.superpowers as sp_mod
        from nanobot.plugins.superpowers import SuperpowersPlugin

        original = sp_mod._find_skills_dir
        sp_mod._find_skills_dir = lambda: None
        try:
            plugin = SuperpowersPlugin()
            inp = _make_plugin_input(tmp_path)
            hooks = await plugin.initialize(inp)

            messages = [{"role": "user", "content": "Hello"}]
            output = {"messages": messages}
            await hooks.chat_messages_transform({}, output)
            assert output["messages"][0]["content"] == "Hello"
        finally:
            sp_mod._find_skills_dir = original


# ===========================================================================
# Runner integration — plugin_manager tool hooks wired up
# ===========================================================================

class TestRunnerPluginIntegration:
    @pytest.mark.asyncio
    async def test_runner_calls_tool_before_hook(self, tmp_path):
        from nanobot.agent.runner import AgentRunSpec, AgentRunner
        from nanobot.providers.base import LLMResponse, ToolCallRequest

        before_calls = []

        class MyPlugin(Plugin):
            async def initialize(self, inp):
                async def before(inp_dict, output):
                    before_calls.append(inp_dict["tool"])
                return PluginHooks(tool_execute_before=before)

        pm = PluginManager()
        pm._hooks.append(await MyPlugin().initialize(_make_plugin_input(tmp_path)))

        provider = MagicMock()
        call_n = {"n": 0}

        async def chat_with_retry(**kwargs):
            call_n["n"] += 1
            if call_n["n"] == 1:
                return LLMResponse(
                    content="",
                    tool_calls=[ToolCallRequest(id="c1", name="shell", arguments={"cmd": "ls"})],
                )
            return LLMResponse(content="done", tool_calls=[])

        provider.chat_with_retry = chat_with_retry
        tools = MagicMock()
        tools.get_definitions.return_value = []
        tools.execute = AsyncMock(return_value="ok")

        runner = AgentRunner(provider)
        await runner.run(AgentRunSpec(
            initial_messages=[{"role": "user", "content": "go"}],
            tools=tools,
            model="test",
            max_iterations=3,
            plugin_manager=pm,
        ))

        assert "shell" in before_calls

    @pytest.mark.asyncio
    async def test_runner_calls_tool_after_hook(self, tmp_path):
        from nanobot.agent.runner import AgentRunSpec, AgentRunner
        from nanobot.providers.base import LLMResponse, ToolCallRequest

        after_results = []

        class MyPlugin(Plugin):
            async def initialize(self, inp):
                async def after(inp_dict, output):
                    after_results.append(output["result"])
                return PluginHooks(tool_execute_after=after)

        pm = PluginManager()
        pm._hooks.append(await MyPlugin().initialize(_make_plugin_input(tmp_path)))

        provider = MagicMock()
        call_n = {"n": 0}

        async def chat_with_retry(**kwargs):
            call_n["n"] += 1
            if call_n["n"] == 1:
                return LLMResponse(
                    content="",
                    tool_calls=[ToolCallRequest(id="c1", name="shell", arguments={})],
                )
            return LLMResponse(content="done", tool_calls=[])

        provider.chat_with_retry = chat_with_retry
        tools = MagicMock()
        tools.get_definitions.return_value = []
        tools.execute = AsyncMock(return_value="tool output")

        runner = AgentRunner(provider)
        await runner.run(AgentRunSpec(
            initial_messages=[{"role": "user", "content": "go"}],
            tools=tools,
            model="test",
            max_iterations=3,
            plugin_manager=pm,
        ))

        assert "tool output" in after_results

    @pytest.mark.asyncio
    async def test_runner_tool_before_modified_args_used(self, tmp_path):
        """Args modified by tool_before hook must be passed to tools.execute."""
        from nanobot.agent.runner import AgentRunSpec, AgentRunner
        from nanobot.providers.base import LLMResponse, ToolCallRequest

        class MyPlugin(Plugin):
            async def initialize(self, inp):
                async def before(inp_dict, output):
                    output["args"]["injected"] = True
                return PluginHooks(tool_execute_before=before)

        pm = PluginManager()
        pm._hooks.append(await MyPlugin().initialize(_make_plugin_input(tmp_path)))

        provider = MagicMock()
        call_n = {"n": 0}
        captured_args = {}

        async def chat_with_retry(**kwargs):
            call_n["n"] += 1
            if call_n["n"] == 1:
                return LLMResponse(
                    content="",
                    tool_calls=[ToolCallRequest(id="c1", name="mytool", arguments={"x": 1})],
                )
            return LLMResponse(content="done", tool_calls=[])

        provider.chat_with_retry = chat_with_retry

        async def fake_execute(name, args):
            captured_args.update(args)
            return "result"

        tools = MagicMock()
        tools.get_definitions.return_value = []
        tools.execute = fake_execute

        runner = AgentRunner(provider)
        await runner.run(AgentRunSpec(
            initial_messages=[{"role": "user", "content": "go"}],
            tools=tools,
            model="test",
            max_iterations=3,
            plugin_manager=pm,
        ))

        assert captured_args.get("injected") is True

    @pytest.mark.asyncio
    async def test_runner_publishes_tool_executed_event(self, tmp_path):
        """tool.executed event published to EventBus after each tool call."""
        from nanobot.agent.runner import AgentRunSpec, AgentRunner
        from nanobot.providers.base import LLMResponse, ToolCallRequest

        bus = EventBus.instance()
        received = []
        bus.subscribe("tool.executed", lambda et, p: received.append(p))

        provider = MagicMock()
        call_n = {"n": 0}

        async def chat_with_retry(**kwargs):
            call_n["n"] += 1
            if call_n["n"] == 1:
                return LLMResponse(
                    content="",
                    tool_calls=[ToolCallRequest(id="c1", name="mytest", arguments={})],
                )
            return LLMResponse(content="done", tool_calls=[])

        provider.chat_with_retry = chat_with_retry
        tools = MagicMock()
        tools.get_definitions.return_value = []
        tools.execute = AsyncMock(return_value="result")

        runner = AgentRunner(provider)
        await runner.run(AgentRunSpec(
            initial_messages=[{"role": "user", "content": "go"}],
            tools=tools,
            model="test",
            max_iterations=3,
        ))

        # Allow fire-and-forget tasks to complete
        await asyncio.sleep(0)

        assert any(e.get("name") == "mytest" for e in received)
