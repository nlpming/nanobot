"""Built-in slash command handlers."""

from __future__ import annotations

import asyncio
import os
import sys

from nanobot import __version__
from nanobot.bus.events import OutboundMessage
from nanobot.command.router import CommandContext, CommandRouter
from nanobot.utils.helpers import build_context_content, build_status_content


async def cmd_stop(ctx: CommandContext) -> OutboundMessage:
    """Cancel all active tasks and subagents for the session."""
    loop = ctx.loop
    msg = ctx.msg
    tasks = loop._active_tasks.pop(msg.session_key, [])
    cancelled = sum(1 for t in tasks if not t.done() and t.cancel())
    for t in tasks:
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass
    sub_cancelled = await loop.subagents.cancel_by_session(msg.session_key)
    total = cancelled + sub_cancelled
    content = f"Stopped {total} task(s)." if total else "No active task to stop."
    return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=content)


async def cmd_restart(ctx: CommandContext) -> OutboundMessage:
    """Restart the process in-place via os.execv."""
    msg = ctx.msg

    async def _do_restart():
        await asyncio.sleep(1)
        os.execv(sys.executable, [sys.executable, "-m", "nanobot"] + sys.argv[1:])

    asyncio.create_task(_do_restart())
    return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content="Restarting...")


async def cmd_status(ctx: CommandContext) -> OutboundMessage:
    """Build an outbound status message for a session."""
    loop = ctx.loop
    session = ctx.session or loop.sessions.get_or_create(ctx.key)
    ctx_est = 0
    try:
        ctx_est, _ = loop.memory_consolidator.estimate_session_prompt_tokens(session)
    except Exception:
        pass
    if ctx_est <= 0:
        ctx_est = loop._last_usage.get("prompt_tokens", 0)
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=build_status_content(
            version=__version__, model=loop.model,
            start_time=loop._start_time, last_usage=loop._last_usage,
            context_window_tokens=loop.context_window_tokens,
            session_msg_count=len(session.get_history(max_messages=0)),
            context_tokens_estimate=ctx_est,
        ),
        metadata={"render_as": "text"},
    )


async def cmd_new(ctx: CommandContext) -> OutboundMessage:
    """Start a fresh session."""
    loop = ctx.loop
    session = ctx.session or loop.sessions.get_or_create(ctx.key)
    snapshot = session.messages[session.last_consolidated:]
    session.clear()
    loop.sessions.save(session)
    loop.sessions.invalidate(session.key)
    if snapshot:
        loop._schedule_background(loop.memory_consolidator.archive_messages(snapshot))
    return OutboundMessage(
        channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
        content="New session started.",
    )


async def cmd_context(ctx: CommandContext) -> OutboundMessage:
    """Show per-category token breakdown of the current context window."""
    from nanobot.utils.helpers import estimate_message_tokens, estimate_prompt_tokens

    loop = ctx.loop
    session = ctx.session or loop.sessions.get_or_create(ctx.key)

    # System prompt (identity + bootstrap + memory), excluding skills
    try:
        full_prompt = loop.context.build_system_prompt()
        skills_section = loop.context.build_skills_section()
        core_prompt = full_prompt.replace(skills_section, "").strip() if skills_section else full_prompt
        system_tokens = estimate_prompt_tokens([{"role": "system", "content": core_prompt}])
    except Exception:
        system_tokens = 0

    # Skills section of the system prompt
    try:
        skills_tokens = estimate_prompt_tokens([{"role": "system", "content": skills_section}]) if skills_section else 0
    except Exception:
        skills_tokens = 0

    # Built-in tools (non-MCP)
    try:
        tools_tokens = estimate_prompt_tokens([], loop.tools.get_builtin_definitions())
    except Exception:
        tools_tokens = 0

    # MCP tools
    try:
        mcp_tokens = estimate_prompt_tokens([], loop.tools.get_mcp_definitions())
    except Exception:
        mcp_tokens = 0

    # Session messages
    try:
        history = session.get_history(max_messages=0)
        messages_tokens = sum(estimate_message_tokens(m) for m in history)
    except Exception:
        messages_tokens = 0

    content = build_context_content(
        model=loop.model,
        system_tokens=system_tokens,
        skills_tokens=skills_tokens,
        tools_tokens=tools_tokens,
        mcp_tokens=mcp_tokens,
        messages_tokens=messages_tokens,
        context_window_tokens=loop.context_window_tokens,
    )
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=content,
        metadata={"render_as": "text"},
    )


async def cmd_skills(ctx: CommandContext) -> OutboundMessage:
    """List all available skills (workspace + built-in)."""
    from nanobot.agent.skills import SkillsLoader

    loop = ctx.loop
    loader = SkillsLoader(loop.workspace)
    all_skills = loader.list_skills(filter_unavailable=False)

    if not all_skills:
        content = "No skills found."
    else:
        lines = ["📚 Skills:"]
        for s in all_skills:
            meta = loader.get_skill_metadata(s["name"]) or {}
            desc = meta.get("description", "")
            available = loader._check_requirements(loader._get_skill_meta(s["name"]))
            always = meta.get("always", "") in ("true", True)
            tags = []
            if not available:
                missing = loader._get_missing_requirements(loader._get_skill_meta(s["name"]))
                tags.append(f"unavailable: {missing}")
            if always:
                tags.append("always")
            tag_str = f"  [{', '.join(tags)}]" if tags else ""
            source_icon = "📁" if s["source"] == "workspace" else "📦"
            lines.append(f"{source_icon} {s['name']}{tag_str}")
            if desc:
                lines.append(f"   {desc}")
        content = "\n".join(lines)

    return OutboundMessage(
        channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
        content=content, metadata={"render_as": "text"},
    )


async def cmd_agents(ctx: CommandContext) -> OutboundMessage:
    """List all available custom subagents."""
    from nanobot.agent.agents import AgentLoader

    loop = ctx.loop
    loader = AgentLoader(loop.workspace)
    all_agents = loader.list_agents()

    if not all_agents:
        content = (
            "No custom agents found.\n"
            f"Add agents to: {loop.workspace / 'agents'}/<name>.md"
        )
    else:
        lines = ["🤖 Custom Agents:"]
        for a in all_agents:
            meta = loader._parse_frontmatter_from_path(a["path"])
            desc = meta.get("description", "")
            model = meta.get("model", "")
            tools = meta.get("tools")
            source_icon = "📁" if a["source"] == "workspace" else "🌐"
            lines.append(f"{source_icon} {a['name']}")
            if desc:
                lines.append(f"   {desc}")
            if model:
                lines.append(f"   model: {model}")
            if tools:
                tools_str = ", ".join(tools) if isinstance(tools, list) else tools
                lines.append(f"   tools: {tools_str}")
        content = "\n".join(lines)

    return OutboundMessage(
        channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
        content=content, metadata={"render_as": "text"},
    )


async def cmd_mcp(ctx: CommandContext) -> OutboundMessage:
    """List configured MCP servers and their registered tools."""
    loop = ctx.loop
    mcp_servers: dict = loop._mcp_servers or {}

    if not mcp_servers:
        content = "No MCP servers configured."
    else:
        # Group registered tools by server name
        tools_by_server: dict[str, list[str]] = {}
        for tool_name in loop.tools.tool_names:
            if tool_name.startswith("mcp_"):
                # tool name format: mcp_<server>_<tool>
                rest = tool_name[4:]  # strip "mcp_"
                for srv in mcp_servers:
                    prefix = srv + "_"
                    if rest.startswith(prefix):
                        original = rest[len(prefix):]
                        tools_by_server.setdefault(srv, []).append(original)
                        break
                else:
                    # fallback: use first underscore split
                    parts = rest.split("_", 1)
                    srv = parts[0]
                    tools_by_server.setdefault(srv, []).append(parts[1] if len(parts) > 1 else rest)

        connected = set(tools_by_server)
        lines = ["🔌 MCP Servers:"]
        for name in mcp_servers:
            if name in connected:
                tool_list = tools_by_server[name]
                lines.append(f"✅ {name}  ({len(tool_list)} tools)")
                for t in tool_list:
                    lines.append(f"   • {t}")
            else:
                lines.append(f"❌ {name}  (not connected)")
        content = "\n".join(lines)

    return OutboundMessage(
        channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
        content=content, metadata={"render_as": "text"},
    )


async def cmd_help(ctx: CommandContext) -> OutboundMessage:
    """Return available slash commands."""
    lines = [
        "🐈 nanobot commands:",
        "/new — Start a new conversation",
        "/stop — Stop the current task",
        "/restart — Restart the bot",
        "/status — Show bot status",
        "/context — Show context window token usage",
        "/skills — List available skills",
        "/agents — List custom subagents",
        "/mcp — List MCP servers and tools",
        "/help — Show available commands",
    ]
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content="\n".join(lines),
        metadata={"render_as": "text"},
    )


def register_builtin_commands(router: CommandRouter) -> None:
    """Register the default set of slash commands."""
    router.priority("/stop", cmd_stop)
    router.priority("/restart", cmd_restart)
    router.priority("/status", cmd_status)
    router.exact("/new", cmd_new)
    router.exact("/status", cmd_status)
    router.exact("/context", cmd_context)
    router.exact("/skills", cmd_skills)
    router.exact("/agents", cmd_agents)
    router.exact("/mcp", cmd_mcp)
    router.exact("/help", cmd_help)
