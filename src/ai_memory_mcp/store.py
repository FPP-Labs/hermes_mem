from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

from .config import MemoryConfig
from .time_utils import end_after_days, event_status, iso_now, now_in, parse_day, parse_datetime, today_payload


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _json(data: dict[str, Any] | None) -> str:
    return json.dumps(data or {}, ensure_ascii=False, sort_keys=True)


def _loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _loads_list(value: str | None) -> list[Any]:
    if not value:
        return []
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return []
    return loaded if isinstance(loaded, list) else []


def _tokens(query: str) -> list[str]:
    return [token for token in re.findall(r"[\w]+", query, flags=re.UNICODE) if token]


def _fts_query(query: str) -> str:
    tokens = _tokens(query)
    return " OR ".join(f"{token}*" for token in tokens)


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


class MemoryStore:
    """SQLite storage for Hermes memory.

    The store has four durable layers:
    - rolling detailed day chunks for the last N days;
    - forever user facts;
    - forever events with links/traces to day memories.
    - separate 10-day chat cards/notes with links to events.
    """

    def __init__(self, config: MemoryConfig | None = None, *, db_path: str | Path | None = None) -> None:
        if config is None:
            config = MemoryConfig.load()
        if db_path is not None:
            config = MemoryConfig(
                db_path=Path(db_path).expanduser(),
                timezone=config.timezone,
                detailed_retention_days=config.detailed_retention_days,
                chat_retention_days=config.chat_retention_days,
                gradual_delete_chars=config.gradual_delete_chars,
                max_context_chars=config.max_context_chars,
                max_search_items=config.max_search_items,
                auto_attach_active_events=config.auto_attach_active_events,
            )
        self.config = config
        self.zone = config.zoneinfo()
        self.db_path = config.db_path.expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.init_db()

    def close(self) -> None:
        self.conn.close()

    def init_db(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS days (
                day TEXT PRIMARY KEY,
                timezone TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                purge_started_at TEXT,
                deleted_at TEXT
            );

            CREATE TABLE IF NOT EXISTS turns (
                id TEXT PRIMARY KEY,
                day TEXT NOT NULL,
                user_message TEXT NOT NULL,
                assistant_message TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS day_chunks (
                id TEXT PRIMARY KEY,
                day TEXT NOT NULL,
                text TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'memory',
                source TEXT NOT NULL DEFAULT 'manual',
                turn_id TEXT,
                order_index INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                deleted_at TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY(day) REFERENCES days(day),
                FOREIGN KEY(turn_id) REFERENCES turns(id)
            );

            CREATE INDEX IF NOT EXISTS idx_day_chunks_day_order
                ON day_chunks(day, order_index);
            CREATE INDEX IF NOT EXISTS idx_day_chunks_deleted
                ON day_chunks(deleted_at);

            CREATE TABLE IF NOT EXISTS forever_facts (
                id TEXT PRIMARY KEY,
                fact TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'user',
                importance INTEGER NOT NULL DEFAULT 5,
                pinned INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'manual',
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE INDEX IF NOT EXISTS idx_forever_facts_importance
                ON forever_facts(importance DESC, updated_at DESC);

            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                event_type TEXT NOT NULL DEFAULT 'event',
                description TEXT NOT NULL DEFAULT '',
                start_at TEXT,
                end_at TEXT,
                timezone TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                importance INTEGER NOT NULL DEFAULT 5,
                summary TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE INDEX IF NOT EXISTS idx_events_time
                ON events(start_at, end_at);
            CREATE INDEX IF NOT EXISTS idx_events_status
                ON events(status);

            CREATE TABLE IF NOT EXISTS event_memory_links (
                id TEXT PRIMARY KEY,
                event_id TEXT NOT NULL,
                memory_type TEXT NOT NULL,
                memory_id TEXT NOT NULL,
                day TEXT,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE(event_id, memory_type, memory_id),
                FOREIGN KEY(event_id) REFERENCES events(id)
            );

            CREATE INDEX IF NOT EXISTS idx_event_memory_links_event
                ON event_memory_links(event_id);
            CREATE INDEX IF NOT EXISTS idx_event_memory_links_memory
                ON event_memory_links(memory_type, memory_id);

            CREATE TABLE IF NOT EXISTS event_traces (
                id TEXT PRIMARY KEY,
                event_id TEXT NOT NULL,
                day TEXT,
                text TEXT NOT NULL,
                source_chunk_id TEXT,
                created_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                UNIQUE(event_id, source_chunk_id),
                FOREIGN KEY(event_id) REFERENCES events(id)
            );

            CREATE INDEX IF NOT EXISTS idx_event_traces_event
                ON event_traces(event_id, day);

            CREATE TABLE IF NOT EXISTS chat_sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '',
                aliases_json TEXT NOT NULL DEFAULT '[]',
                summary TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                started_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                deleted_at TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE INDEX IF NOT EXISTS idx_chat_sessions_updated
                ON chat_sessions(updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_chat_sessions_expires
                ON chat_sessions(expires_at, deleted_at);

            CREATE TABLE IF NOT EXISTS chat_notes (
                id TEXT PRIMARY KEY,
                chat_id TEXT NOT NULL,
                day TEXT NOT NULL,
                text TEXT NOT NULL,
                note_type TEXT NOT NULL DEFAULT 'progress',
                created_at TEXT NOT NULL,
                deleted_at TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY(chat_id) REFERENCES chat_sessions(id)
            );

            CREATE INDEX IF NOT EXISTS idx_chat_notes_chat
                ON chat_notes(chat_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_chat_notes_deleted
                ON chat_notes(deleted_at);

            CREATE TABLE IF NOT EXISTS chat_event_links (
                id TEXT PRIMARY KEY,
                chat_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE(chat_id, event_id),
                FOREIGN KEY(chat_id) REFERENCES chat_sessions(id),
                FOREIGN KEY(event_id) REFERENCES events(id)
            );

            CREATE INDEX IF NOT EXISTS idx_chat_event_links_chat
                ON chat_event_links(chat_id);
            CREATE INDEX IF NOT EXISTS idx_chat_event_links_event
                ON chat_event_links(event_id);

            CREATE TABLE IF NOT EXISTS operations (
                id TEXT PRIMARY KEY,
                op_type TEXT NOT NULL,
                details_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            """
        )
        self._init_fts()
        self.conn.commit()

    def _init_fts(self) -> None:
        self.conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS day_chunks_fts USING fts5(id UNINDEXED, day UNINDEXED, text)"
        )
        self.conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS forever_facts_fts USING fts5(id UNINDEXED, fact)"
        )
        self.conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(id UNINDEXED, title, description, summary)"
        )
        self.conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS event_traces_fts USING fts5(id UNINDEXED, event_id UNINDEXED, text)"
        )
        self.conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS chat_sessions_fts USING fts5(id UNINDEXED, title, aliases, summary)"
        )
        self.conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS chat_notes_fts USING fts5(id UNINDEXED, chat_id UNINDEXED, text)"
        )

    def log_operation(self, op_type: str, details: dict[str, Any] | None = None) -> None:
        self.conn.execute(
            "INSERT INTO operations (id, op_type, details_json, created_at) VALUES (?, ?, ?, ?)",
            (_id("op"), op_type, _json(details), iso_now(self.zone)),
        )

    def get_today(self) -> dict[str, str]:
        return today_payload(self.zone)

    def ensure_day(self, day: str) -> None:
        now = iso_now(self.zone)
        self.conn.execute(
            """
            INSERT INTO days (day, timezone, status, created_at, updated_at)
            VALUES (?, ?, 'active', ?, ?)
            ON CONFLICT(day) DO UPDATE SET updated_at = excluded.updated_at
            """,
            (day, self.config.timezone, now, now),
        )

    def append_day_memory(
        self,
        text: str,
        *,
        day: str | None = None,
        at: str | None = None,
        role: str = "memory",
        source: str = "manual",
        turn_id: str | None = None,
        event_ids: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        rotate: bool = True,
    ) -> dict[str, Any]:
        cleaned = text.strip()
        if not cleaned:
            raise ValueError("text must not be empty")
        memory_day = day or parse_day(at, self.zone)
        self.ensure_day(memory_day)
        order_index = self.next_order_index(memory_day)
        chunk_id = _id("chunk")
        created_at = parse_datetime(at, self.zone).isoformat(timespec="seconds") if at else iso_now(self.zone)
        self.conn.execute(
            """
            INSERT INTO day_chunks
                (id, day, text, role, source, turn_id, order_index, created_at, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (chunk_id, memory_day, cleaned, role, source, turn_id, order_index, created_at, _json(metadata)),
        )
        self.conn.execute(
            "INSERT INTO day_chunks_fts (id, day, text) VALUES (?, ?, ?)",
            (chunk_id, memory_day, cleaned),
        )

        linked_event_ids = list(dict.fromkeys(event_ids or []))
        if self.config.auto_attach_active_events:
            linked_event_ids.extend(event["id"] for event in self.active_events(at=created_at))
            linked_event_ids = list(dict.fromkeys(linked_event_ids))
        for event_id in linked_event_ids:
            self.link_memory_to_event(event_id, "day_chunk", chunk_id, day=memory_day)

        if rotate:
            rotation = self.rotate_10_day_memory(today=memory_day)
        else:
            rotation = {"rotated": False, "deleted_chars": 0, "days": []}
        self.conn.commit()
        return {
            "id": chunk_id,
            "day": memory_day,
            "order_index": order_index,
            "chars": len(cleaned),
            "linked_event_ids": linked_event_ids,
            "rotation": rotation,
        }

    def next_order_index(self, day: str) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(MAX(order_index), 0) + 1 AS next_index FROM day_chunks WHERE day = ?",
            (day,),
        ).fetchone()
        return int(row["next_index"])

    def save_turn(
        self,
        *,
        user_message: str,
        assistant_message: str = "",
        detailed_memory_text: str | None = None,
        at: str | None = None,
        day: str | None = None,
        event_ids: list[str] | None = None,
        forever_facts: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not user_message.strip() and not assistant_message.strip():
            raise ValueError("user_message or assistant_message must not be empty")
        created_at = parse_datetime(at, self.zone).isoformat(timespec="seconds") if at else iso_now(self.zone)
        memory_day = day or parse_day(created_at, self.zone)
        self.ensure_day(memory_day)
        turn_id = _id("turn")
        self.conn.execute(
            """
            INSERT INTO turns
                (id, day, user_message, assistant_message, created_at, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (turn_id, memory_day, user_message.strip(), assistant_message.strip(), created_at, _json(metadata)),
        )
        detailed_text = detailed_memory_text.strip() if detailed_memory_text else self._format_turn_memory(
            created_at, user_message, assistant_message
        )
        chunk = self.append_day_memory(
            detailed_text,
            day=memory_day,
            at=created_at,
            role="turn",
            source="save_turn",
            turn_id=turn_id,
            event_ids=event_ids,
            metadata={"turn_id": turn_id, **(metadata or {})},
            rotate=True,
        )
        fact_results = []
        for fact in forever_facts or []:
            if fact.strip():
                fact_results.append(self.save_forever_fact(fact.strip(), source="save_turn"))
        self.conn.commit()
        return {"turn_id": turn_id, "day": memory_day, "chunk": chunk, "forever_facts": fact_results}

    def _format_turn_memory(self, created_at: str, user_message: str, assistant_message: str) -> str:
        parts = [f"[{created_at}]"]
        if user_message.strip():
            parts.append(f"Пользователь: {user_message.strip()}")
        if assistant_message.strip():
            parts.append(f"Hermes: {assistant_message.strip()}")
        return "\n".join(parts)

    def save_forever_fact(
        self,
        fact: str,
        *,
        category: str = "user",
        importance: int = 7,
        pinned: bool = True,
        source: str = "manual",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        cleaned = fact.strip()
        if not cleaned:
            raise ValueError("fact must not be empty")
        now = iso_now(self.zone)
        fact_id = _id("fact")
        self.conn.execute(
            """
            INSERT INTO forever_facts
                (id, fact, category, importance, pinned, created_at, updated_at, source, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (fact_id, cleaned, category, int(importance), 1 if pinned else 0, now, now, source, _json(metadata)),
        )
        self.conn.execute("INSERT INTO forever_facts_fts (id, fact) VALUES (?, ?)", (fact_id, cleaned))
        self.conn.commit()
        return {"id": fact_id, "fact": cleaned, "category": category, "importance": int(importance), "pinned": pinned}

    def list_forever_facts(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT * FROM forever_facts
            ORDER BY pinned DESC, importance DESC, updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [self._fact_payload(row) for row in rows]

    def _fact_payload(self, row: sqlite3.Row) -> dict[str, Any]:
        payload = _row_to_dict(row)
        payload["pinned"] = bool(payload["pinned"])
        payload["metadata"] = _loads(payload.pop("metadata_json", "{}"))
        return payload

    def create_event(
        self,
        *,
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
        cleaned_title = title.strip()
        if not cleaned_title:
            raise ValueError("title must not be empty")
        tz = timezone or self.config.timezone
        zone = self.zone if tz == self.config.timezone else MemoryConfig(db_path=self.db_path, timezone=tz).zoneinfo()
        now = iso_now(self.zone)
        start_iso = parse_datetime(start_at, zone).isoformat(timespec="seconds") if start_at else now
        end_iso = parse_datetime(end_at, zone).isoformat(timespec="seconds") if end_at else None
        if duration_days is not None and not end_iso:
            end_iso = end_after_days(start_iso, int(duration_days), zone)
        computed_status = status or event_status(start_iso, end_iso, zone)
        event_id = _id("event")
        self.conn.execute(
            """
            INSERT INTO events
                (id, title, event_type, description, start_at, end_at, timezone, status,
                 importance, summary, created_at, updated_at, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                cleaned_title,
                event_type,
                description.strip(),
                start_iso,
                end_iso,
                tz,
                computed_status,
                int(importance),
                summary.strip(),
                now,
                now,
                _json(metadata),
            ),
        )
        self.conn.execute(
            "INSERT INTO events_fts (id, title, description, summary) VALUES (?, ?, ?, ?)",
            (event_id, cleaned_title, description.strip(), summary.strip()),
        )
        linked_existing = 0
        if auto_link_existing:
            linked_existing = self.link_existing_day_memories_to_event(event_id)
        self.conn.commit()
        payload = self.get_event(event_id)
        payload["linked_existing_count"] = linked_existing
        return payload

    def get_event(self, event_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        if not row:
            raise KeyError(f"event not found: {event_id}")
        return self._event_payload(row)

    def _event_payload(self, row: sqlite3.Row) -> dict[str, Any]:
        payload = _row_to_dict(row)
        payload["metadata"] = _loads(payload.pop("metadata_json", "{}"))
        payload["computed_status"] = event_status(payload.get("start_at"), payload.get("end_at"), self.zone)
        return payload

    def update_event(
        self,
        event_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
        start_at: str | None = None,
        end_at: str | None = None,
        status: str | None = None,
        summary: str | None = None,
        importance: int | None = None,
    ) -> dict[str, Any]:
        current = self.get_event(event_id)
        values = {
            "title": title.strip() if title is not None else current["title"],
            "description": description.strip() if description is not None else current["description"],
            "start_at": parse_datetime(start_at, self.zone).isoformat(timespec="seconds")
            if start_at is not None
            else current["start_at"],
            "end_at": parse_datetime(end_at, self.zone).isoformat(timespec="seconds")
            if end_at is not None
            else current["end_at"],
            "status": status if status is not None else current["status"],
            "summary": summary.strip() if summary is not None else current["summary"],
            "importance": int(importance) if importance is not None else current["importance"],
            "updated_at": iso_now(self.zone),
        }
        self.conn.execute(
            """
            UPDATE events
            SET title = ?, description = ?, start_at = ?, end_at = ?, status = ?,
                summary = ?, importance = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                values["title"],
                values["description"],
                values["start_at"],
                values["end_at"],
                values["status"],
                values["summary"],
                values["importance"],
                values["updated_at"],
                event_id,
            ),
        )
        self.conn.execute("DELETE FROM events_fts WHERE id = ?", (event_id,))
        self.conn.execute(
            "INSERT INTO events_fts (id, title, description, summary) VALUES (?, ?, ?, ?)",
            (event_id, values["title"], values["description"], values["summary"]),
        )
        self.conn.commit()
        return self.get_event(event_id)

    def list_events(self, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if status:
            rows = self.conn.execute(
                "SELECT * FROM events WHERE status = ? ORDER BY start_at DESC, created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM events ORDER BY start_at DESC, created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._event_payload(row) for row in rows]

    def active_events(self, *, at: str | None = None) -> list[dict[str, Any]]:
        current = parse_datetime(at, self.zone) if at else now_in(self.zone)
        rows = self.conn.execute("SELECT * FROM events ORDER BY importance DESC, start_at DESC").fetchall()
        active = []
        for row in rows:
            payload = self._event_payload(row)
            if event_status(payload.get("start_at"), payload.get("end_at"), self.zone, at=current) == "active":
                active.append(payload)
        return active

    def link_existing_day_memories_to_event(self, event_id: str) -> int:
        event = self.get_event(event_id)
        start = parse_datetime(event.get("start_at"), self.zone)
        end = parse_datetime(event.get("end_at"), self.zone)
        if not start:
            return 0
        start_day = start.date().isoformat()
        end_day = end.date().isoformat() if end else start_day
        rows = self.conn.execute(
            """
            SELECT id, day FROM day_chunks
            WHERE deleted_at IS NULL AND day >= ? AND day <= ?
            ORDER BY day, order_index
            """,
            (start_day, end_day),
        ).fetchall()
        count = 0
        for row in rows:
            if self.link_memory_to_event(event_id, "day_chunk", row["id"], day=row["day"], commit=False):
                count += 1
        return count

    def link_memory_to_event(
        self,
        event_id: str,
        memory_type: str,
        memory_id: str,
        *,
        day: str | None = None,
        note: str = "",
        commit: bool = False,
    ) -> bool:
        self.get_event(event_id)
        now = iso_now(self.zone)
        try:
            self.conn.execute(
                """
                INSERT INTO event_memory_links
                    (id, event_id, memory_type, memory_id, day, note, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (_id("link"), event_id, memory_type, memory_id, day, note, now),
            )
            inserted = True
        except sqlite3.IntegrityError:
            inserted = False
        if commit:
            self.conn.commit()
        return inserted

    def _chat_expires_at(self, at: str | None = None) -> str:
        base = parse_datetime(at, self.zone) if at else now_in(self.zone)
        return (base + timedelta(days=self.config.chat_retention_days)).isoformat(timespec="seconds")

    def _chat_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        data = _row_to_dict(row)
        data["aliases"] = [str(item) for item in _loads_list(data.pop("aliases_json", "[]")) if str(item).strip()]
        data["metadata"] = _loads(data.pop("metadata_json", "{}"))
        data["linked_event_ids"] = [
            linked["event_id"]
            for linked in self.conn.execute(
                "SELECT event_id FROM chat_event_links WHERE chat_id = ? ORDER BY created_at, id",
                (data["id"],),
            ).fetchall()
        ]
        return data

    def upsert_chat_session(
        self,
        *,
        chat_id: str | None = None,
        title: str = "",
        aliases: list[str] | None = None,
        summary: str = "",
        status: str = "active",
        at: str | None = None,
        event_ids: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = parse_datetime(at, self.zone).isoformat(timespec="seconds") if at else iso_now(self.zone)
        session_id = chat_id.strip() if chat_id and chat_id.strip() else _id("chat")
        clean_aliases = [alias.strip() for alias in aliases or [] if alias and alias.strip()]
        existing = self.conn.execute("SELECT * FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()

        if existing:
            existing_aliases = [str(item) for item in _loads_list(existing["aliases_json"]) if str(item).strip()]
            merged_aliases = list(dict.fromkeys([*existing_aliases, *clean_aliases]))
            next_title = title.strip() or existing["title"]
            next_summary = summary.strip() or existing["summary"]
            next_metadata = {**_loads(existing["metadata_json"]), **(metadata or {})}
            self.conn.execute(
                """
                UPDATE chat_sessions
                SET title = ?, aliases_json = ?, summary = ?, status = ?, updated_at = ?,
                    expires_at = ?, deleted_at = NULL, metadata_json = ?
                WHERE id = ?
                """,
                (
                    next_title,
                    json.dumps(merged_aliases, ensure_ascii=False),
                    next_summary,
                    status or existing["status"],
                    now,
                    self._chat_expires_at(now),
                    _json(next_metadata),
                    session_id,
                ),
            )
            self.conn.execute("DELETE FROM chat_sessions_fts WHERE id = ?", (session_id,))
            self.conn.execute(
                "INSERT INTO chat_sessions_fts (id, title, aliases, summary) VALUES (?, ?, ?, ?)",
                (session_id, next_title, " ".join(merged_aliases), next_summary),
            )
        else:
            self.conn.execute(
                """
                INSERT INTO chat_sessions
                    (id, title, aliases_json, summary, status, started_at, updated_at, expires_at, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    title.strip(),
                    json.dumps(clean_aliases, ensure_ascii=False),
                    summary.strip(),
                    status,
                    now,
                    now,
                    self._chat_expires_at(now),
                    _json(metadata),
                ),
            )
            self.conn.execute(
                "INSERT INTO chat_sessions_fts (id, title, aliases, summary) VALUES (?, ?, ?, ?)",
                (session_id, title.strip(), " ".join(clean_aliases), summary.strip()),
            )

        for event_id in event_ids or []:
            if event_id:
                self.link_chat_to_event(session_id, event_id, at=now, commit=False)
        self.conn.commit()
        return self.get_chat_session(session_id, at=now)

    def get_chat_session(self, chat_id: str, *, at: str | None = None) -> dict[str, Any]:
        current = parse_datetime(at, self.zone).isoformat(timespec="seconds") if at else iso_now(self.zone)
        row = self.conn.execute(
            "SELECT * FROM chat_sessions WHERE id = ? AND deleted_at IS NULL AND expires_at >= ?",
            (chat_id, current),
        ).fetchone()
        if row is None:
            raise KeyError(f"chat session not found: {chat_id}")
        return self._chat_row_to_dict(row)

    def link_chat_to_event(
        self,
        chat_id: str,
        event_id: str,
        *,
        note: str = "",
        at: str | None = None,
        commit: bool = True,
    ) -> bool:
        self.get_chat_session(chat_id, at=at)
        self.get_event(event_id)
        now = iso_now(self.zone)
        try:
            self.conn.execute(
                """
                INSERT INTO chat_event_links (id, chat_id, event_id, note, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (_id("chatlink"), chat_id, event_id, note, now),
            )
            inserted = True
        except sqlite3.IntegrityError:
            inserted = False
        if commit:
            self.conn.commit()
        return inserted

    def append_chat_note(
        self,
        chat_id: str | None,
        text: str,
        *,
        title: str = "",
        aliases: list[str] | None = None,
        summary: str = "",
        at: str | None = None,
        note_type: str = "progress",
        event_ids: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not text.strip():
            raise ValueError("chat note text must not be empty")
        session = self.upsert_chat_session(
            chat_id=chat_id,
            title=title,
            aliases=aliases,
            summary=summary,
            at=at,
            event_ids=event_ids,
            metadata=metadata,
        )
        created_at = parse_datetime(at, self.zone).isoformat(timespec="seconds") if at else iso_now(self.zone)
        day = parse_day(created_at, self.zone)
        note_id = _id("chatnote")
        clean_text = text.strip()
        self.conn.execute(
            """
            INSERT INTO chat_notes
                (id, chat_id, day, text, note_type, created_at, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (note_id, session["id"], day, clean_text, note_type, created_at, _json(metadata)),
        )
        self.conn.execute(
            "INSERT INTO chat_notes_fts (id, chat_id, text) VALUES (?, ?, ?)",
            (note_id, session["id"], clean_text),
        )
        self.conn.execute(
            "UPDATE chat_sessions SET updated_at = ?, expires_at = ? WHERE id = ?",
            (created_at, self._chat_expires_at(created_at), session["id"]),
        )
        self.conn.commit()
        return {
            "id": note_id,
            "chat_id": session["id"],
            "day": day,
            "text": clean_text,
            "note_type": note_type,
            "created_at": created_at,
            "chat": self.get_chat_session(session["id"], at=created_at),
        }

    def list_chat_sessions(self, *, limit: int = 20, include_deleted: bool = False) -> list[dict[str, Any]]:
        where = "" if include_deleted else "WHERE deleted_at IS NULL AND expires_at >= ?"
        params: tuple[Any, ...] = (limit,) if include_deleted else (iso_now(self.zone), limit)
        rows = self.conn.execute(
            f"SELECT * FROM chat_sessions {where} ORDER BY updated_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [self._chat_row_to_dict(row) for row in rows]

    def get_chat_context(
        self,
        *,
        chat_id: str | None = None,
        query: str = "",
        max_chars: int | None = None,
    ) -> dict[str, Any]:
        limit_chars = max_chars or min(self.config.max_context_chars, 16_000)
        session = self.get_chat_session(chat_id) if chat_id else None
        notes: list[dict[str, Any]] = []
        if chat_id:
            rows = self.conn.execute(
                """
                SELECT * FROM chat_notes
                WHERE chat_id = ? AND deleted_at IS NULL
                ORDER BY created_at
                """,
                (chat_id,),
            ).fetchall()
            notes = [_row_to_dict(row) for row in rows]
        elif query.strip():
            notes = self._search_chat_notes(_fts_query(query), self.config.max_search_items)

        event_rows = []
        if chat_id:
            event_rows = self.conn.execute(
                """
                SELECT e.*, l.note AS link_note
                FROM chat_event_links l
                JOIN events e ON e.id = l.event_id
                WHERE l.chat_id = ?
                ORDER BY e.start_at, e.created_at
                """,
                (chat_id,),
            ).fetchall()
        events = [self._event_payload(row) | {"link_note": row["link_note"]} for row in event_rows]

        parts = []
        if session:
            title = session.get("title") or session["id"]
            aliases = ", ".join(session.get("aliases") or [])
            parts.append(f"Чат: {title}")
            if aliases:
                parts.append(f"Алиасы: {aliases}")
            if session.get("summary"):
                parts.append(f"Сводка: {session['summary']}")
        if events:
            parts.append("Связанные события:\n" + "\n".join(f"- {self._format_event(event)}" for event in events))
        if notes:
            parts.append(
                "Заметки чата:\n"
                + "\n".join(f"- [{note.get('day') or note.get('created_at')}] {note['text']}" for note in notes)
            )
        context_text, truncated = self._fit_text("\n\n".join(parts), limit_chars)
        return {
            "chat": session,
            "events": events,
            "note_count": len(notes),
            "notes_preview": [
                {
                    "id": note.get("id"),
                    "day": note.get("day"),
                    "text": self._trace_text(str(note.get("text") or ""), limit=500),
                }
                for note in notes[:8]
            ],
            "context_text": context_text,
            "truncated": truncated,
        }

    def rotate_chat_memory(self, *, at: str | None = None, retention_days: int | None = None) -> dict[str, Any]:
        now = parse_datetime(at, self.zone).isoformat(timespec="seconds") if at else iso_now(self.zone)
        if retention_days is not None:
            cutoff = (parse_datetime(now, self.zone) - timedelta(days=retention_days)).isoformat(timespec="seconds")
            rows = self.conn.execute(
                "SELECT id FROM chat_sessions WHERE deleted_at IS NULL AND updated_at < ?",
                (cutoff,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT id FROM chat_sessions WHERE deleted_at IS NULL AND expires_at < ?",
                (now,),
            ).fetchall()
        chat_ids = [row["id"] for row in rows]
        for chat_id in chat_ids:
            note_rows = self.conn.execute("SELECT id FROM chat_notes WHERE chat_id = ?", (chat_id,)).fetchall()
            self.conn.execute("UPDATE chat_sessions SET deleted_at = ? WHERE id = ?", (now, chat_id))
            self.conn.execute("UPDATE chat_notes SET deleted_at = ? WHERE chat_id = ?", (now, chat_id))
            self.conn.execute("DELETE FROM chat_sessions_fts WHERE id = ?", (chat_id,))
            for row in note_rows:
                self.conn.execute("DELETE FROM chat_notes_fts WHERE id = ?", (row["id"],))
        self.conn.commit()
        return {"rotated": bool(chat_ids), "deleted_chat_count": len(chat_ids), "chat_ids": chat_ids}

    def get_event_context(self, event_id: str, *, query: str = "", max_chars: int | None = None) -> dict[str, Any]:
        event = self.get_event(event_id)
        limit_chars = max_chars or self.config.max_context_chars
        linked_rows = self.conn.execute(
            """
            SELECT l.*, c.text, c.deleted_at
            FROM event_memory_links l
            LEFT JOIN day_chunks c ON l.memory_type = 'day_chunk' AND c.id = l.memory_id
            WHERE l.event_id = ?
            ORDER BY l.day, l.created_at
            """,
            (event_id,),
        ).fetchall()
        memories = []
        forgotten_links = 0
        for row in linked_rows:
            text = row["text"]
            if row["memory_type"] == "day_chunk" and (not text or row["deleted_at"]):
                forgotten_links += 1
                continue
            memories.append(
                {
                    "link_id": row["id"],
                    "memory_type": row["memory_type"],
                    "memory_id": row["memory_id"],
                    "day": row["day"],
                    "note": row["note"],
                    "text": text,
                }
            )
        traces = [
            _row_to_dict(row)
            for row in self.conn.execute(
                "SELECT id, day, text, source_chunk_id, created_at FROM event_traces WHERE event_id = ? ORDER BY day, created_at",
                (event_id,),
            ).fetchall()
        ]
        if query:
            memories = [memory for memory in memories if query.lower() in (memory.get("text") or "").lower()]
            traces = [trace for trace in traces if query.lower() in trace["text"].lower()]
        text_parts = [self._format_event(event)]
        if memories:
            text_parts.append("Связанные подробные воспоминания события:")
            for memory in memories:
                text_parts.append(f"- {memory['day']}: {memory['text']}")
        if traces:
            text_parts.append("Короткие следы удаленной подробной памяти события:")
            for trace in traces:
                text_parts.append(f"- {trace['day']}: {trace['text']}")
        context_text, truncated = self._fit_text("\n".join(text_parts), limit_chars)
        return {
            "event": event,
            "memories": memories,
            "traces": traces,
            "forgotten_link_count": forgotten_links,
            "context_text": context_text,
            "truncated": truncated,
        }

    def rotate_10_day_memory(
        self,
        *,
        today: str | None = None,
        retention_days: int | None = None,
        delete_chars: int | None = None,
    ) -> dict[str, Any]:
        keep_days = retention_days or self.config.detailed_retention_days
        budget = self.config.gradual_delete_chars if delete_chars is None else delete_chars
        memory_today = today or now_in(self.zone).date().isoformat()
        rows = self.conn.execute(
            """
            SELECT d.day, d.status, COALESCE(SUM(LENGTH(c.text)), 0) AS chars,
                   COUNT(c.id) AS chunks
            FROM days d
            JOIN day_chunks c ON c.day = d.day AND c.deleted_at IS NULL
            WHERE d.deleted_at IS NULL AND d.day <= ?
            GROUP BY d.day, d.status
            ORDER BY d.day
            """,
            (memory_today,),
        ).fetchall()
        days = [_row_to_dict(row) for row in rows]
        if len(days) <= keep_days:
            return {"rotated": False, "deleted_chars": 0, "days": [], "active_day_count": len(days)}

        surplus = days[: len(days) - keep_days]
        deleted_chars = 0
        affected_days: list[dict[str, Any]] = []
        now = iso_now(self.zone)
        for day_info in surplus:
            if budget is not None and budget <= 0:
                break
            day = day_info["day"]
            self.conn.execute(
                """
                UPDATE days
                SET status = 'rotating', purge_started_at = COALESCE(purge_started_at, ?), updated_at = ?
                WHERE day = ?
                """,
                (now, now, day),
            )
            remaining_budget = None if budget is None else budget
            removed = self._delete_day_chunks(day, remaining_budget)
            deleted_chars += removed["deleted_chars"]
            if budget is not None:
                budget -= removed["deleted_chars"]
            active_left = self.conn.execute(
                "SELECT COUNT(*) AS count FROM day_chunks WHERE day = ? AND deleted_at IS NULL",
                (day,),
            ).fetchone()["count"]
            if active_left == 0:
                self.conn.execute(
                    "UPDATE days SET status = 'forgotten', deleted_at = ?, updated_at = ? WHERE day = ?",
                    (now, now, day),
                )
            affected_days.append({"day": day, **removed, "active_chunks_left": active_left})
        self.log_operation(
            "rotate_10_day_memory",
            {"today": memory_today, "retention_days": keep_days, "deleted_chars": deleted_chars, "days": affected_days},
        )
        self.conn.commit()
        return {
            "rotated": bool(affected_days),
            "deleted_chars": deleted_chars,
            "days": affected_days,
            "active_day_count_before": len(days),
            "retention_days": keep_days,
        }

    def _delete_day_chunks(self, day: str, budget: int | None) -> dict[str, Any]:
        rows = self.conn.execute(
            """
            SELECT id, text, order_index
            FROM day_chunks
            WHERE day = ? AND deleted_at IS NULL
            ORDER BY order_index
            """,
            (day,),
        ).fetchall()
        deleted_chunks = 0
        deleted_chars = 0
        now = iso_now(self.zone)
        for row in rows:
            text = row["text"]
            if budget is not None and deleted_chars >= budget:
                break
            self._preserve_event_traces_for_chunk(row["id"], day, text)
            self.conn.execute("UPDATE day_chunks SET deleted_at = ? WHERE id = ?", (now, row["id"]))
            self.conn.execute("DELETE FROM day_chunks_fts WHERE id = ?", (row["id"],))
            deleted_chunks += 1
            deleted_chars += len(text)
        return {"deleted_chunks": deleted_chunks, "deleted_chars": deleted_chars}

    def _preserve_event_traces_for_chunk(self, chunk_id: str, day: str, text: str) -> None:
        links = self.conn.execute(
            """
            SELECT event_id FROM event_memory_links
            WHERE memory_type = 'day_chunk' AND memory_id = ?
            """,
            (chunk_id,),
        ).fetchall()
        if not links:
            return
        trace_text = self._trace_text(text)
        now = iso_now(self.zone)
        for link in links:
            trace_id = _id("trace")
            try:
                self.conn.execute(
                    """
                    INSERT INTO event_traces
                        (id, event_id, day, text, source_chunk_id, created_at, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (trace_id, link["event_id"], day, trace_text, chunk_id, now, _json({"source": "rotation"})),
                )
                self.conn.execute(
                    "INSERT INTO event_traces_fts (id, event_id, text) VALUES (?, ?, ?)",
                    (trace_id, link["event_id"], trace_text),
                )
            except sqlite3.IntegrityError:
                continue

    def _trace_text(self, text: str, *, limit: int = 1200) -> str:
        cleaned = " ".join(text.split())
        if len(cleaned) <= limit:
            return cleaned
        return f"{cleaned[: limit - 3].rstrip()}..."

    def get_10_day_detailed_memory(self, *, today: str | None = None, max_chars: int | None = None) -> dict[str, Any]:
        memory_today = today or now_in(self.zone).date().isoformat()
        rows = self.conn.execute(
            """
            SELECT DISTINCT d.day
            FROM days d
            JOIN day_chunks c ON c.day = d.day AND c.deleted_at IS NULL
            WHERE d.deleted_at IS NULL AND d.day <= ?
            ORDER BY d.day DESC
            LIMIT ?
            """,
            (memory_today, self.config.detailed_retention_days),
        ).fetchall()
        days_desc = [row["day"] for row in rows]
        days = list(reversed(days_desc))
        day_payloads = []
        parts = []
        for day in days:
            chunks = [
                _row_to_dict(row)
                for row in self.conn.execute(
                    """
                    SELECT id, day, text, role, source, turn_id, order_index, created_at
                    FROM day_chunks
                    WHERE day = ? AND deleted_at IS NULL
                    ORDER BY order_index
                    """,
                    (day,),
                ).fetchall()
            ]
            day_text = "\n\n".join(chunk["text"] for chunk in chunks)
            parts.append(f"## {day}\n{day_text}")
            day_payloads.append({"day": day, "chunks": chunks, "chars": len(day_text)})
        context_text, truncated = self._fit_text("\n\n".join(parts), max_chars or self.config.max_context_chars)
        return {"days": day_payloads, "context_text": context_text, "truncated": truncated}

    def get_context(
        self,
        *,
        query: str = "",
        at: str | None = None,
        max_chars: int | None = None,
        include_detailed_memory: bool = True,
        include_search: bool = True,
    ) -> dict[str, Any]:
        requested_limit = max_chars or self.config.max_context_chars
        limit_chars = max(2_000, min(int(requested_limit), 24_000))
        today = self.get_today()
        current_at = at or today["now"]
        active_events = self.active_events(at=current_at)
        facts = self.list_forever_facts(limit=50)
        detailed_budget = max(2_000, limit_chars // 2)
        detailed = self.get_10_day_detailed_memory(today=parse_day(current_at, self.zone), max_chars=detailed_budget)
        search_results = self.search(query, limit=self.config.max_search_items) if query and include_search else []

        sections = [f"Сегодня: {today['human']} ({today['timezone']})."]
        if facts:
            sections.append("Вечные факты о пользователе:\n" + "\n".join(f"- {fact['fact']}" for fact in facts))
        if active_events:
            sections.append("Активные события:\n" + "\n".join(f"- {self._format_event(event)}" for event in active_events))
        if query and search_results:
            sections.append(
                "Релевантные найденные воспоминания:\n"
                + "\n".join(f"- [{item['type']}] {item['text']}" for item in search_results)
            )
        if include_detailed_memory and detailed["context_text"]:
            sections.append("Подробная 10-дневная память:\n" + detailed["context_text"])
        context_text, truncated = self._fit_text("\n\n".join(sections), limit_chars)
        return {
            "today": today,
            "forever_fact_count": len(facts),
            "active_event_count": len(active_events),
            "detailed_memory": {
                "day_count": len(detailed.get("days", [])),
                "chars": sum(int(day.get("chars") or 0) for day in detailed.get("days", [])),
                "truncated": detailed["truncated"],
            },
            "search_result_count": len(search_results),
            "search_results_preview": [
                {
                    "type": item.get("type"),
                    "id": item.get("id"),
                    "day": item.get("day"),
                    "text": self._trace_text(str(item.get("text") or ""), limit=500),
                }
                for item in search_results[:5]
            ],
            "context_text": context_text,
            "truncated": truncated or detailed["truncated"],
        }

    def search(self, query: str, *, limit: int | None = None) -> list[dict[str, Any]]:
        cleaned = query.strip()
        if not cleaned:
            return []
        max_items = limit or self.config.max_search_items
        fts = _fts_query(cleaned)
        if not fts:
            return []
        results: list[dict[str, Any]] = []
        results.extend(self._search_chat_sessions(fts, max_items))
        results.extend(self._search_chat_notes(fts, max_items))
        results.extend(self._search_day_chunks(fts, max_items))
        results.extend(self._search_facts(fts, max_items))
        results.extend(self._search_events(fts, max_items))
        results.extend(self._search_event_traces(fts, max_items))
        return results[:max_items]

    def _search_day_chunks(self, fts_query: str, limit: int) -> list[dict[str, Any]]:
        try:
            rows = self.conn.execute(
                """
                SELECT c.id, c.day, c.text, c.created_at
                FROM day_chunks_fts
                JOIN day_chunks c ON c.id = day_chunks_fts.id
                WHERE day_chunks_fts MATCH ? AND c.deleted_at IS NULL
                ORDER BY bm25(day_chunks_fts)
                LIMIT ?
                """,
                (fts_query, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [
            {"type": "day_chunk", "id": row["id"], "day": row["day"], "text": row["text"], "created_at": row["created_at"]}
            for row in rows
        ]

    def _search_facts(self, fts_query: str, limit: int) -> list[dict[str, Any]]:
        try:
            rows = self.conn.execute(
                """
                SELECT f.id, f.fact, f.category, f.importance
                FROM forever_facts_fts
                JOIN forever_facts f ON f.id = forever_facts_fts.id
                WHERE forever_facts_fts MATCH ?
                ORDER BY bm25(forever_facts_fts)
                LIMIT ?
                """,
                (fts_query, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [
            {
                "type": "forever_fact",
                "id": row["id"],
                "text": row["fact"],
                "category": row["category"],
                "importance": row["importance"],
            }
            for row in rows
        ]

    def _search_events(self, fts_query: str, limit: int) -> list[dict[str, Any]]:
        try:
            rows = self.conn.execute(
                """
                SELECT e.*
                FROM events_fts
                JOIN events e ON e.id = events_fts.id
                WHERE events_fts MATCH ?
                ORDER BY bm25(events_fts)
                LIMIT ?
                """,
                (fts_query, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [
            {
                "type": "event",
                "id": row["id"],
                "text": self._format_event(self._event_payload(row)),
                "status": row["status"],
                "start_at": row["start_at"],
                "end_at": row["end_at"],
            }
            for row in rows
        ]

    def _search_event_traces(self, fts_query: str, limit: int) -> list[dict[str, Any]]:
        try:
            rows = self.conn.execute(
                """
                SELECT t.id, t.event_id, t.day, t.text, t.created_at
                FROM event_traces_fts
                JOIN event_traces t ON t.id = event_traces_fts.id
                WHERE event_traces_fts MATCH ?
                ORDER BY bm25(event_traces_fts)
                LIMIT ?
                """,
                (fts_query, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [
            {
                "type": "event_trace",
                "id": row["id"],
                "event_id": row["event_id"],
                "day": row["day"],
                "text": row["text"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def _search_chat_sessions(self, fts_query: str, limit: int) -> list[dict[str, Any]]:
        try:
            rows = self.conn.execute(
                """
                SELECT c.*
                FROM chat_sessions_fts
                JOIN chat_sessions c ON c.id = chat_sessions_fts.id
                WHERE chat_sessions_fts MATCH ? AND c.deleted_at IS NULL AND c.expires_at >= ?
                ORDER BY bm25(chat_sessions_fts)
                LIMIT ?
                """,
                (fts_query, iso_now(self.zone), limit),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [
            {
                "type": "chat_session",
                "id": row["id"],
                "text": " | ".join(part for part in [row["title"], row["summary"]] if part),
                "title": row["title"],
                "aliases": [str(item) for item in _loads_list(row["aliases_json"]) if str(item).strip()],
                "updated_at": row["updated_at"],
                "expires_at": row["expires_at"],
            }
            for row in rows
        ]

    def _search_chat_notes(self, fts_query: str, limit: int) -> list[dict[str, Any]]:
        try:
            rows = self.conn.execute(
                """
                SELECT n.id, n.chat_id, n.day, n.text, n.note_type, n.created_at, c.title
                FROM chat_notes_fts
                JOIN chat_notes n ON n.id = chat_notes_fts.id
                JOIN chat_sessions c ON c.id = n.chat_id
                WHERE chat_notes_fts MATCH ? AND n.deleted_at IS NULL AND c.deleted_at IS NULL AND c.expires_at >= ?
                ORDER BY bm25(chat_notes_fts)
                LIMIT ?
                """,
                (fts_query, iso_now(self.zone), limit),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [
            {
                "type": "chat_note",
                "id": row["id"],
                "chat_id": row["chat_id"],
                "chat_title": row["title"],
                "day": row["day"],
                "text": row["text"],
                "note_type": row["note_type"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def forget_memory(self, memory_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT id, day, text FROM day_chunks WHERE id = ? AND deleted_at IS NULL",
            (memory_id,),
        ).fetchone()
        if not row:
            raise KeyError(f"active day chunk not found: {memory_id}")
        self._preserve_event_traces_for_chunk(row["id"], row["day"], row["text"])
        now = iso_now(self.zone)
        self.conn.execute("UPDATE day_chunks SET deleted_at = ? WHERE id = ?", (now, memory_id))
        self.conn.execute("DELETE FROM day_chunks_fts WHERE id = ?", (memory_id,))
        self.log_operation("forget_memory", {"memory_id": memory_id})
        self.conn.commit()
        return {"forgotten": True, "memory_id": memory_id, "day": row["day"], "chars": len(row["text"])}

    def doctor(self) -> dict[str, Any]:
        try:
            self.conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _fts_probe USING fts5(x)")
            fts5 = True
        except sqlite3.OperationalError:
            fts5 = False
        row = self.conn.execute("SELECT sqlite_version() AS version").fetchone()
        stats = self.conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM day_chunks WHERE deleted_at IS NULL) AS active_chunks,
                (SELECT COUNT(*) FROM forever_facts) AS forever_facts,
                (SELECT COUNT(*) FROM events) AS events,
                (SELECT COUNT(*) FROM event_traces) AS event_traces,
                (SELECT COUNT(*) FROM chat_sessions WHERE deleted_at IS NULL) AS chat_sessions,
                (SELECT COUNT(*) FROM chat_notes WHERE deleted_at IS NULL) AS chat_notes
            """
        ).fetchone()
        return {
            "db_path": str(self.db_path),
            "timezone": self.config.timezone,
            "sqlite_version": row["version"],
            "fts5": fts5,
            **_row_to_dict(stats),
        }

    def _format_event(self, event: dict[str, Any]) -> str:
        parts = [event["title"]]
        if event.get("start_at") or event.get("end_at"):
            parts.append(f"{event.get('start_at') or '?'} -> {event.get('end_at') or '?'}")
        parts.append(f"status={event.get('computed_status') or event.get('status')}")
        if event.get("summary"):
            parts.append(event["summary"])
        elif event.get("description"):
            parts.append(event["description"])
        return " | ".join(parts)

    def _fit_text(self, text: str, limit: int) -> tuple[str, bool]:
        if len(text) <= limit:
            return text, False
        if limit <= 100:
            return text[:limit], True
        marker = "\n\n[context truncated]\n"
        return text[: limit - len(marker)] + marker, True

    def day_stats(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT d.day, d.status, d.purge_started_at, d.deleted_at,
                   COUNT(c.id) AS total_chunks,
                   SUM(CASE WHEN c.deleted_at IS NULL THEN 1 ELSE 0 END) AS active_chunks,
                   COALESCE(SUM(CASE WHEN c.deleted_at IS NULL THEN LENGTH(c.text) ELSE 0 END), 0) AS active_chars
            FROM days d
            LEFT JOIN day_chunks c ON c.day = d.day
            GROUP BY d.day
            ORDER BY d.day
            """
        ).fetchall()
        return [_row_to_dict(row) for row in rows]
