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


PLAN_EVENT_TYPES = {"plan", "intent", "intention"}
UNSCHEDULED_EVENT_TYPES = PLAN_EVENT_TYPES | {"idea", "possibility"}
LIFECYCLE_EVENT_STATUSES = {"planned", "in_progress", "completed", "cancelled", "unknown"}
OPEN_EVENT_STATUSES = {"planned", "upcoming", "in_progress", "active", "unknown"}


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


def _importance(value: Any, default: int = 5) -> int:
    try:
        return max(0, min(int(value), 10))
    except (TypeError, ValueError):
        return default


class MemoryStore:
    """SQLite storage for Hermes memory.

    The store has five durable layers:
    - an automatic verbatim turn archive for the first N days;
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
                exact_retention_days=config.exact_retention_days,
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

            CREATE TABLE IF NOT EXISTS exact_turns (
                id TEXT PRIMARY KEY,
                external_turn_id TEXT NOT NULL UNIQUE,
                session_id TEXT NOT NULL DEFAULT '',
                task_id TEXT NOT NULL DEFAULT '',
                user_message TEXT NOT NULL,
                assistant_message TEXT NOT NULL,
                user_created_at TEXT NOT NULL,
                assistant_created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                review_status TEXT NOT NULL DEFAULT 'pending',
                reviewed_at TEXT,
                deleted_at TEXT,
                model TEXT NOT NULL DEFAULT '',
                platform TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE INDEX IF NOT EXISTS idx_exact_turns_session_time
                ON exact_turns(session_id, assistant_created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_exact_turns_expiry
                ON exact_turns(expires_at, review_status, deleted_at);

            CREATE TABLE IF NOT EXISTS turn_consolidations (
                id TEXT PRIMARY KEY,
                exact_turn_id TEXT NOT NULL UNIQUE,
                summary TEXT NOT NULL,
                memory_kind TEXT NOT NULL DEFAULT 'observation',
                memory_status TEXT NOT NULL DEFAULT 'unknown',
                importance INTEGER NOT NULL DEFAULT 5,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY(exact_turn_id) REFERENCES exact_turns(id)
            );

            CREATE INDEX IF NOT EXISTS idx_turn_consolidations_importance
                ON turn_consolidations(importance DESC, updated_at DESC);

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
            "CREATE VIRTUAL TABLE IF NOT EXISTS exact_turns_fts USING "
            "fts5(id UNINDEXED, user_message, assistant_message)"
        )
        self.conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS turn_consolidations_fts USING "
            "fts5(id UNINDEXED, summary)"
        )
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

    def archive_exact_turn(
        self,
        *,
        external_turn_id: str,
        user_message: str,
        assistant_message: str,
        session_id: str = "",
        task_id: str = "",
        user_created_at: str | None = None,
        assistant_created_at: str | None = None,
        model: str = "",
        platform: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Idempotently archive the exact visible text of one completed turn."""
        external_id = external_turn_id.strip()
        if not external_id:
            raise ValueError("external_turn_id must not be empty")
        user_text = str(user_message)
        assistant_text = str(assistant_message)
        if not user_text.strip() and not assistant_text.strip():
            raise ValueError("user_message or assistant_message must not be empty")
        existing = self.conn.execute(
            "SELECT * FROM exact_turns WHERE external_turn_id = ?",
            (external_id,),
        ).fetchone()
        if existing:
            payload = self._exact_turn_payload(existing)
            payload["duplicate"] = True
            return payload

        assistant_dt = parse_datetime(assistant_created_at, self.zone) or now_in(self.zone)
        user_dt = parse_datetime(user_created_at, self.zone) or assistant_dt
        assistant_iso = assistant_dt.isoformat(timespec="seconds")
        user_iso = user_dt.isoformat(timespec="seconds")
        expires_at = (assistant_dt + timedelta(days=self.config.exact_retention_days)).isoformat(
            timespec="seconds"
        )
        exact_id = _id("exact")
        self.conn.execute(
            """
            INSERT INTO exact_turns (
                id, external_turn_id, session_id, task_id, user_message,
                assistant_message, user_created_at, assistant_created_at,
                expires_at, model, platform, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                exact_id,
                external_id,
                session_id.strip(),
                task_id.strip(),
                user_text,
                assistant_text,
                user_iso,
                assistant_iso,
                expires_at,
                model.strip(),
                platform.strip(),
                _json(metadata),
            ),
        )
        self.conn.execute(
            """
            INSERT INTO exact_turns_fts (id, user_message, assistant_message)
            VALUES (?, ?, ?)
            """,
            (exact_id, user_text, assistant_text),
        )
        rotation = self.rotate_exact_turns(at=assistant_iso, commit=False)
        self.log_operation(
            "archive_exact_turn",
            {"exact_turn_id": exact_id, "external_turn_id": external_id},
        )
        self.conn.commit()
        payload = self.get_exact_turn(exact_id)
        payload["duplicate"] = False
        payload["rotation"] = rotation
        return payload

    def get_exact_turn(self, exact_turn_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM exact_turns WHERE id = ?",
            (exact_turn_id,),
        ).fetchone()
        if not row:
            raise KeyError(f"exact turn not found: {exact_turn_id}")
        return self._exact_turn_payload(row)

    def _exact_turn_payload(self, row: sqlite3.Row) -> dict[str, Any]:
        payload = _row_to_dict(row)
        payload["metadata"] = _loads(payload.pop("metadata_json", "{}"))
        return payload

    def list_exact_turns(
        self,
        *,
        session_id: str | None = None,
        limit: int = 100,
        include_expired_pending: bool = True,
    ) -> list[dict[str, Any]]:
        clauses = ["deleted_at IS NULL"]
        values: list[Any] = []
        if session_id is not None:
            clauses.append("session_id = ?")
            values.append(session_id)
        if not include_expired_pending:
            clauses.append("expires_at >= ?")
            values.append(iso_now(self.zone))
        values.append(max(1, min(int(limit), 500)))
        rows = self.conn.execute(
            f"""
            SELECT * FROM exact_turns
            WHERE {' AND '.join(clauses)}
            ORDER BY assistant_created_at DESC
            LIMIT ?
            """,
            values,
        ).fetchall()
        return [self._exact_turn_payload(row) for row in rows]

    def rotate_exact_turns(
        self,
        *,
        at: str | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Delete expired verbatim text only after its semantic review succeeded."""
        cutoff = (parse_datetime(at, self.zone) or now_in(self.zone)).isoformat(timespec="seconds")
        rows = self.conn.execute(
            """
            SELECT id FROM exact_turns
            WHERE deleted_at IS NULL
              AND expires_at < ?
              AND review_status IN ('reviewed', 'skipped')
            """,
            (cutoff,),
        ).fetchall()
        ids = [row["id"] for row in rows]
        now = iso_now(self.zone)
        for exact_id in ids:
            self.conn.execute(
                """
                UPDATE exact_turns
                SET user_message = '', assistant_message = '', deleted_at = ?
                WHERE id = ?
                """,
                (now, exact_id),
            )
            self.conn.execute("DELETE FROM exact_turns_fts WHERE id = ?", (exact_id,))
        pending = self.conn.execute(
            """
            SELECT COUNT(*) AS count FROM exact_turns
            WHERE deleted_at IS NULL AND expires_at < ? AND review_status = 'pending'
            """,
            (cutoff,),
        ).fetchone()
        if ids:
            self.log_operation("rotate_exact_turns", {"ids": ids, "cutoff": cutoff})
        if commit:
            self.conn.commit()
        return {
            "deleted_count": len(ids),
            "deleted_ids": ids,
            "expired_pending_review_count": int(pending["count"]),
        }

    def apply_turn_review(
        self,
        *,
        exact_turn_id: str,
        summary: str = "",
        keep_long_term: bool = False,
        memory_kind: str = "observation",
        memory_status: str = "unknown",
        importance: int = 5,
        facts: list[dict[str, Any]] | None = None,
        events: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Apply one model-produced semantic review to an exact source turn."""
        source = self.get_exact_turn(exact_turn_id)
        if source["review_status"] in {"reviewed", "skipped"}:
            return {
                "exact_turn_id": exact_turn_id,
                "duplicate": True,
                "review_status": source["review_status"],
            }
        now = iso_now(self.zone)
        safe_importance = _importance(importance)
        clean_summary = str(summary or "").strip()
        keep = keep_long_term is True or str(keep_long_term).strip().lower() in {
            "1",
            "true",
            "yes",
        }
        safe_metadata = metadata if isinstance(metadata, dict) else {}
        safe_kind = str(memory_kind or "observation").strip() or "observation"
        safe_status = str(memory_status or "unknown").strip() or "unknown"
        consolidation_id = None
        fact_results: list[dict[str, Any]] = []
        event_results: list[dict[str, Any]] = []

        if keep and clean_summary:
            consolidation_id = _id("summary")
            self.conn.execute(
                """
                INSERT INTO turn_consolidations (
                    id, exact_turn_id, summary, memory_kind, memory_status,
                    importance, created_at, updated_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    consolidation_id,
                    exact_turn_id,
                    clean_summary,
                    safe_kind,
                    safe_status,
                    safe_importance,
                    now,
                    now,
                    _json({"source_exact_turn_id": exact_turn_id, **safe_metadata}),
                ),
            )
            self.conn.execute(
                "INSERT INTO turn_consolidations_fts (id, summary) VALUES (?, ?)",
                (consolidation_id, clean_summary),
            )

            for item in facts or []:
                if not isinstance(item, dict) or not str(item.get("text") or "").strip():
                    continue
                try:
                    saved_fact = self.save_forever_fact(
                        str(item["text"]),
                        category=str(item.get("category") or "user"),
                        importance=_importance(item.get("importance"), safe_importance),
                        source="automatic_turn_review",
                        metadata={"source_exact_turn_id": exact_turn_id},
                    )
                except (TypeError, ValueError):
                    continue
                fact_results.append(saved_fact)

            for item in events or []:
                if not isinstance(item, dict) or not str(item.get("title") or "").strip():
                    continue
                event_title = str(item["title"]).strip()
                event_type = str(item.get("event_type") or "event").strip() or "event"
                event_importance = _importance(item.get("importance"), safe_importance)
                try:
                    existing_event = self.find_matching_event(event_title, event_type)
                    if existing_event:
                        requested_status = str(item.get("status") or "").strip() or None
                        if existing_event["status"] in {"completed", "cancelled"}:
                            requested_status = existing_event["status"]
                        saved_event = self.update_event(
                            existing_event["id"],
                            description=str(item.get("description") or "").strip() or None,
                            start_at=item.get("start_at") or None,
                            end_at=item.get("end_at") or None,
                            status=requested_status,
                            summary=str(item.get("summary") or "").strip() or None,
                            importance=max(int(existing_event["importance"]), event_importance),
                        )
                        saved_event["duplicate"] = True
                    else:
                        saved_event = self.create_event(
                            title=event_title,
                            event_type=event_type,
                            description=str(item.get("description") or ""),
                            start_at=item.get("start_at"),
                            end_at=item.get("end_at"),
                            status=str(item.get("status") or "") or None,
                            importance=event_importance,
                            summary=str(item.get("summary") or ""),
                            metadata={"source_exact_turn_id": exact_turn_id},
                            auto_link_existing=False,
                        )
                        saved_event["duplicate"] = False
                    self.link_memory_to_event(
                        saved_event["id"],
                        "exact_turn",
                        exact_turn_id,
                        day=parse_day(source["assistant_created_at"], self.zone),
                        note="automatic semantic review source",
                        commit=False,
                    )
                except (TypeError, ValueError):
                    continue
                event_results.append(saved_event)

        review_status = "reviewed" if keep and clean_summary else "skipped"
        self.conn.execute(
            """
            UPDATE exact_turns
            SET review_status = ?, reviewed_at = ?
            WHERE id = ?
            """,
            (review_status, now, exact_turn_id),
        )
        self.log_operation(
            "apply_turn_review",
            {
                "exact_turn_id": exact_turn_id,
                "review_status": review_status,
                "consolidation_id": consolidation_id,
            },
        )
        rotation = self.rotate_exact_turns(commit=False)
        self.conn.commit()
        return {
            "exact_turn_id": exact_turn_id,
            "duplicate": False,
            "review_status": review_status,
            "consolidation_id": consolidation_id,
            "facts": fact_results,
            "events": event_results,
            "rotation": rotation,
        }

    def list_turn_consolidations(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT * FROM turn_consolidations
            ORDER BY importance DESC, updated_at DESC
            LIMIT ?
            """,
            (max(1, min(int(limit), 500)),),
        ).fetchall()
        payloads = []
        for row in rows:
            payload = _row_to_dict(row)
            payload["metadata"] = _loads(payload.pop("metadata_json", "{}"))
            payloads.append(payload)
        return payloads

    def _format_timestamp(self, value: str | None) -> str:
        parsed = parse_datetime(value, self.zone)
        if parsed is None:
            return f"time unknown ({self.config.timezone})"
        return f"{parsed.strftime('%d.%m.%Y %H:%M:%S')} {self.config.timezone}"

    def _format_memory_marker(
        self,
        value: str | None,
        *,
        memory_kind: str | None = None,
        memory_status: str | None = None,
    ) -> str:
        parts = [self._format_timestamp(value)]
        if memory_kind:
            parts.append(f"kind={memory_kind}")
        if memory_status:
            parts.append(f"status={memory_status}")
        return " | ".join(parts)

    def _format_search_result(self, item: dict[str, Any]) -> str:
        timestamp = item.get("created_at") or item.get("updated_at") or item.get("start_at")
        marker = self._format_memory_marker(
            timestamp,
            memory_kind=item.get("memory_kind"),
            memory_status=item.get("memory_status"),
        )
        if item.get("type") == "exact_turn":
            user_marker = self._format_timestamp(item.get("user_created_at"))
            return (
                f"[exact verbatim turn | source={item['id']}]\n"
                f"  User exact quote [{user_marker}]: {item.get('user_quote') or '(empty)'}\n"
                f"  Hermes exact quote [{marker}]: {item.get('assistant_quote') or '(empty)'}"
            )
        return f"[{item['type']} | {marker}] {item['text']}"

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
            parts.append(f"User: {user_message.strip()}")
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
        existing = next(
            (
                row
                for row in self.conn.execute("SELECT * FROM forever_facts").fetchall()
                if str(row["fact"]).strip().casefold() == cleaned.casefold()
            ),
            None,
        )
        if existing:
            existing_metadata = _loads(existing["metadata_json"])
            new_metadata = metadata if isinstance(metadata, dict) else {}
            merged_metadata = {**existing_metadata, **new_metadata}
            safe_importance = max(int(existing["importance"]), _importance(importance, 7))
            self.conn.execute(
                """
                UPDATE forever_facts
                SET category = ?, importance = ?, pinned = ?, updated_at = ?,
                    metadata_json = ?
                WHERE id = ?
                """,
                (
                    category,
                    safe_importance,
                    1 if pinned or bool(existing["pinned"]) else 0,
                    now,
                    _json(merged_metadata),
                    existing["id"],
                ),
            )
            self.conn.commit()
            payload = self._fact_payload(
                self.conn.execute(
                    "SELECT * FROM forever_facts WHERE id = ?",
                    (existing["id"],),
                ).fetchone()
            )
            payload["duplicate"] = True
            return payload
        fact_id = _id("fact")
        self.conn.execute(
            """
            INSERT INTO forever_facts
                (id, fact, category, importance, pinned, created_at, updated_at, source, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fact_id,
                cleaned,
                category,
                _importance(importance, 7),
                1 if pinned else 0,
                now,
                now,
                source,
                _json(metadata),
            ),
        )
        self.conn.execute("INSERT INTO forever_facts_fts (id, fact) VALUES (?, ?)", (fact_id, cleaned))
        self.conn.commit()
        return {
            "id": fact_id,
            "fact": cleaned,
            "category": category,
            "importance": _importance(importance, 7),
            "pinned": pinned,
            "duplicate": False,
        }

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
        normalized_type = event_type.strip().lower() or "event"
        normalized_status = status.strip().lower() if status and status.strip() else None
        is_undated_plan = not start_at and (
            normalized_type in UNSCHEDULED_EVENT_TYPES or normalized_status in {"planned", "unknown"}
        )
        if start_at:
            start_iso = parse_datetime(start_at, zone).isoformat(timespec="seconds")
        elif is_undated_plan:
            start_iso = None
        else:
            start_iso = now
        end_iso = parse_datetime(end_at, zone).isoformat(timespec="seconds") if end_at else None
        if duration_days is not None and not end_iso and start_iso:
            end_iso = end_after_days(start_iso, int(duration_days), zone)
        if normalized_status:
            stored_status = normalized_status
        elif normalized_type in PLAN_EVENT_TYPES:
            stored_status = "planned"
        elif normalized_type in {"idea", "possibility"}:
            stored_status = "unknown"
        else:
            stored_status = event_status(start_iso, end_iso, zone)
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
                normalized_type,
                description.strip(),
                start_iso,
                end_iso,
                tz,
                stored_status,
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

    def find_matching_event(self, title: str, event_type: str) -> dict[str, Any] | None:
        normalized_title = title.strip().casefold()
        normalized_type = event_type.strip().casefold() or "event"
        if not normalized_title:
            return None
        for row in self.conn.execute("SELECT * FROM events ORDER BY updated_at DESC").fetchall():
            if (
                str(row["title"]).strip().casefold() == normalized_title
                and str(row["event_type"]).strip().casefold() == normalized_type
            ):
                return self._event_payload(row)
        return None

    def _event_payload(self, row: sqlite3.Row) -> dict[str, Any]:
        payload = _row_to_dict(row)
        payload["metadata"] = _loads(payload.pop("metadata_json", "{}"))
        temporal_status = event_status(payload.get("start_at"), payload.get("end_at"), self.zone)
        lifecycle_status = str(payload.get("status") or "").strip().lower()
        payload["temporal_status"] = temporal_status
        payload["computed_status"] = (
            lifecycle_status if lifecycle_status in LIFECYCLE_EVENT_STATUSES else temporal_status
        )
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
            temporal_status = event_status(payload.get("start_at"), payload.get("end_at"), self.zone, at=current)
            lifecycle_status = str(payload.get("status") or "").strip().lower()
            if lifecycle_status == "in_progress" or (
                lifecycle_status not in {"planned", "completed", "cancelled", "unknown"}
                and temporal_status == "active"
            ):
                active.append(payload)
        return active

    def open_events(self, *, at: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        current = parse_datetime(at, self.zone) if at else now_in(self.zone)
        rows = self.conn.execute(
            "SELECT * FROM events ORDER BY importance DESC, created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        open_items = []
        for row in rows:
            payload = self._event_payload(row)
            lifecycle_status = str(payload.get("status") or "").strip().lower()
            temporal_status = event_status(payload.get("start_at"), payload.get("end_at"), self.zone, at=current)
            effective_status = (
                lifecycle_status if lifecycle_status in LIFECYCLE_EVENT_STATUSES else temporal_status
            )
            payload["temporal_status"] = temporal_status
            payload["computed_status"] = effective_status
            if effective_status in OPEN_EVENT_STATUSES:
                open_items.append(payload)
        return open_items

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
            parts.append(f"Chat: {title}")
            if aliases:
                parts.append(f"Aliases: {aliases}")
            if session.get("summary"):
                parts.append(f"Summary: {session['summary']}")
        if events:
            parts.append("Linked events:\n" + "\n".join(f"- {self._format_event(event)}" for event in events))
        if notes:
            parts.append(
                "Chat notes:\n"
                + "\n".join(
                    f"- [{self._format_timestamp(note.get('created_at'))}] {note['text']}"
                    for note in notes
                )
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
                    "created_at": note.get("created_at"),
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
            SELECT l.*, c.text, c.deleted_at, c.created_at AS memory_created_at
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
                    "created_at": row["memory_created_at"] or row["created_at"],
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
            text_parts.append("Linked detailed event memories:")
            for memory in memories:
                text_parts.append(
                    f"- [{self._format_timestamp(memory.get('created_at'))}] {memory['text']}"
                )
        if traces:
            text_parts.append("Short traces of removed detailed event memory:")
            for trace in traces:
                text_parts.append(
                    f"- [{self._format_timestamp(trace.get('created_at'))}] {trace['text']}"
                )
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
                    SELECT id, day, text, role, source, turn_id, order_index, created_at, metadata_json
                    FROM day_chunks
                    WHERE day = ? AND deleted_at IS NULL
                    ORDER BY order_index
                    """,
                    (day,),
                ).fetchall()
            ]
            day_entries = []
            for chunk in chunks:
                metadata = _loads(chunk.pop("metadata_json", "{}"))
                chunk["metadata"] = metadata
                marker = self._format_memory_marker(
                    chunk.get("created_at"),
                    memory_kind=metadata.get("memory_kind"),
                    memory_status=metadata.get("memory_status"),
                )
                day_entries.append(f"[{marker}]\n{chunk['text']}")
            day_text = "\n\n".join(day_entries)
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
        open_events = self.open_events(at=current_at)
        facts = self.list_forever_facts(limit=50)
        consolidations = self.list_turn_consolidations(limit=30)
        detailed_budget = max(2_000, limit_chars // 2)
        detailed = self.get_10_day_detailed_memory(today=parse_day(current_at, self.zone), max_chars=detailed_budget)
        search_results = self.search(query, limit=self.config.max_search_items) if query and include_search else []

        sections = [f"Current local time: {today['human']} ({today['timezone']})."]
        if query and search_results:
            search_budget = max(800, min(5_000, limit_chars // 3))
            rendered_results: list[str] = []
            rendered_chars = 0
            for item in search_results:
                rendered = self._format_search_result(item)
                if len(rendered) > search_budget - rendered_chars:
                    if item.get("type") == "exact_turn":
                        continue
                    rendered = self._trace_text(rendered, limit=max(100, search_budget - rendered_chars))
                if not rendered or rendered_chars + len(rendered) > search_budget:
                    break
                rendered_results.append("- " + rendered)
                rendered_chars += len(rendered) + 2
            if rendered_results:
                sections.append(
                    "Relevant memory search results. Only entries marked 'exact verbatim turn' "
                    "may be presented as direct quotes:\n"
                    + "\n".join(rendered_results)
                )

        search_exact_ids = {
            str(item.get("id"))
            for item in search_results
            if item.get("type") == "exact_turn"
        }
        recent_budget = max(600, min(3_500, limit_chars // 4))
        recent_lines: list[str] = []
        recent_chars = 0
        for item in self.recent_exact_quotes(limit=3):
            if item["id"] in search_exact_ids:
                continue
            rendered = self._format_search_result(item)
            if len(rendered) > recent_budget - recent_chars:
                continue
            recent_lines.append("- " + rendered)
            recent_chars += len(rendered) + 2
        if recent_lines:
            sections.append(
                "Most recent complete verbatim turns (10-day short-term memory):\n"
                + "\n".join(recent_lines)
            )

        if facts:
            sections.append(
                "Permanent user facts:\n"
                + "\n".join(
                    f"- [{self._format_timestamp(fact.get('updated_at') or fact.get('created_at'))}] "
                    f"{fact['fact']}"
                    for fact in facts
                )
            )
        if consolidations:
            sections.append(
                "Long-term schematic memory (summaries, never verbatim quotes):\n"
                + "\n".join(
                    f"- [{self._format_memory_marker(item.get('updated_at'), memory_kind=item.get('memory_kind'), memory_status=item.get('memory_status'))}] "
                    f"{item['summary']}"
                    for item in consolidations
                )
            )
        if open_events:
            sections.append(
                "Current events and unresolved plans:\n"
                + "\n".join(f"- {self._format_event(event)}" for event in open_events)
            )
        if include_detailed_memory and detailed["context_text"]:
            sections.append("Detailed 10-day memory:\n" + detailed["context_text"])
        context_text, truncated = self._fit_text("\n\n".join(sections), limit_chars)
        return {
            "today": today,
            "forever_fact_count": len(facts),
            "long_term_summary_count": len(consolidations),
            "active_event_count": len(active_events),
            "open_event_count": len(open_events),
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
                    "created_at": item.get("created_at") or item.get("updated_at"),
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
        results.extend(self._search_exact_turns(fts, max_items))
        results.extend(self._search_turn_consolidations(fts, max_items))
        results.extend(self._search_chat_sessions(fts, max_items))
        results.extend(self._search_chat_notes(fts, max_items))
        results.extend(self._search_day_chunks(fts, max_items))
        results.extend(self._search_facts(fts, max_items))
        results.extend(self._search_events(fts, max_items))
        results.extend(self._search_event_traces(fts, max_items))
        return results[:max_items]

    def search_exact_quotes(self, query: str, *, limit: int = 8) -> list[dict[str, Any]]:
        """Search only active verbatim turns that are safe to quote directly."""
        cleaned = query.strip()
        if not cleaned:
            return []
        fts = _fts_query(cleaned)
        if not fts:
            return []
        return self._search_exact_turns(fts, max(1, min(int(limit), 100)))

    def recent_exact_quotes(self, *, limit: int = 3) -> list[dict[str, Any]]:
        """Return the most recent active complete turns as quote-safe records."""
        rows = self.list_exact_turns(
            limit=max(1, min(int(limit), 20)),
            include_expired_pending=False,
        )
        return [
            {
                "type": "exact_turn",
                "id": row["id"],
                "external_turn_id": row["external_turn_id"],
                "session_id": row["session_id"],
                "text": "\n".join(
                    [
                        f"User: {row['user_message']}",
                        f"Hermes: {row['assistant_message']}",
                    ]
                ),
                "user_quote": row["user_message"],
                "assistant_quote": row["assistant_message"],
                "created_at": row["assistant_created_at"],
                "user_created_at": row["user_created_at"],
                "expires_at": row["expires_at"],
                "verbatim": True,
            }
            for row in rows
        ]

    def memory_dashboard(
        self,
        *,
        query: str = "",
        scope: str = "all",
        limit: int = 40,
    ) -> dict[str, Any]:
        normalized_scope = scope.strip().lower().replace("_", "-")
        if normalized_scope not in {"all", "long-term", "10-day", "events"}:
            raise ValueError("scope must be all, long-term, 10-day, or events")
        safe_limit = max(1, min(int(limit), 100))
        today = self.get_today()
        detailed = self.get_10_day_detailed_memory(today=today["date"], max_chars=200_000)
        today_memory = next((day for day in detailed["days"] if day["day"] == today["date"]), None)
        results = self.search(query, limit=100) if query.strip() else []
        long_term_types = {"forever_fact", "turn_consolidation"}
        ten_day_types = {"exact_turn", "day_chunk", "chat_session", "chat_note"}
        event_types = {"event", "event_trace"}
        if normalized_scope == "long-term":
            results = [item for item in results if item.get("type") in long_term_types]
        elif normalized_scope == "10-day":
            results = [item for item in results if item.get("type") in ten_day_types]
        elif normalized_scope == "events":
            results = [item for item in results if item.get("type") in event_types]
        return {
            "today": today,
            "today_memory": today_memory or {"day": today["date"], "chunks": [], "chars": 0},
            "ten_day_memory": detailed["days"],
            "exact_turns": self.list_exact_turns(limit=100, include_expired_pending=False),
            "long_term_summaries": self.list_turn_consolidations(limit=100),
            "forever_facts": self.list_forever_facts(limit=100),
            "active_events": self.active_events(at=today["now"]),
            "search": {
                "query": query,
                "scope": normalized_scope,
                "results": results[:safe_limit],
            },
            "health": self.doctor(),
        }

    def clear_all_memory(self, *, confirmation: str) -> dict[str, Any]:
        if confirmation != "DELETE_ALL_MEMORY":
            raise ValueError("confirmation must be DELETE_ALL_MEMORY")
        counts = self.doctor()
        self.conn.execute("PRAGMA secure_delete = ON")
        for table in (
            "event_memory_links",
            "event_traces_fts",
            "event_traces",
            "chat_event_links",
            "chat_notes_fts",
            "chat_notes",
            "chat_sessions_fts",
            "chat_sessions",
            "day_chunks_fts",
            "day_chunks",
            "turns",
            "days",
            "turn_consolidations_fts",
            "turn_consolidations",
            "exact_turns_fts",
            "exact_turns",
            "forever_facts_fts",
            "forever_facts",
            "events_fts",
            "events",
            "operations",
        ):
            self.conn.execute(f"DELETE FROM {table}")
        self.conn.commit()
        return {
            "deleted": True,
            "previous_counts": {
                key: counts[key]
                for key in (
                    "active_chunks",
                    "exact_turns",
                    "pending_turn_reviews",
                    "long_term_summaries",
                    "forever_facts",
                    "events",
                    "event_traces",
                    "chat_sessions",
                    "chat_notes",
                )
            },
        }

    def _search_exact_turns(self, fts_query: str, limit: int) -> list[dict[str, Any]]:
        try:
            rows = self.conn.execute(
                """
                SELECT t.id, t.external_turn_id, t.session_id, t.user_message,
                       t.assistant_message, t.user_created_at, t.assistant_created_at,
                       t.expires_at
                FROM exact_turns_fts
                JOIN exact_turns t ON t.id = exact_turns_fts.id
                WHERE exact_turns_fts MATCH ?
                  AND t.deleted_at IS NULL
                  AND t.expires_at >= ?
                ORDER BY bm25(exact_turns_fts)
                LIMIT ?
                """,
                (fts_query, iso_now(self.zone), limit),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [
            {
                "type": "exact_turn",
                "id": row["id"],
                "external_turn_id": row["external_turn_id"],
                "session_id": row["session_id"],
                "text": "\n".join(
                    [
                        f"User: {row['user_message']}",
                        f"Hermes: {row['assistant_message']}",
                    ]
                ),
                "user_quote": row["user_message"],
                "assistant_quote": row["assistant_message"],
                "created_at": row["assistant_created_at"],
                "user_created_at": row["user_created_at"],
                "expires_at": row["expires_at"],
                "verbatim": True,
            }
            for row in rows
        ]

    def _search_turn_consolidations(self, fts_query: str, limit: int) -> list[dict[str, Any]]:
        try:
            rows = self.conn.execute(
                """
                SELECT c.*
                FROM turn_consolidations_fts
                JOIN turn_consolidations c ON c.id = turn_consolidations_fts.id
                WHERE turn_consolidations_fts MATCH ?
                ORDER BY bm25(turn_consolidations_fts)
                LIMIT ?
                """,
                (fts_query, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [
            {
                "type": "turn_consolidation",
                "id": row["id"],
                "exact_turn_id": row["exact_turn_id"],
                "text": row["summary"],
                "memory_kind": row["memory_kind"],
                "memory_status": row["memory_status"],
                "importance": row["importance"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "verbatim": False,
            }
            for row in rows
        ]

    def _search_day_chunks(self, fts_query: str, limit: int) -> list[dict[str, Any]]:
        try:
            rows = self.conn.execute(
                """
                SELECT c.id, c.day, c.text, c.created_at, c.metadata_json
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
        results = []
        for row in rows:
            metadata = _loads(row["metadata_json"])
            results.append(
                {
                    "type": "day_chunk",
                    "id": row["id"],
                    "day": row["day"],
                    "text": row["text"],
                    "created_at": row["created_at"],
                    "memory_kind": metadata.get("memory_kind"),
                    "memory_status": metadata.get("memory_status"),
                }
            )
        return results

    def _search_facts(self, fts_query: str, limit: int) -> list[dict[str, Any]]:
        try:
            rows = self.conn.execute(
                """
                SELECT f.id, f.fact, f.category, f.importance, f.created_at, f.updated_at
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
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
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
                "created_at": row["created_at"],
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
                (SELECT COUNT(*) FROM exact_turns WHERE deleted_at IS NULL) AS exact_turns,
                (SELECT COUNT(*) FROM exact_turns WHERE deleted_at IS NULL AND review_status = 'pending') AS pending_turn_reviews,
                (SELECT COUNT(*) FROM turn_consolidations) AS long_term_summaries,
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
        parts = [
            event["title"],
            f"type={event.get('event_type') or 'event'}",
            f"recorded={self._format_timestamp(event.get('created_at'))}",
        ]
        if event.get("start_at") or event.get("end_at"):
            parts.append(f"{event.get('start_at') or '?'} -> {event.get('end_at') or '?'}")
        else:
            parts.append("schedule=unknown")
        parts.append(f"status={event.get('computed_status') or event.get('status')}")
        temporal_status = event.get("temporal_status")
        if temporal_status and temporal_status != event.get("computed_status"):
            parts.append(f"temporal_status={temporal_status}")
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
