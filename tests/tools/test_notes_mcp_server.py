"""
Tests for examples/mcp/notes_server.py

三层测试：
  1. NoteStore  — 纯业务逻辑，不依赖 MCP
  2. MCP server — 工具注册与工具输出格式
  3. nanobot 集成 — 通过 connect_mcp_servers 注册到 ToolRegistry
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager, AsyncExitStack
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

# ---------------------------------------------------------------------------
# 让 examples/ 可导入（不在 sys.path 里）
# ---------------------------------------------------------------------------

EXAMPLES_DIR = Path(__file__).parents[2] / "examples" / "mcp"


@pytest.fixture(autouse=True)
def _add_examples_to_path():
    sys.path.insert(0, str(EXAMPLES_DIR))
    yield
    sys.path.remove(str(EXAMPLES_DIR))


# ---------------------------------------------------------------------------
# 1. NoteStore 单元测试
# ---------------------------------------------------------------------------

class TestNoteStore:
    @pytest.fixture()
    def store(self, tmp_path):
        from notes_server import NoteStore
        return NoteStore(tmp_path / "notes")

    def test_create_writes_file(self, store, tmp_path):
        store.create("My Note", "Hello world")
        files = list((tmp_path / "notes").glob("*.md"))
        assert len(files) == 1
        assert "hello-world" in files[0].read_text() or "Hello world" in files[0].read_text()

    def test_create_adds_title_header(self, store):
        store.create("Shopping List", "- milk\n- eggs")
        content = store.read("Shopping List")
        assert content.startswith("# Shopping List")

    def test_create_overwrites_existing(self, store):
        store.create("Note", "version 1")
        store.create("Note", "version 2")
        assert "version 2" in store.read("Note")
        assert "version 1" not in store.read("Note")

    def test_create_returns_file_path(self, store, tmp_path):
        path = store.create("Test", "content")
        assert Path(path).exists()

    def test_create_raises_on_empty_title(self, store):
        with pytest.raises(ValueError):
            store.create("!@#$%", "content")

    def test_list_empty_directory(self, store):
        assert store.list_notes() == []

    def test_list_returns_all_notes(self, store):
        store.create("Alpha", "first")
        store.create("Beta", "second")
        notes = store.list_notes()
        assert len(notes) == 2
        titles = [n["title"] for n in notes]
        assert "Alpha" in titles
        assert "Beta" in titles

    def test_list_includes_preview(self, store):
        store.create("Tip", "Use pytest for testing")
        notes = store.list_notes()
        assert notes[0]["preview"] == "Use pytest for testing"

    def test_read_returns_full_content(self, store):
        store.create("Full Note", "line1\nline2\nline3")
        content = store.read("Full Note")
        assert "line1" in content
        assert "line3" in content

    def test_read_raises_file_not_found(self, store):
        with pytest.raises(FileNotFoundError):
            store.read("nonexistent")

    def test_delete_existing_note(self, store):
        store.create("Temp", "delete me")
        assert store.delete("Temp") is True
        with pytest.raises(FileNotFoundError):
            store.read("Temp")

    def test_delete_nonexistent_returns_false(self, store):
        assert store.delete("does-not-exist") is False

    def test_search_finds_matching_notes(self, store):
        store.create("Python Tips", "Use list comprehensions for cleaner code")
        store.create("Java Notes", "Use streams instead of loops")
        results = store.search("comprehensions")
        assert len(results) == 1
        assert "Python" in results[0]["title"] or "python" in results[0]["title"].lower()

    def test_search_is_case_insensitive(self, store):
        store.create("Meeting", "Discussed BUDGET planning")
        assert len(store.search("budget")) == 1

    def test_search_returns_snippet(self, store):
        store.create("Ideas", "The main idea is to simplify the API")
        results = store.search("simplify")
        assert results[0]["snippet"] != ""
        assert "simplify" in results[0]["snippet"].lower()

    def test_search_no_results(self, store):
        store.create("Note A", "hello world")
        assert store.search("xyz123notfound") == []

    def test_search_multiple_matches(self, store):
        store.create("Note 1", "python is great")
        store.create("Note 2", "I love python")
        store.create("Note 3", "javascript rules")
        results = store.search("python")
        assert len(results) == 2

    def test_title_with_spaces_creates_valid_file(self, store, tmp_path):
        store.create("My Great Note", "content")
        files = list((tmp_path / "notes").glob("*.md"))
        assert len(files) == 1
        # Filename should be slug-style (no spaces)
        assert " " not in files[0].name


# ---------------------------------------------------------------------------
# 2. MCP 工具注册与格式测试
# ---------------------------------------------------------------------------

class TestMCPTools:
    """Test the MCP tool wrappers built by build_mcp_server()."""

    @pytest.fixture()
    def store_and_mcp(self, tmp_path):
        from notes_server import NoteStore, build_mcp_server
        store = NoteStore(tmp_path / "notes")
        mcp = build_mcp_server(store)
        return store, mcp

    def _tool_func(self, mcp, name: str):
        """Extract the underlying callable for a registered tool."""
        # FastMCP stores tools in _tool_manager
        tool = mcp._tool_manager._tools.get(name)
        assert tool is not None, f"Tool '{name}' not registered"
        return tool.fn

    def test_all_tools_registered(self, store_and_mcp):
        _, mcp = store_and_mcp
        tools = mcp._tool_manager._tools
        for name in ("create_note", "list_notes", "read_note", "delete_note", "search_notes"):
            assert name in tools, f"Missing tool: {name}"

    @pytest.mark.asyncio
    async def test_create_note_tool_returns_success(self, store_and_mcp):
        store, mcp = store_and_mcp
        fn = self._tool_func(mcp, "create_note")
        result = fn(title="Test", content="hello")
        assert "Test" in result
        assert store.read("Test")  # actually written

    @pytest.mark.asyncio
    async def test_list_notes_tool_empty(self, store_and_mcp):
        _, mcp = store_and_mcp
        fn = self._tool_func(mcp, "list_notes")
        assert "No notes found" in fn()

    @pytest.mark.asyncio
    async def test_list_notes_tool_shows_count(self, store_and_mcp):
        store, mcp = store_and_mcp
        store.create("A", "first")
        store.create("B", "second")
        fn = self._tool_func(mcp, "list_notes")
        result = fn()
        assert "2 note(s)" in result

    @pytest.mark.asyncio
    async def test_read_note_tool_returns_content(self, store_and_mcp):
        store, mcp = store_and_mcp
        store.create("Hello", "world content")
        fn = self._tool_func(mcp, "read_note")
        assert "world content" in fn(title="Hello")

    @pytest.mark.asyncio
    async def test_read_note_tool_not_found_returns_error(self, store_and_mcp):
        _, mcp = store_and_mcp
        fn = self._tool_func(mcp, "read_note")
        result = fn(title="missing")
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_delete_note_tool_success(self, store_and_mcp):
        store, mcp = store_and_mcp
        store.create("Temp", "bye")
        fn = self._tool_func(mcp, "delete_note")
        result = fn(title="Temp")
        assert "deleted" in result.lower()

    @pytest.mark.asyncio
    async def test_delete_note_tool_not_found(self, store_and_mcp):
        _, mcp = store_and_mcp
        fn = self._tool_func(mcp, "delete_note")
        result = fn(title="ghost")
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_search_notes_tool_returns_matches(self, store_and_mcp):
        store, mcp = store_and_mcp
        store.create("Python", "generators and comprehensions")
        fn = self._tool_func(mcp, "search_notes")
        result = fn(query="generators")
        assert "1 match" in result
        assert "generators" in result.lower()

    @pytest.mark.asyncio
    async def test_search_notes_tool_no_match(self, store_and_mcp):
        _, mcp = store_and_mcp
        fn = self._tool_func(mcp, "search_notes")
        result = fn(query="zzznomatch")
        assert "No notes matching" in result


# ---------------------------------------------------------------------------
# 3. nanobot 集成测试：通过 connect_mcp_servers 注册到 ToolRegistry
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _fake_mcp_module(monkeypatch, tmp_path):
    """Stub the MCP SDK's transport so connect_mcp_servers works without a real process."""
    from notes_server import NoteStore, build_mcp_server

    store = NoteStore(tmp_path / "notes")
    notes_mcp = build_mcp_server(store)

    class _FakeTextContent:
        def __init__(self, text: str) -> None:
            self.text = text

    # Build fake session that delegates call_tool → notes_mcp tool functions
    class _FakeSession:
        async def initialize(self) -> None:
            pass

        async def list_tools(self):
            tools = []
            for name, tool in notes_mcp._tool_manager._tools.items():
                import inspect
                sig = inspect.signature(tool.fn)
                props = {
                    p: {"type": "string"}
                    for p in sig.parameters
                    if p not in ("self",)
                }
                tool_def = SimpleNamespace(
                    name=name,
                    description=tool.description or name,
                    inputSchema={"type": "object", "properties": props},
                )
                tools.append(tool_def)
            return SimpleNamespace(tools=tools)

        async def call_tool(self, name: str, arguments: dict):
            tool = notes_mcp._tool_manager._tools[name]
            result = tool.fn(**arguments)
            return SimpleNamespace(content=[_FakeTextContent(result)])

    fake_session = _FakeSession()

    mod = ModuleType("mcp")
    mod.types = SimpleNamespace(TextContent=_FakeTextContent)

    class _FakeClientSession:
        def __init__(self, _r, _w): pass
        async def __aenter__(self): return fake_session
        async def __aexit__(self, *a): return False

    @asynccontextmanager
    async def _fake_stdio(*_a, **_kw):
        yield object(), object()

    @asynccontextmanager
    async def _fake_sse(*_a, **_kw):
        yield object(), object()

    @asynccontextmanager
    async def _fake_http(*_a, **_kw):
        yield object(), object(), object()

    mod.ClientSession = _FakeClientSession
    mod.StdioServerParameters = SimpleNamespace

    stdio_mod = ModuleType("mcp.client.stdio")
    stdio_mod.stdio_client = _fake_stdio
    sse_mod = ModuleType("mcp.client.sse")
    sse_mod.sse_client = _fake_sse
    http_mod = ModuleType("mcp.client.streamable_http")
    http_mod.streamable_http_client = _fake_http

    monkeypatch.setitem(sys.modules, "mcp", mod)
    monkeypatch.setitem(sys.modules, "mcp.client", ModuleType("mcp.client"))
    monkeypatch.setitem(sys.modules, "mcp.client.stdio", stdio_mod)
    monkeypatch.setitem(sys.modules, "mcp.client.sse", sse_mod)
    monkeypatch.setitem(sys.modules, "mcp.client.streamable_http", http_mod)

    # Expose fake_session for integration tests
    monkeypatch.setattr("tests.tools.test_notes_mcp_server._shared_session", fake_session, raising=False)
    globals()["_shared_session"] = fake_session


_shared_session = None


class TestNotesNanobotIntegration:
    """Verify notes tools register and execute correctly via nanobot's MCP client."""

    async def _make_registry(self):
        from nanobot.agent.tools.mcp import connect_mcp_servers
        from nanobot.agent.tools.registry import ToolRegistry
        from nanobot.config.schema import MCPServerConfig

        registry = ToolRegistry()
        stack = AsyncExitStack()
        await stack.__aenter__()
        await connect_mcp_servers(
            {"notes": MCPServerConfig(command="python", args=["notes_server.py"])},
            registry,
            stack,
        )
        return registry, stack

    @pytest.mark.asyncio
    async def test_tools_registered_with_mcp_prefix(self):
        registry, stack = await self._make_registry()
        try:
            tool_names = registry.tool_names
            assert "mcp_notes_create_note" in tool_names
            assert "mcp_notes_list_notes" in tool_names
            assert "mcp_notes_read_note" in tool_names
            assert "mcp_notes_delete_note" in tool_names
            assert "mcp_notes_search_notes" in tool_names
        finally:
            await stack.aclose()

    @pytest.mark.asyncio
    async def test_create_and_read_via_registry(self):
        registry, stack = await self._make_registry()
        try:
            await registry.execute("mcp_notes_create_note", {"title": "MCP Test", "content": "via nanobot"})
            result = await registry.execute("mcp_notes_read_note", {"title": "MCP Test"})
            assert "via nanobot" in result
        finally:
            await stack.aclose()

    @pytest.mark.asyncio
    async def test_list_shows_created_notes(self):
        registry, stack = await self._make_registry()
        try:
            await registry.execute("mcp_notes_create_note", {"title": "Note X", "content": "content x"})
            result = await registry.execute("mcp_notes_list_notes", {})
            assert "Note X" in result or "note-x" in result.lower()
        finally:
            await stack.aclose()

    @pytest.mark.asyncio
    async def test_search_via_registry(self):
        registry, stack = await self._make_registry()
        try:
            await registry.execute("mcp_notes_create_note", {"title": "Async Guide", "content": "asyncio tasks and coroutines"})
            result = await registry.execute("mcp_notes_search_notes", {"query": "asyncio"})
            assert "asyncio" in result.lower()
        finally:
            await stack.aclose()

    @pytest.mark.asyncio
    async def test_delete_via_registry(self):
        registry, stack = await self._make_registry()
        try:
            await registry.execute("mcp_notes_create_note", {"title": "Temp Note", "content": "delete me"})
            delete_result = await registry.execute("mcp_notes_delete_note", {"title": "Temp Note"})
            assert "deleted" in delete_result.lower()
            read_result = await registry.execute("mcp_notes_read_note", {"title": "Temp Note"})
            assert "Error" in read_result
        finally:
            await stack.aclose()
