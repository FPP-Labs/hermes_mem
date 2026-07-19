from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from ai_memory_mcp.config import MemoryConfig
from ai_memory_mcp.server import create_mcp_server
from ai_memory_mcp.store import MemoryStore


def make_store(tmp_path: Path, *, delete_chars: int = 100_000) -> MemoryStore:
    return MemoryStore(
        MemoryConfig(
            db_path=tmp_path / "memory.sqlite3",
            timezone="UTC",
            detailed_retention_days=10,
            chat_retention_days=10,
            gradual_delete_chars=delete_chars,
            max_context_chars=200_000,
            max_search_items=20,
            auto_attach_active_events=True,
        )
    )


def test_forever_fact_and_today(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    try:
        today = store.get_today()
        assert {"time", "day", "month", "year", "timezone", "human"} <= set(today)
        fact = store.save_forever_fact("The user's name is Alex.", category="identity")
        assert fact["id"].startswith("fact_")
        assert store.list_forever_facts()[0]["fact"] == "The user's name is Alex."
    finally:
        store.close()


def test_rolling_10_days_forgets_oldest_day(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    try:
        for day in range(1, 12):
            store.append_day_memory(
                f"Detailed description of day {day}. Conversations, details, and context.",
                at=f"2026-01-{day:02d}T10:00:00+03:00",
            )

        stats = store.day_stats()
        by_day = {row["day"]: row for row in stats}
        assert by_day["2026-01-01"]["status"] == "forgotten"
        assert by_day["2026-01-01"]["active_chunks"] == 0
        assert by_day["2026-01-11"]["active_chunks"] == 1

        detailed = store.get_10_day_detailed_memory(today="2026-01-11")
        assert "day 1." not in detailed["context_text"]
        assert "day 11." in detailed["context_text"]
        assert len(detailed["days"]) == 10
    finally:
        store.close()


def test_event_links_active_turns_and_keeps_trace_after_rotation(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    try:
        event = store.create_event(
            title="User trip",
            event_type="trip",
            description="The user will be traveling for 10 days.",
            start_at="2026-02-01T00:00:00+03:00",
            duration_days=10,
        )

        saved = store.save_turn(
            user_message="Today is the first day of the trip, and I really liked the place.",
            assistant_message="I saved this as part of the trip.",
            at="2026-02-01T09:00:00+03:00",
        )
        chunk_id = saved["chunk"]["id"]

        event_context = store.get_event_context(event["id"])
        assert chunk_id in {memory["memory_id"] for memory in event_context["memories"]}
        assert "really liked the place" in event_context["context_text"]

        for day in range(2, 13):
            store.append_day_memory(
                f"Long detailed description of day {day} after the trip started.",
                at=f"2026-02-{day:02d}T10:00:00+03:00",
            )

        event_context_after = store.get_event_context(event["id"])
        assert event_context_after["forgotten_link_count"] >= 1
        assert any("really liked the place" in trace["text"] for trace in event_context_after["traces"])
    finally:
        store.close()


def test_chat_cards_are_separate_searchable_and_rotate(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    try:
        started_at = datetime.now(ZoneInfo("UTC")).replace(microsecond=0)
        started_iso = started_at.isoformat(timespec="seconds")
        rotate_iso = (started_at + timedelta(days=18)).isoformat(timespec="seconds")
        event = store.create_event(
            title="Choosing a laptop",
            event_type="purchase",
            description="The user is choosing a portable laptop.",
            start_at=started_iso,
        )
        note = store.append_chat_note(
            "chat_macbook_lenovo",
            "CHECKPOINT: discussed selling the Lenovo for a MacBook Neo; conclusion: a real MacBook is the better macOS machine.",
            title="Selling Lenovo for a MacBook Neo",
            aliases=["MacBook instead of Lenovo", "Lenovo IdeaPad 3"],
            summary="Choosing a MacBook Neo as a portable macOS machine.",
            at=started_iso,
            event_ids=[event["id"]],
        )

        assert note["chat_id"] == "chat_macbook_lenovo"
        assert store.day_stats() == []

        results = store.search("MacBook instead of Lenovo", limit=10)
        assert any(item["type"] == "chat_session" and item["id"] == "chat_macbook_lenovo" for item in results)
        assert any(item["type"] == "chat_note" and item["chat_id"] == "chat_macbook_lenovo" for item in results)

        context = store.get_chat_context(chat_id="chat_macbook_lenovo")
        assert "Selling Lenovo for a MacBook Neo" in context["context_text"]
        assert "Choosing a laptop" in context["context_text"]

        rotated = store.rotate_chat_memory(at=rotate_iso)
        assert rotated["deleted_chat_count"] == 1
        assert store.list_chat_sessions() == []
        assert not any(item.get("chat_id") == "chat_macbook_lenovo" for item in store.search("MacBook Lenovo", limit=10))
    finally:
        store.close()


def test_historical_chat_import_uses_the_supplied_time(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    try:
        event = store.create_event(
            title="Old project",
            event_type="project",
            start_at="2020-01-01T09:00:00+03:00",
        )
        note = store.append_chat_note(
            "chat_historical",
            "Decision from an old chat.",
            title="Archived chat",
            at="2020-01-02T12:00:00+03:00",
            event_ids=[event["id"]],
        )

        assert note["chat"]["id"] == "chat_historical"
        assert note["chat"]["linked_event_ids"] == [event["id"]]
        assert store.list_chat_sessions() == []
    finally:
        store.close()


def test_mcp_server_can_be_created(tmp_path: Path) -> None:
    config = MemoryConfig(db_path=tmp_path / "memory.sqlite3", timezone="UTC")
    server = create_mcp_server(config)
    assert server.name == "hermes-memory"


def test_memory_dashboard_exposes_today_long_term_ten_day_and_active_events(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    try:
        today = store.get_today()
        store.append_day_memory("Today the user selected a blue keyboard.", day=today["date"])
        store.save_forever_fact("The user prefers blue keyboards.", category="preference")
        store.create_event(title="Keyboard project", description="Selecting a blue keyboard.")

        dashboard = store.memory_dashboard(query="blue keyboard", scope="all")
        assert dashboard["today_memory"]["chunks"]
        assert dashboard["ten_day_memory"]
        assert dashboard["forever_facts"]
        assert dashboard["active_events"]
        assert {item["type"] for item in dashboard["search"]["results"]} >= {"day_chunk", "forever_fact"}

        long_term = store.memory_dashboard(query="blue keyboard", scope="long-term")
        assert {item["type"] for item in long_term["search"]["results"]} == {"forever_fact"}
        ten_day = store.memory_dashboard(query="blue keyboard", scope="10-day")
        assert all(item["type"] in {"day_chunk", "chat_session", "chat_note"} for item in ten_day["search"]["results"])
        events = store.memory_dashboard(query="blue keyboard", scope="events")
        assert events["search"]["results"]
        assert all(item["type"] in {"event", "event_trace"} for item in events["search"]["results"])
    finally:
        store.close()


def test_clear_all_memory_requires_confirmation_and_clears_every_layer(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    try:
        store.append_day_memory("Short-term detail")
        store.save_forever_fact("Permanent detail")
        event = store.create_event(title="Active event")
        store.append_chat_note("chat_clear", "Chat detail", title="Clear test", event_ids=[event["id"]])

        try:
            store.clear_all_memory(confirmation="DELETE")
        except ValueError as exc:
            assert "DELETE_ALL_MEMORY" in str(exc)
        else:
            raise AssertionError("clear_all_memory accepted an invalid confirmation")

        result = store.clear_all_memory(confirmation="DELETE_ALL_MEMORY")
        assert result["deleted"] is True
        assert store.day_stats() == []
        assert store.list_forever_facts() == []
        assert store.list_events() == []
        assert store.list_chat_sessions() == []
        assert store.search("detail") == []
        assert all(value == 0 for key, value in store.doctor().items() if key in result["previous_counts"])
    finally:
        store.close()
