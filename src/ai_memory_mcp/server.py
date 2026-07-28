from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import MemoryConfig
from .store import MemoryStore


def create_mcp_server(config: MemoryConfig | None = None) -> FastMCP:
    store = MemoryStore(config)
    mcp = FastMCP(
        "hermes-memory",
        instructions=(
            "Hermes Memory stores an automatic verbatim 10-day turn archive, "
            "long-term schematic summaries, rolling day notes, permanent facts, "
            "and time-based events. Automatic code captures and retrieves memory "
            "even when the model does not call a tool. Only memory.search_exact_quotes "
            "results are valid sources for direct quotations; summaries must never "
            "be presented as verbatim speech. Preserve whether information is a fact, "
            "preference, possibility, plan, work in progress, or completed action."
        ),
    )

    @mcp.tool(name="memory.get_today")
    def get_today() -> dict[str, str]:
        """Return current local date/time for event reasoning."""
        return store.get_today()

    @mcp.tool(name="memory.get_context")
    def get_context(
        query: str = "",
        at: str | None = None,
        max_chars: int | None = None,
        include_detailed_memory: bool = True,
        include_search: bool = True,
    ) -> dict[str, Any]:
        """Build prompt-ready memory context for Hermes before an LLM call."""
        return store.get_context(
            query=query,
            at=at,
            max_chars=max_chars,
            include_detailed_memory=include_detailed_memory,
            include_search=include_search,
        )

    @mcp.tool(name="memory.save_turn")
    def save_turn(
        user_message: str,
        detailed_memory_text: str,
        assistant_message: str = "",
        memory_kind: str = "observation",
        memory_status: str = "confirmed",
        at: str | None = None,
        day: str | None = None,
        event_ids: list[str] | None = None,
        forever_facts: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Save every user turn as a concise original summary before the final answer.

        detailed_memory_text must paraphrase the useful meaning instead of copying
        the raw conversation. memory_kind and memory_status must preserve modality:
        a wish, possibility, or plan is not a confirmed present fact.
        """
        enriched_metadata = {
            "memory_kind": memory_kind.strip() or "observation",
            "memory_status": memory_status.strip() or "confirmed",
            **(metadata or {}),
        }
        return store.save_turn(
            user_message=user_message,
            assistant_message=assistant_message,
            detailed_memory_text=detailed_memory_text,
            at=at,
            day=day,
            event_ids=event_ids,
            forever_facts=forever_facts,
            metadata=enriched_metadata,
        )

    @mcp.tool(name="memory.append_day_memory")
    def append_day_memory(
        text: str,
        day: str | None = None,
        at: str | None = None,
        role: str = "memory",
        source: str = "manual",
        event_ids: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        rotate: bool = True,
    ) -> dict[str, Any]:
        """Append detailed text to a specific day in the rolling 10-day memory."""
        return store.append_day_memory(
            text,
            day=day,
            at=at,
            role=role,
            source=source,
            event_ids=event_ids,
            metadata=metadata,
            rotate=rotate,
        )

    @mcp.tool(name="memory.get_10_day_detailed_memory")
    def get_10_day_detailed_memory(today: str | None = None, max_chars: int | None = None) -> dict[str, Any]:
        """Return the detailed rolling memory for the latest retained days."""
        return store.get_10_day_detailed_memory(today=today, max_chars=max_chars)

    @mcp.tool(name="memory.rotate_10_day_memory")
    def rotate_10_day_memory(
        today: str | None = None,
        retention_days: int | None = None,
        delete_chars: int | None = None,
    ) -> dict[str, Any]:
        """Gradually delete the oldest detailed day chunks when more than 10 days exist."""
        return store.rotate_10_day_memory(today=today, retention_days=retention_days, delete_chars=delete_chars)

    @mcp.tool(name="memory.save_forever_fact")
    def save_forever_fact(
        fact: str,
        category: str = "user",
        importance: int = 7,
        pinned: bool = True,
        source: str = "manual",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Save a short permanent user fact."""
        return store.save_forever_fact(
            fact,
            category=category,
            importance=importance,
            pinned=pinned,
            source=source,
            metadata=metadata,
        )

    @mcp.tool(name="memory.list_forever_facts")
    def list_forever_facts(limit: int = 100) -> list[dict[str, Any]]:
        """List permanent user facts."""
        return store.list_forever_facts(limit=limit)

    @mcp.tool(name="memory.create_event")
    def create_event(
        title: str,
        event_type: str = "event",
        description: str = "",
        start_at: str | None = None,
        end_at: str | None = None,
        duration_days: int | None = None,
        timezone: str | None = None,
        status: str | None = None,
        importance: int = 6,
        summary: str = "",
        metadata: dict[str, Any] | None = None,
        auto_link_existing: bool = True,
    ) -> dict[str, Any]:
        """Create a time-based event or unresolved plan.

        For a wish or future intention with no known date, use event_type="plan"
        and status="planned". Do not supply an invented start_at value.
        """
        return store.create_event(
            title=title,
            event_type=event_type,
            description=description,
            start_at=start_at,
            end_at=end_at,
            duration_days=duration_days,
            timezone=timezone,
            status=status,
            importance=importance,
            summary=summary,
            metadata=metadata,
            auto_link_existing=auto_link_existing,
        )

    @mcp.tool(name="memory.update_event")
    def update_event(
        event_id: str,
        title: str | None = None,
        description: str | None = None,
        start_at: str | None = None,
        end_at: str | None = None,
        status: str | None = None,
        summary: str | None = None,
        importance: int | None = None,
    ) -> dict[str, Any]:
        """Update an existing event."""
        return store.update_event(
            event_id,
            title=title,
            description=description,
            start_at=start_at,
            end_at=end_at,
            status=status,
            summary=summary,
            importance=importance,
        )

    @mcp.tool(name="memory.list_events")
    def list_events(status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """List permanent events."""
        return store.list_events(status=status, limit=limit)

    @mcp.tool(name="memory.active_events")
    def active_events(at: str | None = None) -> list[dict[str, Any]]:
        """List events active at the given time or now."""
        return store.active_events(at=at)

    @mcp.tool(name="memory.open_events")
    def open_events(at: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """List active events plus unresolved plans, possibilities, and upcoming events."""
        return store.open_events(at=at, limit=limit)

    @mcp.tool(name="memory.get_event_context")
    def get_event_context(event_id: str, query: str = "", max_chars: int | None = None) -> dict[str, Any]:
        """Return memories and traces attached to one event."""
        return store.get_event_context(event_id, query=query, max_chars=max_chars)

    @mcp.tool(name="memory.link_memory_to_event")
    def link_memory_to_event(
        event_id: str,
        memory_type: str,
        memory_id: str,
        day: str | None = None,
        note: str = "",
    ) -> dict[str, Any]:
        """Attach a memory id to an event."""
        inserted = store.link_memory_to_event(event_id, memory_type, memory_id, day=day, note=note, commit=True)
        return {"linked": inserted, "event_id": event_id, "memory_type": memory_type, "memory_id": memory_id}

    @mcp.tool(name="memory.upsert_chat_session")
    def upsert_chat_session(
        chat_id: str | None = None,
        title: str = "",
        aliases: list[str] | None = None,
        summary: str = "",
        status: str = "active",
        at: str | None = None,
        event_ids: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create or update a separate 10-day chat card for handoff/search."""
        return store.upsert_chat_session(
            chat_id=chat_id,
            title=title,
            aliases=aliases,
            summary=summary,
            status=status,
            at=at,
            event_ids=event_ids,
            metadata=metadata,
        )

    @mcp.tool(name="memory.append_chat_note")
    def append_chat_note(
        text: str,
        chat_id: str | None = None,
        title: str = "",
        aliases: list[str] | None = None,
        summary: str = "",
        at: str | None = None,
        note_type: str = "progress",
        event_ids: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append a note to a separate 10-day chat card, optionally linked to events."""
        return store.append_chat_note(
            chat_id,
            text,
            title=title,
            aliases=aliases,
            summary=summary,
            at=at,
            note_type=note_type,
            event_ids=event_ids,
            metadata=metadata,
        )

    @mcp.tool(name="memory.get_chat_context")
    def get_chat_context(chat_id: str | None = None, query: str = "", max_chars: int | None = None) -> dict[str, Any]:
        """Return prompt-ready context from separate 10-day chat cards/notes."""
        return store.get_chat_context(chat_id=chat_id, query=query, max_chars=max_chars)

    @mcp.tool(name="memory.list_chat_sessions")
    def list_chat_sessions(limit: int = 20) -> list[dict[str, Any]]:
        """List active separate 10-day chat cards."""
        return store.list_chat_sessions(limit=limit)

    @mcp.tool(name="memory.link_chat_to_event")
    def link_chat_to_event(chat_id: str, event_id: str, note: str = "") -> dict[str, Any]:
        """Link a separate chat card to a permanent event."""
        inserted = store.link_chat_to_event(chat_id, event_id, note=note, commit=True)
        return {"linked": inserted, "chat_id": chat_id, "event_id": event_id}

    @mcp.tool(name="memory.rotate_chat_memory")
    def rotate_chat_memory(at: str | None = None, retention_days: int | None = None) -> dict[str, Any]:
        """Soft-delete separate chat cards older than their 10-day retention."""
        return store.rotate_chat_memory(at=at, retention_days=retention_days)

    @mcp.tool(name="memory.search")
    def search(query: str, limit: int | None = None) -> list[dict[str, Any]]:
        """Search exact turns, summaries, detailed days, facts, chats, and events."""
        return store.search(query, limit=limit)

    @mcp.tool(name="memory.search_exact_quotes")
    def search_exact_quotes(query: str, limit: int = 8) -> list[dict[str, Any]]:
        """Search only the active 10-day verbatim archive for exact quotations."""
        return store.search_exact_quotes(query, limit=limit)

    @mcp.tool(name="memory.recent_exact_turns")
    def recent_exact_turns(limit: int = 3) -> list[dict[str, Any]]:
        """Return the most recent complete 10-day turns as exact quotations."""
        return store.recent_exact_quotes(limit=limit)

    @mcp.tool(name="memory.forget_memory")
    def forget_memory(memory_id: str) -> dict[str, Any]:
        """Delete one detailed rolling memory chunk while preserving event traces."""
        return store.forget_memory(memory_id)

    @mcp.tool(name="memory.day_stats")
    def day_stats() -> list[dict[str, Any]]:
        """Return rolling detailed memory day sizes and rotation status."""
        return store.day_stats()

    @mcp.tool(name="memory.doctor")
    def doctor() -> dict[str, Any]:
        """Return storage health and feature information."""
        return store.doctor()

    return mcp


def run_server(config: MemoryConfig | None = None, *, transport: str = "stdio") -> None:
    server = create_mcp_server(config)
    server.run(transport=transport)
