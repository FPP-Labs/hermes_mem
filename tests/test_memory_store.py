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
            timezone="Europe/Moscow",
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
        fact = store.save_forever_fact("Пользователя зовут FPP.", category="identity")
        assert fact["id"].startswith("fact_")
        assert store.list_forever_facts()[0]["fact"] == "Пользователя зовут FPP."
    finally:
        store.close()


def test_rolling_10_days_forgets_oldest_day(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    try:
        for day in range(1, 12):
            store.append_day_memory(
                f"Подробное описание дня {day}. Разговоры, детали, контекст.",
                at=f"2026-01-{day:02d}T10:00:00+03:00",
            )

        stats = store.day_stats()
        by_day = {row["day"]: row for row in stats}
        assert by_day["2026-01-01"]["status"] == "forgotten"
        assert by_day["2026-01-01"]["active_chunks"] == 0
        assert by_day["2026-01-11"]["active_chunks"] == 1

        detailed = store.get_10_day_detailed_memory(today="2026-01-11")
        assert "дня 1." not in detailed["context_text"]
        assert "дня 11." in detailed["context_text"]
        assert len(detailed["days"]) == 10
    finally:
        store.close()


def test_event_links_active_turns_and_keeps_trace_after_rotation(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    try:
        event = store.create_event(
            title="Поездка пользователя",
            event_type="trip",
            description="Пользователь будет в поездке 10 дней.",
            start_at="2026-02-01T00:00:00+03:00",
            duration_days=10,
        )

        saved = store.save_turn(
            user_message="Сегодня первый день поездки, место очень понравилось.",
            assistant_message="Запомнил это как часть поездки.",
            at="2026-02-01T09:00:00+03:00",
        )
        chunk_id = saved["chunk"]["id"]

        event_context = store.get_event_context(event["id"])
        assert chunk_id in {memory["memory_id"] for memory in event_context["memories"]}
        assert "место очень понравилось" in event_context["context_text"]

        for day in range(2, 13):
            store.append_day_memory(
                f"Большое подробное описание дня {day} после начала поездки.",
                at=f"2026-02-{day:02d}T10:00:00+03:00",
            )

        event_context_after = store.get_event_context(event["id"])
        assert event_context_after["forgotten_link_count"] >= 1
        assert any("место очень понравилось" in trace["text"] for trace in event_context_after["traces"])
    finally:
        store.close()


def test_chat_cards_are_separate_searchable_and_rotate(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    try:
        started_at = datetime.now(ZoneInfo("Europe/Moscow")).replace(microsecond=0)
        started_iso = started_at.isoformat(timespec="seconds")
        rotate_iso = (started_at + timedelta(days=18)).isoformat(timespec="seconds")
        event = store.create_event(
            title="Выбор ноутбука",
            event_type="purchase",
            description="Пользователь выбирает мобильный ноутбук.",
            start_at=started_iso,
        )
        note = store.append_chat_note(
            "chat_macbook_lenovo",
            "CHECKPOINT: обсуждали продажу Lenovo ради MacBook Neo; вывод — macOS лучше закрывать настоящим MacBook.",
            title="Продажа Lenovo ради MacBook Neo",
            aliases=["MacBook вместо Lenovo", "Lenovo IdeaPad 3"],
            summary="Выбор MacBook Neo как мобильной macOS-машины.",
            at=started_iso,
            event_ids=[event["id"]],
        )

        assert note["chat_id"] == "chat_macbook_lenovo"
        assert store.day_stats() == []

        results = store.search("MacBook вместо Lenovo", limit=10)
        assert any(item["type"] == "chat_session" and item["id"] == "chat_macbook_lenovo" for item in results)
        assert any(item["type"] == "chat_note" and item["chat_id"] == "chat_macbook_lenovo" for item in results)

        context = store.get_chat_context(chat_id="chat_macbook_lenovo")
        assert "Продажа Lenovo ради MacBook Neo" in context["context_text"]
        assert "Выбор ноутбука" in context["context_text"]

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
            title="Старый проект",
            event_type="project",
            start_at="2020-01-01T09:00:00+03:00",
        )
        note = store.append_chat_note(
            "chat_historical",
            "Решение из старого чата.",
            title="Архивный чат",
            at="2020-01-02T12:00:00+03:00",
            event_ids=[event["id"]],
        )

        assert note["chat"]["id"] == "chat_historical"
        assert note["chat"]["linked_event_ids"] == [event["id"]]
        assert store.list_chat_sessions() == []
    finally:
        store.close()


def test_mcp_server_can_be_created(tmp_path: Path) -> None:
    config = MemoryConfig(db_path=tmp_path / "memory.sqlite3", timezone="Europe/Moscow")
    server = create_mcp_server(config)
    assert server.name == "hermes-memory"
