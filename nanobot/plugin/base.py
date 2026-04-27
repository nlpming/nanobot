"""Plugin system base types for nanobot."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from nanobot.config.schema import Config


@dataclass
class PluginInput:
    """Context passed to each plugin on initialization."""

    workspace: Path
    config: "Config"


@dataclass
class PluginHooks:
    """Hooks a plugin can implement.

    Notification hooks receive data and perform side-effects.
    Trigger hooks receive (input_dict, output_dict) and may mutate output_dict
    to modify nanobot's behavior — same pattern as opencode hooks.
    """

    # Notification hooks
    config: Callable | None = None
    """async (cfg: Config) -> None — called once after all plugins load.
    Set cfg._extra_skill_dirs (list[str]) to register additional skill directories."""

    event: Callable | None = None
    """async (event_type: str, payload: dict) -> None — called for every EventBus event."""

    # Trigger hooks  (input, output) -> None, mutate output to change behavior
    chat_messages_transform: Callable | None = None
    """async (input: dict, output: dict) -> None
    output["messages"] is the full message list; mutate to transform before LLM call."""

    tool_execute_before: Callable | None = None
    """async (input: dict, output: dict) -> None
    input: {tool, session_id, call_id}; output: {args} — mutate args to change tool input."""

    tool_execute_after: Callable | None = None
    """async (input: dict, output: dict) -> None
    input: {tool, session_id, call_id, args}; output: {result} — mutate result."""

    shell_env: Callable | None = None
    """async (input: dict, output: dict) -> None
    input: {cwd, session_id}; output: {env: dict[str, str]} — add env vars for shell tools."""


class Plugin:
    """Base class for nanobot plugins.

    Subclass and implement ``initialize`` to return a ``PluginHooks`` object.

    Example::

        class MyPlugin(Plugin):
            async def initialize(self, plugin_input: PluginInput) -> PluginHooks:
                async def on_tool_before(inp, out):
                    out["args"]["debug"] = True
                return PluginHooks(tool_execute_before=on_tool_before)
    """

    async def initialize(self, plugin_input: PluginInput) -> PluginHooks:
        raise NotImplementedError
