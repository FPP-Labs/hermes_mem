#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${AI_MEMORY_HOME:-"$HOME/.ai_memory"}"
SRC_DIR="${AI_MEMORY_SOURCE:-"$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"}"
CODE_DIR="$APP_DIR/mcp"
VENV_DIR="$APP_DIR/venv"
CONFIG_PATH="$APP_DIR/config.toml"
DB_PATH="$APP_DIR/memory.sqlite3"
SERVER_NAME="${AI_MEMORY_MCP_NAME:-hermes-memory}"
HERMES_HOME="${HERMES_HOME:-"$HOME/.hermes"}"
HERMES_ROOT="${HERMES_ROOT:-"$HERMES_HOME/hermes-agent"}"
DEFAULT_ELEVENLABS_MODEL_ID="${ELEVENLABS_MODEL_ID:-eleven_multilingual_v2}"
ARG_COUNT="$#"

OS_NAME="${AI_MEMORY_PLATFORM:-$(uname -s)}"
case "$OS_NAME" in
  Darwin) PLATFORM="macos" ;;
  Linux) PLATFORM="linux" ;;
  *)
    printf 'ERROR: unsupported operating system: %s\n' "$OS_NAME" >&2
    exit 1
    ;;
esac

# A fresh official Hermes install writes its launchers and managed runtimes to
# these directories. Keep them available in this process without requiring a
# shell restart on Linux or macOS.
export PATH="$HOME/.local/bin:$HERMES_ROOT/venv/bin:$HERMES_HOME/node/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

MODE="install"
PACK_PATH=""
INSTALL_DEPS=1
INSTALL_HERMES=1
CONFIGURE_HERMES=1
DISABLE_HERMES_BUILTIN_MEMORY=1
CONFIGURE_ELEVENLABS=0
CONFIGURE_WEB_SEARCH=0
BACKUP_HERMES_CONFIG=1
APPLY_HERMES_DESKTOP_UI=1
BUILD_HERMES_DESKTOP_UI=1
WEB_SEARCH_ENABLED=0

usage() {
  cat <<EOF
Install Hermes FPP on Linux or macOS.

Usage:
  ./install.sh                       Install or update; keep memory
  ./install.sh update                Update/repair; keep memory
  ./install.sh doctor                Check Hermes FPP
  ./install.sh backup                Create a portable memory backup
  ./install.sh restore PATH          Restore a memory backup
  ./install.sh desktop               Rebuild and install FPP Desktop only
  ./install.sh reset-memory          Erase memory and reinstall FPP
  ./install.sh uninstall             Remove Hermes FPP and all user data

Advanced options:
  --no-deps                   Do not install missing Git/curl prerequisites
  --no-install-hermes         Do not install Hermes Agent
  --no-hermes                 Do not configure Hermes MCP
  --keep-hermes-builtin-memory
                              Keep Hermes built-in MEMORY.md/USER.md enabled
  --configure-web-search      Configure web search in the terminal
  --configure-elevenlabs      Configure ElevenLabs in the terminal
  --no-hermes-config-backup   Do not back up current Hermes config files
  --no-desktop-ui             Do not patch Hermes Desktop UI
  --no-desktop-ui-build       Patch Desktop source but do not rebuild the launchable app
  -h, --help                  Show this help

Environment:
  AI_MEMORY_HOME=/path        Default: ~/.ai_memory
  AI_MEMORY_MCP_NAME=name     Default: hermes-memory
  ELEVENLABS_API_KEY=key      Non-interactive ElevenLabs key
  ELEVENLABS_VOICE_ID=id      Non-interactive ElevenLabs voice id
  ELEVENLABS_MODEL_ID=id      Default: eleven_multilingual_v2
  WEB_SEARCH_API_KEY=key      Non-interactive web search key
  WEB_SEARCH_PROVIDER=name    tavily, exa, parallel, firecrawl, or brave
  SEARXNG_URL=url             Non-interactive local/self-hosted SearXNG URL
  HERMES_ROOT=/path           Default: ~/.hermes/hermes-agent
  HERMES_MCP_ADD_TIMEOUT_SECONDS=seconds
                              Default: 180; timeout for Hermes MCP validation
  AI_MEMORY_UNINSTALL_CONFIRM=DELETE
                              Confirm uninstall/reset in a non-interactive shell

Notes:
  Normal install and update always preserve memory. Optional web-search and
  ElevenLabs keys can be configured later in Hermes/FPP settings.

Legacy aliases (-reinstallsoft, -reinstall, -pak, -unpak, -patchui, -check)
remain accepted for existing users.
EOF
}

log() {
  printf '==> %s\n' "$*"
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

set_mode() {
  local next="$1"
  if [ "$MODE" != "install" ]; then
    die "only one main mode can be used at a time"
  fi
  MODE="$next"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    install)
      ;;
    update|-reinstallsoft)
      set_mode "reinstallsoft"
      INSTALL_HERMES=0
      ;;
    reset-memory|-reinstall)
      set_mode "reinstall"
      INSTALL_HERMES=0
      ;;
    backup|-pak)
      set_mode "pack"
      ;;
    restore|-unpak)
      set_mode "unpack"
      shift
      [ "$#" -gt 0 ] || die "restore needs a backup path"
      PACK_PATH="$1"
      ;;
    desktop|-patchui)
      set_mode "patchui"
      INSTALL_DEPS=0
      INSTALL_HERMES=0
      CONFIGURE_HERMES=0
      CONFIGURE_ELEVENLABS=0
      CONFIGURE_WEB_SEARCH=0
      BACKUP_HERMES_CONFIG=0
      ;;
    doctor|-doctor|-check|-integrity)
      set_mode "doctor"
      INSTALL_DEPS=0
      INSTALL_HERMES=0
      CONFIGURE_ELEVENLABS=0
      CONFIGURE_WEB_SEARCH=0
      BACKUP_HERMES_CONFIG=0
      BUILD_HERMES_DESKTOP_UI=0
      ;;
    uninstall|-uninstall|--uninstall)
      set_mode "uninstall"
      INSTALL_DEPS=0
      INSTALL_HERMES=0
      CONFIGURE_HERMES=0
      CONFIGURE_ELEVENLABS=0
      CONFIGURE_WEB_SEARCH=0
      BACKUP_HERMES_CONFIG=0
      APPLY_HERMES_DESKTOP_UI=0
      BUILD_HERMES_DESKTOP_UI=0
      ;;
    -menu|--menu)
      set_mode "menu"
      ;;
    --no-deps)
      INSTALL_DEPS=0
      ;;
    --no-install-hermes)
      INSTALL_HERMES=0
      ;;
    --no-hermes)
      CONFIGURE_HERMES=0
      ;;
    --keep-hermes-builtin-memory)
      DISABLE_HERMES_BUILTIN_MEMORY=0
      ;;
    --no-web-search)
      CONFIGURE_WEB_SEARCH=0
      ;;
    --configure-web-search)
      CONFIGURE_WEB_SEARCH=1
      ;;
    --no-elevenlabs)
      CONFIGURE_ELEVENLABS=0
      ;;
    --configure-elevenlabs)
      CONFIGURE_ELEVENLABS=1
      ;;
    --no-hermes-config-backup)
      BACKUP_HERMES_CONFIG=0
      ;;
    --no-desktop-ui)
      APPLY_HERMES_DESKTOP_UI=0
      ;;
    --no-desktop-ui-build)
      BUILD_HERMES_DESKTOP_UI=0
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown option: $1"
      ;;
  esac
  shift
done

show_welcome() {
  cat <<EOF

Hermes FPP Memory Installer

This installer sets up:
  1. Hermes Agent
  2. ai-memory MCP in ~/.ai_memory
  3. Hermes MCP config
  4. Hermes SOUL prompt with memory, search, and YouTube rules
  5. Web search and ElevenLabs support (configured later in Desktop)
  6. Clean Hermes Desktop UI
  7. Desktop app launcher

EOF
}

show_menu() {
  show_welcome
  cat <<EOF
Choose an action:
  1) Install/update and keep memory
  2) Check integrity
  3) Rebuild Desktop UI
  4) Backup memory
  5) Restore memory
  6) Reset memory
  7) Uninstall everything
  8) Exit

EOF
  printf 'Select [1-8]: '
  local choice
  IFS= read -r choice
  case "$choice" in
    1|"") MODE="install" ;;
    2) MODE="doctor"; INSTALL_DEPS=0; INSTALL_HERMES=0; BACKUP_HERMES_CONFIG=0; BUILD_HERMES_DESKTOP_UI=0 ;;
    3) MODE="patchui"; INSTALL_DEPS=0; INSTALL_HERMES=0; CONFIGURE_HERMES=0; BACKUP_HERMES_CONFIG=0 ;;
    4) MODE="pack" ;;
    5)
      MODE="unpack"
      printf 'Backup path: '
      IFS= read -r PACK_PATH
      ;;
    6) MODE="reinstall"; INSTALL_HERMES=0 ;;
    7) MODE="uninstall"; INSTALL_DEPS=0; INSTALL_HERMES=0; CONFIGURE_HERMES=0; BACKUP_HERMES_CONFIG=0; APPLY_HERMES_DESKTOP_UI=0; BUILD_HERMES_DESKTOP_UI=0 ;;
    8) exit 0 ;;
    *) die "unknown menu choice: $choice" ;;
  esac
}

if [ "$MODE" = "menu" ]; then
  show_menu
fi

require_existing_install() {
  if [ ! -d "$APP_DIR" ] || [ ! -f "$CONFIG_PATH" ]; then
    die "ai-memory is not installed. Run ./install.sh without flags first."
  fi
}

sudo_cmd() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    die "sudo is required to install OS packages"
  fi
}

install_deps() {
  if [ "$INSTALL_DEPS" -eq 0 ]; then
    return
  fi

  # Hermes' official cross-platform bootstrap owns Python, uv, Node, ripgrep,
  # ffmpeg, Playwright, and native build dependencies. Duplicating that logic
  # here created most of the old installer's questions and distro branches.
  # Hermes FPP only needs Git and curl in order to invoke that bootstrap.
  local missing=()
  local bin
  for bin in git curl; do
    command -v "$bin" >/dev/null 2>&1 || missing+=("$bin")
  done
  if [ "${#missing[@]}" -eq 0 ]; then
    log "Base prerequisites are ready ($PLATFORM)"
    return
  fi

  if [ "$PLATFORM" = "macos" ]; then
    if command -v brew >/dev/null 2>&1; then
      log "Installing missing prerequisites with Homebrew: ${missing[*]}"
      brew install "${missing[@]}"
      return
    fi
    die "missing prerequisites: ${missing[*]}. Install Xcode Command Line Tools (xcode-select --install) or Homebrew, then rerun."
  fi

  if command -v apt-get >/dev/null 2>&1; then
    sudo_cmd apt-get update
    sudo_cmd apt-get install -y "${missing[@]}"
  elif command -v dnf >/dev/null 2>&1; then
    sudo_cmd dnf install -y "${missing[@]}"
  elif command -v pacman >/dev/null 2>&1; then
    sudo_cmd pacman -Syu --needed --noconfirm "${missing[@]}"
  elif command -v emerge >/dev/null 2>&1; then
    sudo_cmd emerge --ask=n "${missing[@]}"
  else
    die "missing prerequisites: ${missing[*]}. Install them and rerun with --no-deps."
  fi
}

install_hermes() {
  if [ "$INSTALL_HERMES" -eq 0 ]; then
    return
  fi
  if command -v hermes >/dev/null 2>&1; then
    log "Hermes already installed: $(command -v hermes)"
    return
  fi
  command -v curl >/dev/null 2>&1 || die "curl is required to install Hermes"

  log "Installing Hermes Agent with the official $PLATFORM bootstrap"
  curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash -s -- --skip-setup
  hash -r
  command -v hermes >/dev/null 2>&1 || die "Hermes installed but its launcher was not found in $PATH"
}

ensure_macos_browser_runtime() {
  [ "$PLATFORM" = "macos" ] || return 0
  [ -d "$HERMES_ROOT" ] || return 0
  if [ -d "$HOME/Library/Caches/ms-playwright" ] && \
    find "$HOME/Library/Caches/ms-playwright" -maxdepth 2 -type f -name INSTALLATION_COMPLETE -print -quit 2>/dev/null | grep -q .; then
    log "Playwright Chromium is ready"
    return 0
  fi
  if ! command -v npx >/dev/null 2>&1; then
    log "npx not found; browser runtime will be installed by Hermes on first use"
    return 0
  fi
  log "Ensuring Playwright Chromium is installed for native macOS browser tools"
  (cd "$HERMES_ROOT" && npx playwright install chromium)
}

find_python() {
  for python_bin in "$HERMES_ROOT/venv/bin/python" python3.13 python3.12 python3.11 python3; do
    if command -v "$python_bin" >/dev/null 2>&1; then
      if "$python_bin" - <<'PY' >/dev/null 2>&1; then
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
        command -v "$python_bin"
        return
      fi
    fi
  done
  die "python >=3.11 not found"
}

copy_source() {
  mkdir -p "$APP_DIR"
  if [ "$(cd "$SRC_DIR" && pwd)" = "$(mkdir -p "$CODE_DIR" && cd "$CODE_DIR" && pwd)" ]; then
    log "Source is already in $CODE_DIR"
    return
  fi

  log "Copying MCP code to $CODE_DIR"
  rm -rf "$CODE_DIR.tmp"
  mkdir -p "$CODE_DIR.tmp"
  tar -C "$SRC_DIR" \
    --exclude='.git' \
    --exclude='.venv' \
    --exclude='.ai-memory-mcp' \
    --exclude='.pytest_cache' \
    --exclude='__pycache__' \
    -cf - . | tar -C "$CODE_DIR.tmp" -xf -
  rm -rf "$CODE_DIR"
  mv "$CODE_DIR.tmp" "$CODE_DIR"
}

write_config() {
  if [ -f "$CONFIG_PATH" ]; then
    log "Keeping existing memory config: $CONFIG_PATH"
    return
  fi
  log "Writing config to $CONFIG_PATH"
  mkdir -p "$APP_DIR"
  cat > "$CONFIG_PATH" <<EOF
db_path = "$DB_PATH"
timezone = "Europe/Moscow"
detailed_retention_days = 10
chat_retention_days = 10
gradual_delete_chars = 20000
max_context_chars = 16000
max_search_items = 8
auto_attach_active_events = true
EOF
}

install_python_package() {
  local python_bin
  python_bin="$(find_python)"
  if [ ! -x "$VENV_DIR/bin/python" ]; then
    log "Creating Python venv at $VENV_DIR with $python_bin"
    "$python_bin" -m venv "$VENV_DIR"
  else
    log "Using existing Python venv at $VENV_DIR"
  fi

  log "Installing Python package"
  "$VENV_DIR/bin/python" -m pip install -q --upgrade pip
  "$VENV_DIR/bin/python" -m pip install -q -e "$CODE_DIR"
}

checkpoint_sqlite() {
  local db="$1"
  [ -f "$db" ] || return 0
  local python_bin="$VENV_DIR/bin/python"
  if [ ! -x "$python_bin" ]; then
    python_bin="$(find_python)"
  fi
  "$python_bin" - "$db" <<'PY' || true
import sqlite3
import sys

db_path = sys.argv[1]
con = sqlite3.connect(db_path)
try:
    con.execute("PRAGMA wal_checkpoint(FULL)")
finally:
    con.close()
PY
}

erase_memory() {
  if [ "${AI_MEMORY_RESET_CONFIRM:-${AI_MEMORY_UNINSTALL_CONFIRM:-}}" != "DELETE" ]; then
    [ -t 0 ] || die "non-interactive reset requires AI_MEMORY_RESET_CONFIRM=DELETE"
    printf 'Type DELETE to erase all Hermes FPP memory: '
    local answer
    IFS= read -r answer
    [ "$answer" = "DELETE" ] || die "memory reset cancelled"
  fi
  log "Erasing memory database"
  rm -f "$DB_PATH" "$DB_PATH-wal" "$DB_PATH-shm"
}

run_with_timeout() {
  local seconds="$1"
  shift
  local python_bin="$VENV_DIR/bin/python"
  if [ ! -x "$python_bin" ]; then
    python_bin="$(find_python)"
  fi
  "$python_bin" -c '
import subprocess, sys
timeout = float(sys.argv[1])
try:
    result = subprocess.run(sys.argv[2:], stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr, timeout=timeout)
except subprocess.TimeoutExpired:
    raise SystemExit(124)
raise SystemExit(result.returncode)
' "$seconds" "$@"
}

configure_hermes() {
  if [ "$CONFIGURE_HERMES" -eq 0 ]; then
    return
  fi
  if ! command -v hermes >/dev/null 2>&1; then
    log "Hermes command not found; skipping Hermes MCP config"
    return
  fi

  local mcp_timeout
  mcp_timeout="${HERMES_MCP_ADD_TIMEOUT_SECONDS:-180}"

  log "Configuring Hermes MCP server: $SERVER_NAME"
  log "Hermes may take up to ${mcp_timeout}s to validate MCP tools"
  hermes mcp remove "$SERVER_NAME" >/dev/null 2>&1 || true
  printf 'Y\n' | run_with_timeout "$mcp_timeout" hermes mcp add "$SERVER_NAME" \
    --command "$VENV_DIR/bin/ai-memory-mcp" \
    --args --config "$CONFIG_PATH" serve || die "Hermes MCP validation timed out or failed"

  if [ "$DISABLE_HERMES_BUILTIN_MEMORY" -eq 1 ]; then
    log "Disabling Hermes built-in MEMORY.md/USER.md injection"
    hermes config set memory.memory_enabled false >/dev/null
    hermes config set memory.user_profile_enabled false >/dev/null
  fi
}

backup_hermes_config() {
  if [ "$BACKUP_HERMES_CONFIG" -eq 0 ]; then
    return
  fi
  if [ ! -d "$HERMES_HOME" ]; then
    log "Hermes home not found at $HERMES_HOME; skipping config backup"
    return
  fi

  local backup_dir
  backup_dir="$APP_DIR/hermes-config-backups/$(date +%Y%m%d_%H%M%S)"
  log "Backing up Hermes config files to $backup_dir"
  mkdir -p "$backup_dir"

  for path in \
    "$HERMES_HOME/config.yaml" \
    "$HERMES_HOME/.env" \
    "$HERMES_HOME/SOUL.md" \
    "$HERMES_HOME/auth.json" \
    "$HERMES_HOME/context_length_cache.yaml"; do
    if [ -f "$path" ]; then
      cp "$path" "$backup_dir/"
      chmod 600 "$backup_dir/$(basename "$path")" 2>/dev/null || true
    fi
  done

  if [ -d "$HERMES_HOME/memories" ]; then
    mkdir -p "$backup_dir/memories"
    cp -a "$HERMES_HOME/memories/." "$backup_dir/memories/"
  fi
}

upsert_env_var() {
  local file="$1"
  local key="$2"
  local value="$3"
  mkdir -p "$(dirname "$file")"
  touch "$file"
  chmod 600 "$file" 2>/dev/null || true
  if grep -qE "^${key}=" "$file"; then
    "$VENV_DIR/bin/python" - "$file" "$key" "$value" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
key = sys.argv[2]
value = sys.argv[3]
lines = path.read_text(encoding="utf-8").splitlines()
out = []
done = False
for line in lines:
    if line.startswith(key + "="):
        out.append(f"{key}={value}")
        done = True
    else:
        out.append(line)
if not done:
    out.append(f"{key}={value}")
path.write_text("\n".join(out) + "\n", encoding="utf-8")
PY
  else
    printf '%s=%s\n' "$key" "$value" >> "$file"
  fi
}

read_existing_env_var() {
  local file="$1"
  local key="$2"
  if [ -f "$file" ]; then
    grep -E "^${key}=" "$file" | tail -n 1 | cut -d= -f2-
  fi
}

remove_env_var() {
  local file="$1"
  local key="$2"
  local tmp
  [ -f "$file" ] || return 0
  tmp="$(mktemp)"
  grep -vE "^${key}=" "$file" > "$tmp" || true
  cat "$tmp" > "$file"
  rm -f "$tmp"
}

trim_spaces() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

normalize_url_or_host() {
  local value
  value="$(trim_spaces "$1")"
  [ -n "$value" ] || return 0
  case "$value" in
    http://*|https://*)
      printf '%s' "$value"
      ;;
    *)
      printf 'http://%s' "$value"
      ;;
  esac
}

web_provider_env_key() {
  case "$1" in
    tavily) printf 'TAVILY_API_KEY' ;;
    exa) printf 'EXA_API_KEY' ;;
    parallel) printf 'PARALLEL_API_KEY' ;;
    firecrawl) printf 'FIRECRAWL_API_KEY' ;;
    brave|brave-free) printf 'BRAVE_SEARCH_API_KEY' ;;
    *) return 1 ;;
  esac
}

web_provider_backend() {
  case "$1" in
    brave) printf 'brave-free' ;;
    *) printf '%s' "$1" ;;
  esac
}

has_web_search_config() {
  local env_file="$HERMES_HOME/.env"
  local key value
  [ -f "$env_file" ] || return 1
  for key in \
    SEARXNG_URL \
    TAVILY_API_KEY \
    EXA_API_KEY \
    PARALLEL_API_KEY \
    FIRECRAWL_API_KEY \
    FIRECRAWL_API_URL \
    BRAVE_SEARCH_API_KEY; do
    value="$(read_existing_env_var "$env_file" "$key" || true)"
    if [ -n "$(trim_spaces "$value")" ]; then
      return 0
    fi
  done
  return 1
}

set_web_backend() {
  local backend="$1"
  if command -v hermes >/dev/null 2>&1; then
    hermes config set web.search_backend "$backend" >/dev/null
  fi
}

configure_web_search() {
  if [ "$CONFIGURE_WEB_SEARCH" -eq 0 ]; then
    if has_web_search_config; then
      WEB_SEARCH_ENABLED=1
    fi
    return
  fi
  if ! command -v hermes >/dev/null 2>&1; then
    log "Hermes command not found; skipping web search config"
    if has_web_search_config; then
      WEB_SEARCH_ENABLED=1
    fi
    return
  fi

  local env_file api_key provider env_key backend searxng_url existing_web
  env_file="$HERMES_HOME/.env"
  api_key="${WEB_SEARCH_API_KEY:-}"
  provider="${WEB_SEARCH_PROVIDER:-}"
  searxng_url="${SEARXNG_URL:-}"
  existing_web=0
  has_web_search_config && existing_web=1

  api_key="$(trim_spaces "$api_key")"
  provider="$(trim_spaces "$provider")"
  searxng_url="$(normalize_url_or_host "$searxng_url")"

  if [ -z "$api_key" ] && [ -t 0 ]; then
    printf 'Web search API key for Tavily/Exa/Parallel/Firecrawl/Brave (Enter for SearXNG'
    if [ "$existing_web" -eq 1 ]; then
      printf ' or to keep current'
    fi
    printf '): '
    IFS= read -r -s api_key
    printf '\n'
    api_key="$(trim_spaces "$api_key")"
  fi

  if [ -n "$api_key" ]; then
    if [ -z "$provider" ] && [ -t 0 ]; then
      printf 'Web search provider [tavily/exa/parallel/firecrawl/brave] (default: tavily): '
      IFS= read -r provider
      provider="$(trim_spaces "$provider")"
    fi
    provider="${provider:-tavily}"
    provider="$(printf '%s' "$provider" | tr '[:upper:]' '[:lower:]')"
    env_key="$(web_provider_env_key "$provider")" || die "unsupported web search provider: $provider"
    backend="$(web_provider_backend "$provider")"

    log "Writing $env_key to $env_file"
    upsert_env_var "$env_file" "$env_key" "$api_key"
    log "Configuring Hermes web search backend: $backend"
    set_web_backend "$backend"
    WEB_SEARCH_ENABLED=1
    return
  fi

  if [ -z "$searxng_url" ] && [ -t 0 ]; then
    printf 'SearXNG URL/IP (example: http://192.168.31.222:8080; Enter to skip'
    if [ "$existing_web" -eq 1 ]; then
      printf ' or keep current'
    fi
    printf '): '
    IFS= read -r searxng_url
    searxng_url="$(normalize_url_or_host "$searxng_url")"
  fi

  if [ -n "$searxng_url" ]; then
    log "Writing SEARXNG_URL to $env_file"
    upsert_env_var "$env_file" "SEARXNG_URL" "$searxng_url"
    log "Configuring Hermes web search backend: searxng"
    set_web_backend "searxng"
    WEB_SEARCH_ENABLED=1

    if command -v curl >/dev/null 2>&1; then
      if curl --max-time 5 -fsS "$searxng_url/search?q=test&format=json" >/dev/null 2>&1; then
        log "SearXNG is reachable"
      else
        log "SearXNG was saved, but the installer could not reach it now"
      fi
    fi
    return
  fi

  if [ "$existing_web" -eq 1 ]; then
    log "Keeping existing Hermes web search config"
    WEB_SEARCH_ENABLED=1
  else
    log "No web search backend configured; omitting web-search rules from SOUL.md"
    WEB_SEARCH_ENABLED=0
  fi
}

install_hermes_soul() {
  if [ ! -d "$HERMES_HOME" ]; then
    log "Hermes home not found at $HERMES_HOME; skipping SOUL.md prompt"
    return
  fi

  if [ "$WEB_SEARCH_ENABLED" -eq 0 ] && has_web_search_config; then
    WEB_SEARCH_ENABLED=1
  fi

  local soul_file="$HERMES_HOME/SOUL.md"
  log "Writing Hermes SOUL prompt: $soul_file"
  {
    cat <<'EOF'
You are Hermes Agent, an intelligent AI assistant created by Nous Research.

Core communication style:
- Answer in Russian by default unless the user explicitly asks for another language.
- Answer in a detailed, explanatory way. Do not give one-line or overly compressed answers unless the user explicitly asks for a short answer.
- Prefer clear plain text with enough context, reasoning, and practical conclusions.
- Do not use emojis, kaomoji, decorative symbols, or smileys.
- Do not wrap ordinary prose in code blocks. Use fenced code blocks only for actual code, terminal commands, configuration snippets, logs, or exact file contents.
- If a command is shown, put only the command in the code block or inline code. Explanations stay outside the block.
- Be direct and useful. If something is uncertain, say what is uncertain and what evidence would confirm it.

Working with files and folders:
- If the user sends or points to a folder, repository, file tree, screenshot, or path but does not explicitly ask to change, fix, patch, edit, delete, move, or create files, inspect only. Do not modify anything.
- Treat phrases like "look", "study", "check", "explain", "review", "what is this", "why", and "analyze" as read-only unless the user clearly asks for changes.
- Before editing files, state briefly what will be changed.
- Keep edits scoped to the user's request and do not do unrelated refactors.

Memory policy for Hermes Memory MCP:
- Use hermes-memory as the long-term user memory system. It is the source of truth instead of Hermes built-in MEMORY.md or USER.md.
- Before the first assistant answer in every new chat, call memory.get_context with the current user message.
- Before every meaningful assistant answer after that, call memory.get_context again unless the user message is only a tiny acknowledgement or the tool is unavailable.
- Treat memory.get_context as mandatory context loading, not an optional search. Use the returned context silently to answer naturally; do not claim there is no memory unless the tool result is empty.
- Use memory.search when the user asks about past conversations, previous decisions, old projects, preferences, events, or anything that may already be stored.
- Save stable long-term facts with memory.save_forever_fact. Examples: user name, operating system, hardware, language preferences, long-term projects, preferred tools, permanent constraints.
- Save time-based information with memory.create_event or memory.update_event. Examples: trips, deadlines, temporary experiments, subscriptions, test periods, planned work.
- Save useful conversation progress with memory.save_turn after meaningful turns, especially when the user gives preferences, project state, decisions, fixes, or personal context worth remembering.
- Use memory.append_day_memory for detailed rolling notes about active work, debugging sessions, installer changes, project status, and temporary context that may be useful over the next days.
- For long or important chats, maintain separate 10-day chat cards with memory.upsert_chat_session and memory.append_chat_note. These are not the same as detailed 10-day day memory: use them for chat title, aliases, current topic, decisions, open questions, handoff checkpoints, and "what we were discussing while this chat was active".
- Link chat cards to events with memory.link_chat_to_event or by passing event_ids to memory.append_chat_note when a chat is about a trip, purchase, project, debugging session, subscription, or other event.
- If the user asks "remember the previous chat", "the chat named ...", "what did we decide about ...", or gives an approximate title such as "MacBook instead of Lenovo", use memory.search first with several title/topic variants, then memory.get_chat_context for the matching chat card when available. If session history/search tools are available and memory is insufficient, use them too. Do not rely only on the current chat transcript.
- Treat huge chats as archives. Do not try to continue a context-overflowed chat by loading all old messages. Summarize and save the durable state, then recommend continuing in a new chat using memory/search checkpoints.
- Do not save secrets, API keys, passwords, tokens, private credentials, or sensitive content unless the user explicitly asks to store a non-secret summary.
- When saving memory, keep it concise and factual. Do not store noisy chat filler.
EOF

    if [ "$WEB_SEARCH_ENABLED" -eq 1 ]; then
      cat <<'EOF'

Web search policy:
- If web search is configured, use it by default for user questions that may benefit from current or external information.
- Always use web search when the user asks to find, search, check online, verify, compare current facts, inspect news, prices, models, APIs, releases, packages, documentation, laws, schedules, or anything that may have changed.
- Do not use web search when the message is not a question, when the user is only reasoning over data already provided in the chat, when the task is strictly local file/code inspection, or when the user explicitly says not to use the internet.
- If the internet or web tool is unavailable, say that clearly and answer from available context without pretending that online verification happened.
- SearXNG is a search backend: use it to find relevant links. If page contents are needed, open the result with browser/page tools when available.
- When using web results, explain the practical conclusion in normal text. Do not dump raw search output unless the user asks for it.
EOF
    fi

    cat <<'EOF'

YouTube policy:
- If the user sends a YouTube link or asks about a YouTube video, first try to use transcript/subtitle tools or the YouTube content skill.
- If a transcript is available, summarize it, extract the key points, and mention timestamps when the tool provides them.
- If there is no transcript, say that the video cannot be fully analyzed from audio/video alone unless video or vision tools are available. In that case, use title, description, comments, or web search only as supporting context and clearly label the limitation.
- Do not claim that you watched the video visually unless a real video/vision tool was used.

Behavior with the user:
- The user prefers practical engineering help and direct explanations.
- For technical topics, first explain the main idea in simple words, then give details and concrete next steps.
- If the user is testing cheap models or limited balance, keep cost and token usage in mind, but still answer fully enough to be useful.
EOF
  } > "$soul_file"
  chmod 600 "$soul_file" 2>/dev/null || true
}

configure_elevenlabs() {
  if [ "$CONFIGURE_ELEVENLABS" -eq 0 ]; then
    return
  fi
  if ! command -v hermes >/dev/null 2>&1; then
    log "Hermes command not found; skipping ElevenLabs config"
    return
  fi

  local env_file api_key voice_id existing_key
  env_file="$HERMES_HOME/.env"
  existing_key="$(read_existing_env_var "$env_file" "ELEVENLABS_API_KEY" || true)"
  api_key="${ELEVENLABS_API_KEY:-}"
  voice_id="${ELEVENLABS_VOICE_ID:-}"
  if [[ "$api_key" =~ ^[[:space:]]*$ ]]; then
    api_key=""
  fi
  if [[ "$voice_id" =~ ^[[:space:]]*$ ]]; then
    voice_id=""
  fi
  if [[ "$existing_key" =~ ^[[:space:]]*$ ]]; then
    if [ -f "$env_file" ] && grep -qE '^ELEVENLABS_API_KEY=' "$env_file"; then
      log "Removing blank ELEVENLABS_API_KEY from $env_file"
      remove_env_var "$env_file" "ELEVENLABS_API_KEY"
    fi
    existing_key=""
  fi

  if [ -z "$api_key" ] && [ -n "$existing_key" ]; then
    log "Keeping existing ELEVENLABS_API_KEY in $env_file"
  elif [ -z "$api_key" ] && [ -t 0 ]; then
    printf 'ElevenLabs API key (leave empty to skip): '
    IFS= read -r -s api_key
    printf '\n'
    if [[ "$api_key" =~ ^[[:space:]]*$ ]]; then
      api_key=""
    fi
  fi

  if [ -n "$api_key" ]; then
    log "Writing ELEVENLABS_API_KEY to $env_file"
    upsert_env_var "$env_file" "ELEVENLABS_API_KEY" "$api_key"
  fi

  if [ -z "$voice_id" ] && [ -t 0 ]; then
    printf 'ElevenLabs voice id (leave empty to skip): '
    IFS= read -r voice_id
    if [[ "$voice_id" =~ ^[[:space:]]*$ ]]; then
      voice_id=""
    fi
  fi

  if [ -n "$voice_id" ]; then
    log "Configuring Hermes TTS provider: elevenlabs"
    hermes config set tts.provider elevenlabs >/dev/null
    hermes config set tts.elevenlabs.voice_id "$voice_id" >/dev/null
    hermes config set tts.elevenlabs.model_id "$DEFAULT_ELEVENLABS_MODEL_ID" >/dev/null
  else
    log "No ElevenLabs voice id provided; leaving TTS config unchanged"
  fi
}

apply_hermes_desktop_ui() {
  if [ "$APPLY_HERMES_DESKTOP_UI" -eq 0 ]; then
    return
  fi

  local patch_script="$CODE_DIR/scripts/apply-hermes-simple-ui.sh"
  if [ ! -x "$patch_script" ]; then
    patch_script="$SRC_DIR/scripts/apply-hermes-simple-ui.sh"
  fi
  [ -x "$patch_script" ] || die "Desktop UI patch script not found"

  if [ ! -d "$HERMES_ROOT/apps/desktop/src" ]; then
    if [ "$MODE" = "patchui" ]; then
      die "Hermes Desktop source not found at $HERMES_ROOT/apps/desktop/src"
    fi
    log "Hermes Desktop source not found at $HERMES_ROOT; skipping Desktop UI patch"
    return
  fi

  log "Applying Hermes Desktop FPP UI patch"
  if [ "$BUILD_HERMES_DESKTOP_UI" -eq 1 ]; then
    HERMES_ROOT="$HERMES_ROOT" "$patch_script" --pack
  else
    HERMES_ROOT="$HERMES_ROOT" "$patch_script"
  fi
}

install_linux_desktop_entry() {
  local apps_dir icon_src icon_value desktop_file launcher_file desktop_app log_file
  apps_dir="$HOME/.local/share/applications"
  desktop_file="$apps_dir/hermes-fpp.desktop"
  launcher_file="$HOME/.local/bin/hermes-fpp-desktop"
  desktop_app="$HERMES_ROOT/apps/desktop/release/linux-unpacked/Hermes"
  log_file="$HERMES_HOME/logs/desktop-launcher.log"
  mkdir -p "$apps_dir"
  mkdir -p "$HOME/.local/bin" "$HERMES_HOME/logs"

  icon_value="hermes"
  for icon_src in \
    "$HERMES_ROOT/apps/desktop/build/icon.png" \
    "$HERMES_ROOT/apps/desktop/assets/icon.png" \
    "$HERMES_ROOT/apps/desktop/public/icon.png"; do
    if [ -f "$icon_src" ]; then
      cp "$icon_src" "$APP_DIR/hermes-fpp-icon.png" || true
      icon_value="$APP_DIR/hermes-fpp-icon.png"
      break
    fi
  done

  log "Writing desktop launcher command: $launcher_file"
  cat > "$launcher_file" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail

app="$desktop_app"
log="$log_file"
profile_dir="\$HOME/.config/Hermes"
mkdir -p "\$(dirname "\$log")"

if [ ! -x "\$app" ]; then
  printf 'Hermes Desktop executable not found: %s\n' "\$app" >> "\$log"
  exit 1
fi

if ! pgrep -u "\$(id -u)" -f "\$app --no-sandbox" >/dev/null 2>&1; then
  pkill -u "\$(id -u)" -f "\$app" >/dev/null 2>&1 || true
  pkill -u "\$(id -u)" -f "\$profile_dir" >/dev/null 2>&1 || true
  rm -f "\$profile_dir"/SingletonLock "\$profile_dir"/SingletonSocket "\$profile_dir"/SingletonCookie
fi

printf '\n[%s] Launching Hermes Desktop\n' "\$(date '+%Y-%m-%d %H:%M:%S')" >> "\$log"
exec "\$app" --no-sandbox --ozone-platform=x11 "\$@" >> "\$log" 2>&1
EOF
  chmod +x "$launcher_file"

  log "Writing desktop launcher: $desktop_file"
  cat > "$desktop_file" <<EOF
[Desktop Entry]
Type=Application
Name=Hermes FPP
Comment=Hermes Agent with FPP memory
Exec=$launcher_file
Icon=$icon_value
Terminal=false
Categories=Utility;Development;AI;
StartupNotify=true
EOF
  chmod +x "$desktop_file" 2>/dev/null || true
  if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$apps_dir" >/dev/null 2>&1 || true
  fi
}

find_macos_desktop_app() {
  local release_dir="$HERMES_ROOT/apps/desktop/release"
  [ -d "$release_dir" ] || return 1
  find "$release_dir" -maxdepth 4 -type d -name 'Hermes.app' -print 2>/dev/null | head -n 1
}

install_macos_desktop_entry() {
  local source_app destination_app staged_app launcher_file
  source_app="$(find_macos_desktop_app || true)"
  if [ -z "$source_app" ]; then
    if [ "$BUILD_HERMES_DESKTOP_UI" -eq 1 ] || [ "$MODE" = "patchui" ]; then
      die "macOS Hermes.app was not produced under $HERMES_ROOT/apps/desktop/release"
    fi
    log "macOS Desktop build not found; skipping app installation"
    return
  fi

  destination_app="$HOME/Applications/Hermes FPP.app"
  staged_app="$HOME/Applications/.Hermes FPP.app.new.$$"
  launcher_file="$HOME/.local/bin/hermes-fpp-desktop"
  mkdir -p "$HOME/Applications" "$HOME/.local/bin"

  log "Installing native macOS app: $destination_app"
  rm -rf -- "$staged_app"
  ditto "$source_app" "$staged_app"
  if command -v codesign >/dev/null 2>&1; then
    codesign --force --deep --sign - "$staged_app" >/dev/null 2>&1 || \
      log "Ad-hoc code signing failed; macOS may ask for confirmation on first launch"
  fi
  rm -rf -- "$destination_app"
  mv "$staged_app" "$destination_app"

  cat > "$launcher_file" <<EOF
#!/usr/bin/env bash
set -e
exec open "$destination_app" --args "\$@"
EOF
  chmod +x "$launcher_file"
}

install_desktop_entry() {
  if ! command -v hermes >/dev/null 2>&1; then
    log "Hermes command not found; skipping desktop launcher"
    return
  fi
  if [ "$PLATFORM" = "macos" ]; then
    install_macos_desktop_entry
  else
    install_linux_desktop_entry
  fi
}

doctor() {
  local failed=0

  log "Checking Hermes FPP on $PLATFORM ($(uname -m))"
  [ -d "$APP_DIR" ] || { printf 'FAIL app dir missing: %s\n' "$APP_DIR"; failed=1; }
  [ -d "$CODE_DIR" ] || { printf 'FAIL code dir missing: %s\n' "$CODE_DIR"; failed=1; }
  [ -x "$VENV_DIR/bin/ai-memory-mcp" ] || { printf 'FAIL MCP executable missing: %s\n' "$VENV_DIR/bin/ai-memory-mcp"; failed=1; }
  [ -f "$CONFIG_PATH" ] || { printf 'FAIL config missing: %s\n' "$CONFIG_PATH"; failed=1; }
  [ -f "$DB_PATH" ] || printf 'WARN memory database not created yet: %s\n' "$DB_PATH"

  if [ "$failed" -eq 0 ]; then
    log "Checking ai-memory-mcp"
    "$VENV_DIR/bin/ai-memory-mcp" --config "$CONFIG_PATH" doctor
  fi

  if ! command -v hermes >/dev/null 2>&1; then
    printf 'FAIL Hermes command not found\n'
    failed=1
  elif [ "$CONFIGURE_HERMES" -eq 1 ]; then
    log "Hermes MCP config"
    hermes mcp list
  fi

  if [ -f "$HERMES_ROOT/apps/desktop/src/app/settings/fpp-settings.tsx" ]; then
    printf 'OK Hermes Desktop FPP settings patch found\n'
  else
    printf 'WARN Hermes Desktop FPP settings patch not found\n'
  fi

  if [ "$PLATFORM" = "macos" ]; then
    local mac_app="$HOME/Applications/Hermes FPP.app"
    if [ -x "$mac_app/Contents/MacOS/Hermes" ]; then
      if command -v codesign >/dev/null 2>&1 && ! codesign --verify --deep --strict "$mac_app" >/dev/null 2>&1; then
        printf 'FAIL native macOS app has an invalid signature: %s\n' "$mac_app"
        failed=1
      else
        printf 'OK native macOS app found and verified\n'
      fi
    else
      printf 'WARN native macOS app not found\n'
    fi
  elif [ -f "$HOME/.local/share/applications/hermes-fpp.desktop" ]; then
    printf 'OK Linux desktop launcher found\n'
  else
    printf 'WARN Linux desktop launcher not found\n'
  fi

  [ "$failed" -eq 0 ] || exit 1
}

pack_memory() {
  require_existing_install
  [ -f "$DB_PATH" ] || die "memory database does not exist: $DB_PATH"
  checkpoint_sqlite "$DB_PATH"

  local pack_name pack_path
  pack_name="ai_memory_pack_$(date +%Y%m%d_%H%M%S).tar.gz"
  pack_path="$APP_DIR/$pack_name"

  log "Creating memory pack: $pack_path"
  tar -C "$APP_DIR" -czf "$pack_path" memory.sqlite3 config.toml
  printf '%s\n' "$pack_path"
}

unpack_memory() {
  require_existing_install
  [ -n "$PACK_PATH" ] || die "restore needs a backup path"
  [ -f "$PACK_PATH" ] || die "backup not found: $PACK_PATH"

  log "Restoring memory pack: $PACK_PATH"
  rm -f "$DB_PATH" "$DB_PATH-wal" "$DB_PATH-shm"
  tar -C "$APP_DIR" -xzf "$PACK_PATH" memory.sqlite3
  [ -f "$APP_DIR/config.toml" ] || write_config
  "$VENV_DIR/bin/ai-memory-mcp" --config "$CONFIG_PATH" doctor
}

install_flow() {
  install_deps
  install_hermes
  ensure_macos_browser_runtime
  copy_source
  write_config
  install_python_package
  backup_hermes_config
  configure_hermes
  configure_web_search
  install_hermes_soul
  configure_elevenlabs
  apply_hermes_desktop_ui
  install_desktop_entry
  doctor
}

reinstall_flow() {
  require_existing_install
  INSTALL_HERMES=0
  log "Reinstalling ai-memory-mcp and erasing memory"
  ensure_macos_browser_runtime
  rm -rf "$CODE_DIR" "$VENV_DIR"
  write_config
  erase_memory
  copy_source
  install_python_package
  backup_hermes_config
  configure_hermes
  configure_web_search
  install_hermes_soul
  configure_elevenlabs
  apply_hermes_desktop_ui
  install_desktop_entry
  doctor
}

reinstall_soft_flow() {
  require_existing_install
  INSTALL_HERMES=0
  log "Repairing/updating ai-memory-mcp and keeping memory"
  ensure_macos_browser_runtime
  rm -rf "$CODE_DIR"
  write_config
  copy_source
  install_python_package
  backup_hermes_config
  configure_hermes
  configure_web_search
  install_hermes_soul
  configure_elevenlabs
  apply_hermes_desktop_ui
  install_desktop_entry
  doctor
}

patch_ui_flow() {
  APPLY_HERMES_DESKTOP_UI=1
  apply_hermes_desktop_ui
  install_desktop_entry
}

safe_remove_path() {
  local path="$1"
  [ -n "$path" ] || die "refusing to remove an empty path"

  local resolved
  if command -v python3 >/dev/null 2>&1; then
    resolved="$(python3 -c 'import os,sys; print(os.path.realpath(os.path.expanduser(sys.argv[1])))' "$path")"
  else
    resolved="$(cd "$(dirname "$path")" 2>/dev/null && printf '%s/%s\n' "$PWD" "$(basename "$path")")"
  fi

  case "$resolved" in
    /|"$HOME")
      die "refusing to remove unsafe path: $resolved"
      ;;
  esac

  if [ -e "$resolved" ] || [ -L "$resolved" ]; then
    log "Removing $resolved"
    rm -rf -- "$resolved"
  fi
}

remove_hermes_services() {
  [ "$PLATFORM" = "linux" ] || return 0
  local unit unit_name
  local user_units=(
    "$HOME/.config/systemd/user/hermes-gateway"*.service
    "$HOME/.config/systemd/user/hermes-agent"*.service
  )

  for unit in "${user_units[@]}"; do
    [ -e "$unit" ] || continue
    unit_name="$(basename "$unit")"
    if command -v systemctl >/dev/null 2>&1; then
      systemctl --user disable --now "$unit_name" >/dev/null 2>&1 || true
    fi
    log "Removing Hermes user service: $unit"
    rm -f -- "$unit"
  done

  if command -v systemctl >/dev/null 2>&1; then
    systemctl --user daemon-reload >/dev/null 2>&1 || true
  fi
}

remove_hermes_launcher() {
  local launcher="$HOME/.local/bin/hermes"
  [ -e "$launcher" ] || [ -L "$launcher" ] || return 0

  if [ -L "$launcher" ]; then
    local target
    target="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$launcher" 2>/dev/null || true)"
    case "$target" in
      "$HERMES_HOME"/*|"$HERMES_ROOT"/*)
        log "Removing Hermes launcher: $launcher"
        rm -f -- "$launcher"
        ;;
    esac
    return
  fi

  if grep -qE 'hermes-agent|hermes_cli' "$launcher" 2>/dev/null; then
    log "Removing Hermes launcher: $launcher"
    rm -f -- "$launcher"
  fi
}

remove_hermes_node_links() {
  local name link target
  for name in node npm npx; do
    link="$HOME/.local/bin/$name"
    [ -L "$link" ] || continue
    target="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$link" 2>/dev/null || true)"
    case "$target" in
      "$HERMES_HOME/node"/*)
        log "Removing Hermes-managed link: $link"
        rm -f -- "$link"
        ;;
    esac
  done
}

confirm_full_uninstall() {
  cat <<EOF

WARNING: complete uninstall will permanently delete:
  $APP_DIR
  $HERMES_HOME
  $HOME/.config/Hermes
  $HOME/.cache/Hermes
  $HOME/.cache/ms-playwright
  $HOME/.local/share/applications/hermes-fpp.desktop
  $HOME/Applications/Hermes FPP.app
  $HOME/Library/Application Support/Hermes
  $HOME/Library/Caches/Hermes
  $HOME/Library/Caches/ms-playwright
  Hermes launcher, managed Node links, Desktop data, sessions, keys, and memory

The project source directory will be kept:
  $SRC_DIR

Shared OS packages such as Python, Git, ripgrep, and ffmpeg will be kept.

EOF

  if [ "${AI_MEMORY_UNINSTALL_CONFIRM:-}" = "DELETE" ]; then
    return
  fi
  [ -t 0 ] || die "non-interactive uninstall requires AI_MEMORY_UNINSTALL_CONFIRM=DELETE"

  local answer
  printf 'Type DELETE to confirm: '
  IFS= read -r answer
  [ "$answer" = "DELETE" ] || die "uninstall cancelled"
}

uninstall_everything() {
  confirm_full_uninstall

  remove_hermes_services
  remove_hermes_launcher
  remove_hermes_node_links

  local hermes_python="$HERMES_ROOT/venv/bin/python"
  if [ -x "$hermes_python" ] && [ -d "$HERMES_ROOT/hermes_cli" ]; then
    log "Running Hermes full uninstaller"
    HERMES_HOME="$HERMES_HOME" "$hermes_python" -m hermes_cli.uninstall --mode full || \
      log "Hermes uninstaller reported an error; continuing with fallback cleanup"
  fi

  safe_remove_path "$APP_DIR"
  safe_remove_path "$HERMES_HOME"
  safe_remove_path "$HOME/.config/Hermes"
  safe_remove_path "$HOME/.cache/Hermes"
  safe_remove_path "$HOME/.cache/ms-playwright"

  if [ "$PLATFORM" = "macos" ]; then
    safe_remove_path "$HOME/Applications/Hermes FPP.app"
    safe_remove_path "$HOME/Library/Application Support/Hermes"
    safe_remove_path "$HOME/Library/Caches/Hermes"
    safe_remove_path "$HOME/Library/Caches/ms-playwright"
  fi

  rm -f -- \
    "$HOME/.local/bin/hermes-fpp-desktop" \
    "$HOME/.local/share/applications/hermes-fpp.desktop" \
    "$HOME/.local/share/applications/hermes.desktop" \
    "$HOME/.local/share/applications/Hermes.desktop"

  if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1 || true
  fi

  cat <<EOF

Uninstall complete.
Removed ai-memory, Hermes Agent, Hermes configuration/data, Desktop UI data,
launchers, and managed runtime files.
Kept project source: $SRC_DIR
EOF
}

case "$MODE" in
  install)
    install_flow
    ;;
  reinstall)
    reinstall_flow
    ;;
  reinstallsoft)
    reinstall_soft_flow
    ;;
  pack)
    pack_memory
    exit 0
    ;;
  unpack)
    unpack_memory
    exit 0
    ;;
  patchui)
    patch_ui_flow
    exit 0
    ;;
  doctor)
    require_existing_install
    doctor
    exit 0
    ;;
  uninstall)
    uninstall_everything
    exit 0
    ;;
  *)
    die "unknown mode: $MODE"
    ;;
esac

printf '\nInstalled:\n'
printf '  Home:    %s\n' "$APP_DIR"
printf '  Code:    %s\n' "$CODE_DIR"
printf '  Venv:    %s\n' "$VENV_DIR"
printf '  Config:  %s\n' "$CONFIG_PATH"
printf '  DB:      %s\n' "$DB_PATH"
printf '\nRun:\n'
printf '  %s/bin/ai-memory-mcp --config %s doctor\n' "$VENV_DIR" "$CONFIG_PATH"
printf '  hermes mcp test %s\n' "$SERVER_NAME"
