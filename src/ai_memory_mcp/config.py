from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


APP_NAME = "ai-memory-mcp"
DEFAULT_HOME = Path("~/.ai_memory")


def _xdg_path(env_name: str, fallback: Path, *parts: str) -> Path:
    base = Path(os.environ.get(env_name, fallback)).expanduser()
    return base.joinpath(*parts)


def _can_write_parent(path: Path) -> bool:
    parent = path.expanduser().parent
    probe = parent / ".ai-memory-mcp-write-test"
    try:
        parent.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _with_local_fallback(primary: Path, fallback: Path) -> Path:
    primary = primary.expanduser()
    if _can_write_parent(primary):
        return primary
    return fallback.expanduser()


def default_db_path() -> Path:
    explicit = os.environ.get("HERMES_MEMORY_DB") or os.environ.get("AI_MEMORY_MCP_DB")
    if explicit:
        return Path(explicit).expanduser()
    return DEFAULT_HOME.expanduser() / "memory.sqlite3"


def default_config_path() -> Path:
    explicit = os.environ.get("HERMES_MEMORY_CONFIG") or os.environ.get("AI_MEMORY_MCP_CONFIG")
    if explicit:
        return Path(explicit).expanduser()
    return DEFAULT_HOME.expanduser() / "config.toml"


def default_state_dir() -> Path:
    return DEFAULT_HOME.expanduser() / "state"


def _read_toml(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    import tomllib

    with path.open("rb") as fh:
        data = tomllib.load(fh)
    return data if isinstance(data, dict) else {}


@dataclass(frozen=True)
class MemoryConfig:
    db_path: Path
    timezone: str = "UTC"
    exact_retention_days: int = 10
    detailed_retention_days: int = 10
    chat_retention_days: int = 10
    gradual_delete_chars: int = 20_000
    max_context_chars: int = 16_000
    max_search_items: int = 8
    auto_attach_active_events: bool = True

    @classmethod
    def load(cls, path: Path | None = None) -> "MemoryConfig":
        config_path = path or default_config_path()
        raw = _read_toml(config_path)
        db_path = Path(str(raw.get("db_path", default_db_path()))).expanduser()
        timezone = str(
            raw.get("timezone")
            or os.environ.get("HERMES_MEMORY_TIMEZONE")
            or os.environ.get("TZ")
            or "UTC"
        )
        return cls(
            db_path=db_path,
            timezone=timezone,
            exact_retention_days=int(raw.get("exact_retention_days", 10)),
            detailed_retention_days=int(raw.get("detailed_retention_days", 10)),
            chat_retention_days=int(raw.get("chat_retention_days", 10)),
            gradual_delete_chars=int(raw.get("gradual_delete_chars", 20_000)),
            max_context_chars=int(raw.get("max_context_chars", 16_000)),
            max_search_items=int(raw.get("max_search_items", 8)),
            auto_attach_active_events=bool(raw.get("auto_attach_active_events", True)),
        )

    def zoneinfo(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError:
            return ZoneInfo("UTC")


def write_default_config(path: Path | None = None, *, overwrite: bool = False) -> Path:
    config_path = path or default_config_path()
    if config_path.exists() and not overwrite:
        return config_path
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        "\n".join(
            [
                f'db_path = "{default_db_path()}"',
                'timezone = "UTC"',
                "exact_retention_days = 10",
                "detailed_retention_days = 10",
                "chat_retention_days = 10",
                "gradual_delete_chars = 20000",
                "max_context_chars = 16000",
                "max_search_items = 8",
                "auto_attach_active_events = true",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return config_path
