import json
import logging
from typing import Any, Callable, Optional

log = logging.getLogger("deskd.tools")


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, dict] = {}

    def register(self, name: str, description: str, schema: dict, handler: Callable):
        self._tools[name] = {
            "name": name,
            "description": description,
            "schema": schema,
            "handler": handler,
        }

    def names(self) -> list[str]:
        return sorted(self._tools)

    def spec_for_llm(self) -> list[dict]:
        return [
            {"name": t["name"], "description": t["description"], "parameters": t["schema"]}
            for t in self._tools.values()
        ]

    async def call(self, name: str, args: Optional[dict] = None) -> Any:
        tool = self._tools.get(name)
        if not tool:
            return {"error": f"unknown tool {name!r}"}
        try:
            result = tool["handler"](**(args or {}))
            if hasattr(result, "__await__"):
                result = await result
            return result
        except Exception as e:
            log.exception("tool %s failed", name)
            return {"error": str(e)}


def build_native_registry(cfg, vault, reminders: "ReminderStoreLike", ctl_bus=None) -> ToolRegistry:
    from ..integrations import obsidian as obs
    from ..integrations import screencap as sc
    from ..integrations import websearch as ws

    reg = ToolRegistry()

    reg.register(
        "reminders_list",
        "List upcoming reminders",
        {},
        lambda: [dict(i) for i in reminders.list()],
    )

    def _reminder_add(title: str, when_str: str):
        from ..scheduler.reminders import parse_when

        due = parse_when(when_str)
        if due is None:
            return {"error": f"unparseable time: {when_str!r}"}
        return dict(reminders.add(str(title), due))

    reg.register(
        "reminder_add",
        "Create a reminder. when_str examples: 'in 30m', 'at 17:30', 'tomorrow 9am'",
        {"title": {"type": "string"}, "when_str": {"type": "string"}},
        _reminder_add,
    )

    def _now():
        return {"now": __import__("datetime").datetime.now().strftime(
            "%A %Y-%m-%d %H:%M:%S")}

    reg.register("get_current_datetime",
                 "Current local date and time", {}, _now)

    if vault is not None:

        def _notes_search(query: str, limit: int = 5):
            return vault.search(query, limit)

        def _notes_tasks(limit: int = 20):
            return vault.tasks(limit)

        def _inbox_append(text: str, as_task: bool = True):
            return {"written_to": vault.append_inbox(text, as_task)}

        def _notes_digest(limit: int = 5):
            return vault.digest(limit)

        reg.register("notes_search", "Search Obsidian notes by keyword", {
            "query": {"type": "string"}, "limit": {"type": "integer"}}, _notes_search)
        reg.register("notes_tasks", "List pending tasks across the vault", {
            "limit": {"type": "integer"}}, _notes_tasks)
        reg.register("inbox_append", "Append a line/task to the inbox note", {
            "text": {"type": "string"}, "as_task": {"type": "boolean"}}, _inbox_append)
        reg.register("notes_digest", "Summaries of recently edited notes", {
            "limit": {"type": "integer"}}, _notes_digest)

    if cfg.websearch.provider.lower() in ("tavily", "brave"):
        reg.register(
            "web_search",
            "Web search via configured provider",
            {"query": {"type": "string"}},
            lambda query: ws.web_search(query, cfg),
        )

    if getattr(cfg, "allow_screen_capture", False):
        reg.register(
            "screen_capture",
            "Capture the screen (opt-in)",
            {},
            lambda: sc.capture_screen(),
        )

    return reg


async def discover_mcp_tools(registry: ToolRegistry, mcp_cfg: dict) -> int:
    """Optionally connect to configured MCP servers and merge their tools.

    mcp_cfg shape: {"<server-name>": {"command": "...", "args": [...], "env": {...}}}
    Returns number of tools added. Silently skips when the mcp SDK is absent.
    """
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError:
        log.info("mcp SDK not installed; skipping MCP discovery")
        return 0

    added = 0
    for name, conf in (mcp_cfg or {}).items():
        try:
            params = StdioServerParameters(
                command=conf["command"],
                args=conf.get("args", []),
                env=conf.get("env"),
            )
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    listing = await session.list_tools()
                    for tool in listing.tools:
                        registry.register(
                            f"mcp_{name}_{tool.name}",
                            tool.description or "",
                            tool.inputSchema or {},
                            _make_mcp_proxy(session, name, tool.name),
                        )
                        added += 1
        except Exception:
            log.exception("MCP server %s failed; skipping", name)
    log.info("MCP discovery added %d tools", added)
    return added


def _make_mcp_proxy(session, server_name: str, tool_name: str):
    async def proxy(**kwargs):
        result = await session.call_tool(tool_name, arguments=kwargs)
        parts = []
        for block in getattr(result, "content", []):
            text = getattr(block, "text", None)
            parts.append(text if text is not None else json.dumps(getattr(block, "data", str(block))))
        return "\n".join(parts) or None

    proxy.__name__ = f"mcp_{server_name}_{tool_name}"
    return proxy


class ReminderStoreLike:
    pass
