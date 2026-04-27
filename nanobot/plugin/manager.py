"""Plugin manager: loads plugins and dispatches hook calls."""

from __future__ import annotations

import importlib
import inspect
import logging
from pathlib import Path
from typing import Any

from nanobot.plugin.base import Plugin, PluginHooks, PluginInput

log = logging.getLogger(__name__)


class PluginManager:
    """Loads plugins from dotted module paths and dispatches trigger/notification hooks."""

    def __init__(self) -> None:
        self._hooks: list[PluginHooks] = []
        # Collected from config hooks; consumed by ContextBuilder / SkillsLoader
        self.extra_skill_dirs: list[Path] = []

    async def load(self, modules: list[str], plugin_input: PluginInput) -> None:
        """Import each module, find Plugin subclasses, call initialize(), collect hooks."""
        for dotpath in modules:
            try:
                mod = importlib.import_module(dotpath)
            except ImportError as exc:
                log.error("Plugin import failed: %s — %s", dotpath, exc)
                continue

            plugin_cls = _find_plugin_class(mod)
            if plugin_cls is None:
                log.error("No Plugin subclass found in module: %s", dotpath)
                continue

            try:
                instance = plugin_cls()
                hooks = await instance.initialize(plugin_input)
                self._hooks.append(hooks)
                log.info("Loaded plugin: %s", dotpath)
            except Exception as exc:  # noqa: BLE001
                log.error("Plugin initialization failed: %s — %s", dotpath, exc)

    # ------------------------------------------------------------------
    # Notification hooks
    # ------------------------------------------------------------------

    async def trigger_config(self, cfg: Any) -> None:
        """Call every plugin's config hook, then harvest extra_skill_dirs."""
        for h in self._hooks:
            if h.config:
                try:
                    await h.config(cfg)
                except Exception as exc:  # noqa: BLE001
                    log.error("Plugin config hook error: %s", exc)

        # Collect dirs registered by plugins (stored as _extra_skill_dirs on cfg)
        raw_dirs: list[str] = getattr(cfg, "_extra_skill_dirs", [])
        for d in raw_dirs:
            p = Path(d).expanduser().resolve()
            if p not in self.extra_skill_dirs:
                self.extra_skill_dirs.append(p)

        # Also honour static extra_skill_dirs from config file
        if hasattr(cfg, "plugins"):
            for d in getattr(cfg.plugins, "extra_skill_dirs", []):
                p = Path(d).expanduser().resolve()
                if p not in self.extra_skill_dirs:
                    self.extra_skill_dirs.append(p)

    async def publish_event(self, event_type: str, payload: dict) -> None:
        """Notify all plugins of an event."""
        for h in self._hooks:
            if h.event:
                try:
                    await h.event(event_type, payload)
                except Exception as exc:  # noqa: BLE001
                    log.error("Plugin event hook error (%s): %s", event_type, exc)

    # ------------------------------------------------------------------
    # Trigger hooks  (input, output) → mutate output → return modified value
    # ------------------------------------------------------------------

    async def trigger_messages_transform(self, messages: list[dict]) -> list[dict]:
        """Call chat_messages_transform hooks; return (possibly modified) messages."""
        output: dict = {"messages": messages}
        for h in self._hooks:
            if h.chat_messages_transform:
                try:
                    await h.chat_messages_transform({}, output)
                except Exception as exc:  # noqa: BLE001
                    log.error("Plugin chat_messages_transform error: %s", exc)
        return output["messages"]

    async def trigger_tool_before(
        self, tool_name: str, session_id: str, call_id: str, args: dict
    ) -> dict:
        """Call tool_execute_before hooks; return (possibly modified) args."""
        output: dict = {"args": dict(args)}
        inp = {"tool": tool_name, "session_id": session_id, "call_id": call_id}
        for h in self._hooks:
            if h.tool_execute_before:
                try:
                    await h.tool_execute_before(inp, output)
                except Exception as exc:  # noqa: BLE001
                    log.error("Plugin tool_execute_before error (%s): %s", tool_name, exc)
        return output["args"]

    async def trigger_tool_after(
        self, tool_name: str, session_id: str, call_id: str, args: dict, result: Any
    ) -> Any:
        """Call tool_execute_after hooks; return (possibly modified) result."""
        output: dict = {"result": result}
        inp = {"tool": tool_name, "session_id": session_id, "call_id": call_id, "args": args}
        for h in self._hooks:
            if h.tool_execute_after:
                try:
                    await h.tool_execute_after(inp, output)
                except Exception as exc:  # noqa: BLE001
                    log.error("Plugin tool_execute_after error (%s): %s", tool_name, exc)
        return output["result"]

    async def trigger_shell_env(
        self, cwd: str, session_id: str | None = None
    ) -> dict[str, str]:
        """Call shell_env hooks; return merged env vars to inject."""
        output: dict = {"env": {}}
        inp = {"cwd": cwd, "session_id": session_id}
        for h in self._hooks:
            if h.shell_env:
                try:
                    await h.shell_env(inp, output)
                except Exception as exc:  # noqa: BLE001
                    log.error("Plugin shell_env error: %s", exc)
        return output["env"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_plugin_class(mod: Any) -> type[Plugin] | None:
    """Return the first Plugin subclass defined in the module, or None."""
    for _name, obj in inspect.getmembers(mod, inspect.isclass):
        if issubclass(obj, Plugin) and obj is not Plugin and obj.__module__ == mod.__name__:
            return obj
    return None
