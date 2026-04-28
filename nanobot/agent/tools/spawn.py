"""Spawn tool for creating background subagents."""

from typing import TYPE_CHECKING, Any

from nanobot.agent.tools.base import Tool

if TYPE_CHECKING:
    from nanobot.agent.subagent import SubagentManager


class SpawnTool(Tool):
    """Tool to spawn a subagent for background task execution."""

    def __init__(self, manager: "SubagentManager"):
        self._manager = manager

    def set_context(self, channel: str, chat_id: str) -> None:
        pass  # subagents run inline; no bus routing needed

    @property
    def name(self) -> str:
        return "spawn"

    @property
    def description(self) -> str:
        base = (
            "Spawn a subagent to complete a task and return its result. "
            "Multiple spawn calls in the same response run in parallel. "
            "Use this to delegate independent subtasks concurrently. "
            "For deliverables or existing projects, inspect the workspace first "
            "and use a dedicated subdirectory when helpful."
        )
        agents_summary = self._manager.agents.build_agents_summary()
        if agents_summary:
            return f"{base}\n\nAvailable custom agents:\n{agents_summary}"
        return base

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The task for the subagent to complete",
                },
                "agent": {
                    "type": "string",
                    "description": (
                        "Optional name of a custom agent to use (from the available agents list). "
                        "If omitted, the default general-purpose subagent is used."
                    ),
                },
                "label": {
                    "type": "string",
                    "description": "Optional short label for the task (for display)",
                },
            },
            "required": ["task"],
        }

    async def execute(self, task: str, agent: str | None = None, label: str | None = None, **kwargs: Any) -> str:
        """Spawn a subagent to execute the given task and return its result."""
        return await self._manager.spawn(task=task, agent=agent, label=label)
