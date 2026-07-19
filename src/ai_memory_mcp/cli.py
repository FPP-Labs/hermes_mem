from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .config import MemoryConfig, default_config_path, write_default_config
from .server import run_server
from .store import MemoryStore


def _print(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))


def _config_from_args(args: argparse.Namespace) -> MemoryConfig:
    config_path = Path(args.config).expanduser() if getattr(args, "config", None) else default_config_path()
    config = MemoryConfig.load(config_path)
    if getattr(args, "db", None):
        config = MemoryConfig(
            db_path=Path(args.db).expanduser(),
            timezone=config.timezone,
            detailed_retention_days=config.detailed_retention_days,
            chat_retention_days=config.chat_retention_days,
            gradual_delete_chars=config.gradual_delete_chars,
            max_context_chars=config.max_context_chars,
            max_search_items=config.max_search_items,
            auto_attach_active_events=config.auto_attach_active_events,
        )
    return config


def _store(args: argparse.Namespace) -> MemoryStore:
    return MemoryStore(_config_from_args(args))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-memory-mcp", description="Hermes local memory MCP server")
    parser.add_argument("--config", help="Path to config TOML")
    parser.add_argument("--db", help="Path to SQLite database")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Create default config and database")
    init.add_argument("--overwrite", action="store_true")

    sub.add_parser("doctor", help="Show database and SQLite health")
    sub.add_parser("today", help="Print current memory date/time")

    serve = sub.add_parser("serve", help="Run MCP server")
    serve.add_argument("--transport", choices=["stdio", "sse", "streamable-http"], default="stdio")

    save = sub.add_parser("save-turn", help="Save one conversation turn")
    save.add_argument("--user", required=True)
    save.add_argument("--assistant", default="")
    save.add_argument("--detail", help="Detailed memory text; defaults to formatted turn")
    save.add_argument("--at")
    save.add_argument("--day")
    save.add_argument("--event-id", action="append", dest="event_ids")
    save.add_argument("--fact", action="append", dest="forever_facts")

    append = sub.add_parser("append-day", help="Append detailed text to a day")
    append.add_argument("text")
    append.add_argument("--day")
    append.add_argument("--at")
    append.add_argument("--role", default="memory")
    append.add_argument("--source", default="manual")
    append.add_argument("--event-id", action="append", dest="event_ids")
    append.add_argument("--no-rotate", action="store_true")

    context = sub.add_parser("context", help="Build prompt-ready context")
    context.add_argument("query", nargs="?", default="")
    context.add_argument("--at")
    context.add_argument("--max-chars", type=int)
    context.add_argument("--no-detailed", action="store_true")
    context.add_argument("--no-search", action="store_true")

    detailed = sub.add_parser("detailed", help="Show 10-day detailed memory")
    detailed.add_argument("--today")
    detailed.add_argument("--max-chars", type=int)

    rotate = sub.add_parser("rotate", help="Gradually rotate detailed memory")
    rotate.add_argument("--today")
    rotate.add_argument("--retention-days", type=int)
    rotate.add_argument("--delete-chars", type=int)

    fact = sub.add_parser("fact", help="Save a forever fact")
    fact.add_argument("text")
    fact.add_argument("--category", default="user")
    fact.add_argument("--importance", type=int, default=7)
    fact.add_argument("--unpinned", action="store_true")

    facts = sub.add_parser("facts", help="List forever facts")
    facts.add_argument("--limit", type=int, default=100)

    event = sub.add_parser("event-create", help="Create a permanent event")
    event.add_argument("title")
    event.add_argument("--type", default="event", dest="event_type")
    event.add_argument("--description", default="")
    event.add_argument("--start-at")
    event.add_argument("--end-at")
    event.add_argument("--duration-days", type=int)
    event.add_argument("--timezone")
    event.add_argument("--status")
    event.add_argument("--importance", type=int, default=6)
    event.add_argument("--summary", default="")
    event.add_argument("--no-auto-link", action="store_true")

    event_update = sub.add_parser("event-update", help="Update an event")
    event_update.add_argument("event_id")
    event_update.add_argument("--title")
    event_update.add_argument("--description")
    event_update.add_argument("--start-at")
    event_update.add_argument("--end-at")
    event_update.add_argument("--status")
    event_update.add_argument("--summary")
    event_update.add_argument("--importance", type=int)

    event_list = sub.add_parser("events", help="List events")
    event_list.add_argument("--status")
    event_list.add_argument("--limit", type=int, default=100)

    event_context = sub.add_parser("event-context", help="Show event memories")
    event_context.add_argument("event_id")
    event_context.add_argument("--query", default="")
    event_context.add_argument("--max-chars", type=int)

    chat = sub.add_parser("chat-upsert", help="Create or update a 10-day chat card")
    chat.add_argument("--chat-id")
    chat.add_argument("--title", default="")
    chat.add_argument("--alias", action="append", dest="aliases")
    chat.add_argument("--summary", default="")
    chat.add_argument("--status", default="active")
    chat.add_argument("--at")
    chat.add_argument("--event-id", action="append", dest="event_ids")

    chat_note = sub.add_parser("chat-note", help="Append a note to a 10-day chat card")
    chat_note.add_argument("text")
    chat_note.add_argument("--chat-id")
    chat_note.add_argument("--title", default="")
    chat_note.add_argument("--alias", action="append", dest="aliases")
    chat_note.add_argument("--summary", default="")
    chat_note.add_argument("--at")
    chat_note.add_argument("--type", default="progress", dest="note_type")
    chat_note.add_argument("--event-id", action="append", dest="event_ids")

    chat_context = sub.add_parser("chat-context", help="Show 10-day chat card context")
    chat_context.add_argument("--chat-id")
    chat_context.add_argument("--query", default="")
    chat_context.add_argument("--max-chars", type=int)

    chat_list = sub.add_parser("chats", help="List active 10-day chat cards")
    chat_list.add_argument("--limit", type=int, default=20)

    chat_link = sub.add_parser("chat-link-event", help="Link a chat card to an event")
    chat_link.add_argument("chat_id")
    chat_link.add_argument("event_id")
    chat_link.add_argument("--note", default="")

    chat_rotate = sub.add_parser("chat-rotate", help="Rotate expired 10-day chat cards")
    chat_rotate.add_argument("--at")
    chat_rotate.add_argument("--retention-days", type=int)

    search = sub.add_parser("search", help="Search memory")
    search.add_argument("query")
    search.add_argument("--limit", type=int)

    forget = sub.add_parser("forget", help="Forget one detailed memory chunk")
    forget.add_argument("memory_id")

    sub.add_parser("day-stats", help="Show rolling day stats")

    dashboard = sub.add_parser("dashboard", help="Show data for the Hermes Mem settings dashboard")
    dashboard.add_argument("--query", default="")
    dashboard.add_argument("--scope", choices=["all", "long-term", "10-day", "events"], default="all")
    dashboard.add_argument("--limit", type=int, default=40)

    clear_all = sub.add_parser("clear-all", help="Delete every Hermes Mem memory record")
    clear_all.add_argument("--confirm", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "init":
        config_path = Path(args.config).expanduser() if args.config else default_config_path()
        written = write_default_config(config_path, overwrite=args.overwrite)
        store = _store(args)
        _print({"config": str(written), "doctor": store.doctor()})
        return 0

    if args.command == "serve":
        run_server(_config_from_args(args), transport=args.transport)
        return 0

    store = _store(args)
    try:
        if args.command == "doctor":
            _print(store.doctor())
        elif args.command == "today":
            _print(store.get_today())
        elif args.command == "save-turn":
            _print(
                store.save_turn(
                    user_message=args.user,
                    assistant_message=args.assistant,
                    detailed_memory_text=args.detail,
                    at=args.at,
                    day=args.day,
                    event_ids=args.event_ids,
                    forever_facts=args.forever_facts,
                )
            )
        elif args.command == "append-day":
            _print(
                store.append_day_memory(
                    args.text,
                    day=args.day,
                    at=args.at,
                    role=args.role,
                    source=args.source,
                    event_ids=args.event_ids,
                    rotate=not args.no_rotate,
                )
            )
        elif args.command == "context":
            _print(
                store.get_context(
                    query=args.query,
                    at=args.at,
                    max_chars=args.max_chars,
                    include_detailed_memory=not args.no_detailed,
                    include_search=not args.no_search,
                )
            )
        elif args.command == "detailed":
            _print(store.get_10_day_detailed_memory(today=args.today, max_chars=args.max_chars))
        elif args.command == "rotate":
            _print(
                store.rotate_10_day_memory(
                    today=args.today,
                    retention_days=args.retention_days,
                    delete_chars=args.delete_chars,
                )
            )
        elif args.command == "fact":
            _print(
                store.save_forever_fact(
                    args.text,
                    category=args.category,
                    importance=args.importance,
                    pinned=not args.unpinned,
                )
            )
        elif args.command == "facts":
            _print(store.list_forever_facts(limit=args.limit))
        elif args.command == "event-create":
            _print(
                store.create_event(
                    title=args.title,
                    event_type=args.event_type,
                    description=args.description,
                    start_at=args.start_at,
                    end_at=args.end_at,
                    duration_days=args.duration_days,
                    timezone=args.timezone,
                    status=args.status,
                    importance=args.importance,
                    summary=args.summary,
                    auto_link_existing=not args.no_auto_link,
                )
            )
        elif args.command == "event-update":
            _print(
                store.update_event(
                    args.event_id,
                    title=args.title,
                    description=args.description,
                    start_at=args.start_at,
                    end_at=args.end_at,
                    status=args.status,
                    summary=args.summary,
                    importance=args.importance,
                )
            )
        elif args.command == "events":
            _print(store.list_events(status=args.status, limit=args.limit))
        elif args.command == "event-context":
            _print(store.get_event_context(args.event_id, query=args.query, max_chars=args.max_chars))
        elif args.command == "chat-upsert":
            _print(
                store.upsert_chat_session(
                    chat_id=args.chat_id,
                    title=args.title,
                    aliases=args.aliases,
                    summary=args.summary,
                    status=args.status,
                    at=args.at,
                    event_ids=args.event_ids,
                )
            )
        elif args.command == "chat-note":
            _print(
                store.append_chat_note(
                    args.chat_id,
                    args.text,
                    title=args.title,
                    aliases=args.aliases,
                    summary=args.summary,
                    at=args.at,
                    note_type=args.note_type,
                    event_ids=args.event_ids,
                )
            )
        elif args.command == "chat-context":
            _print(store.get_chat_context(chat_id=args.chat_id, query=args.query, max_chars=args.max_chars))
        elif args.command == "chats":
            _print(store.list_chat_sessions(limit=args.limit))
        elif args.command == "chat-link-event":
            _print(
                {
                    "linked": store.link_chat_to_event(args.chat_id, args.event_id, note=args.note, commit=True),
                    "chat_id": args.chat_id,
                    "event_id": args.event_id,
                }
            )
        elif args.command == "chat-rotate":
            _print(store.rotate_chat_memory(at=args.at, retention_days=args.retention_days))
        elif args.command == "search":
            _print(store.search(args.query, limit=args.limit))
        elif args.command == "forget":
            _print(store.forget_memory(args.memory_id))
        elif args.command == "day-stats":
            _print(store.day_stats())
        elif args.command == "dashboard":
            _print(store.memory_dashboard(query=args.query, scope=args.scope, limit=args.limit))
        elif args.command == "clear-all":
            _print(store.clear_all_memory(confirmation=args.confirm))
        else:
            parser.error(f"unknown command: {args.command}")
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
