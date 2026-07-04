# ai-memory-mcp

Локальный MCP-модуль памяти для Hermes.

Главная идея: Hermes сам управляет памятью. Перед ответом он вызывает `memory.get_context`, отправляет полученный контекст в Codex/ChatGPT, а после ответа вызывает `memory.save_turn`.

```text
Hermes Linux App
  |
  +-- Hermes Memory MCP
  |     +-- 10-day detailed rolling memory
  |     +-- forever user facts
  |     +-- forever time-based events
  |     +-- SQLite
  |
  +-- Codex / ChatGPT
```

## Слои памяти

### 1. 10-дневная подробная память

Это не короткое summary. Модуль хранит подробный текст последних 10 дней чанками.

На 11-й день новый день начинает записываться подробно, а самый старый день постепенно удаляется. Размер шага удаления задается `gradual_delete_chars`.

### 2. Вечные факты

Короткие постоянные факты о пользователе:

```text
Пользователя зовут FPP.
Пользователь делает Hermes для Linux.
Пользователь хочет 10 дней подробной памяти, а не summary.
```

### 3. События

События хранятся навсегда и имеют даты:

```text
Поездка пользователя: 2026-06-17 -> 2026-06-27
```

Если пользователь общается с Hermes во время события, новые дневные воспоминания автоматически привязываются к активному событию. Когда подробная 10-дневная память позднее удаляет старый чанк, событие сохраняет короткий `event_trace`.

## Установка

Рекомендуемый вариант: установить весь MCP-модуль и всю память в одну папку пользователя:

```text
~/.ai_memory/
  mcp/              # код MCP
  venv/             # Python virtualenv
  config.toml       # конфиг памяти
  memory.sqlite3    # SQLite база памяти
```

Автоустановка для Debian, Fedora, Arch и Gentoo:

```bash
./install.sh
```

Этапы установщика:

1. Проверяет системные зависимости и ставит недостающие через `apt`, `dnf`, `pacman` или `emerge`.
2. Ставит Hermes Agent, если команды `hermes` еще нет.
3. Ставит этот MCP в `~/.ai_memory`.
4. Создает конфиг `~/.ai_memory/config.toml`.
5. Делает backup текущих Hermes-конфигов в `~/.ai_memory/hermes-config-backups/`.
6. Подключает MCP `hermes-memory` к Hermes.
7. Отключает встроенную память Hermes `MEMORY.md/USER.md`, чтобы не было конфликтов.
8. Спрашивает ElevenLabs API key и voice id, если запуск интерактивный, и прописывает TTS.

На Arch Linux установщик сначала проверяет пакеты через локальную базу `pacman`.
Если все зависимости уже установлены, системная транзакция не запускается.
Если чего-то не хватает, используется полное обновление `pacman -Syu`, потому что
частичное обновление через `pacman -Sy` на Arch не поддерживается и может вызвать
конфликты ABI, например между `x265`, `ffmpeg4.4` и `libheif`.

Обычная установка больше не ищет старые базы автоматически. Для переноса памяти используй pack/unpack:

```bash
./install.sh -pak
./install.sh -unpak /home/fpp/.ai_memory/ai_memory_pack_YYYYMMDD_HHMMSS.tar.gz
```

Если ничего еще не установлено, режимы `-pak`, `-unpak`, `-reinstall` и `-reinstallsoft`
завершатся ошибкой и попросят сначала запустить обычную установку без флагов.

Если системные зависимости уже стоят:

```bash
./install.sh --no-deps
```

Если Hermes не надо ставить автоматически:

```bash
./install.sh --no-install-hermes
```

Полная переустановка без переустановки Hermes и с удалением памяти:

```bash
./install.sh -reinstall
```

Мягкая переустановка без переустановки Hermes, но с сохранением памяти:

```bash
./install.sh -reinstallsoft
```

Полное удаление всего, что относится к ai-memory и Hermes:

```bash
./install.sh -uninstall
```

Режим требует ввести `DELETE` и удаляет `~/.ai_memory`, весь `~/.hermes`,
конфигурацию, ключи, сессии, логи, Desktop UI, launcher и управляемые Hermes
runtime-файлы, включая кэш Playwright `~/.cache/ms-playwright`. Исходная папка этого проекта и общие системные пакеты
(`python`, `git`, `ripgrep`, `ffmpeg`) сохраняются.

Для подтверждённого неинтерактивного запуска:

```bash
AI_MEMORY_UNINSTALL_CONFIRM=DELETE ./install.sh -uninstall
```

Для ElevenLabs в неинтерактивном режиме:

```bash
ELEVENLABS_API_KEY="..." ELEVENLABS_VOICE_ID="s0phbFBBp708ZeIy8oGx" ./install.sh
```

Ключ пишется в:

```text
~/.hermes/.env
```

Настройки голоса пишутся в:

```yaml
tts:
  provider: elevenlabs
  elevenlabs:
    voice_id: s0phbFBBp708ZeIy8oGx
    model_id: eleven_multilingual_v2
```

Установщик:

- ставит Python-зависимости;
- копирует код в `~/.ai_memory/mcp`;
- создает venv в `~/.ai_memory/venv`;
- создает конфиг `~/.ai_memory/config.toml`;
- прописывает MCP `hermes-memory` в Hermes;
- настраивает ElevenLabs TTS, если даны ключ и voice id;
- отключает встроенную память Hermes `MEMORY.md/USER.md`, чтобы источником правды была эта MCP-память.

Ручная разработческая установка в текущем репозитории:

```bash
.venv/bin/python -m pip install -e ".[dev]"
```

Инициализация:

```bash
.venv/bin/ai-memory-mcp init
.venv/bin/ai-memory-mcp doctor
```

По умолчанию база лежит здесь:

```text
~/.ai_memory/memory.sqlite3
```

Можно переопределить:

```bash
HERMES_MEMORY_DB=/path/to/memory.sqlite3 .venv/bin/ai-memory-mcp serve
```

## Запуск MCP

```bash
.venv/bin/ai-memory-mcp serve
```

Пример подключения в Codex/Hermes как stdio MCP:

```json
{
  "mcpServers": {
    "hermes-memory": {
      "command": "/home/fpp/.ai_memory/venv/bin/ai-memory-mcp",
      "args": ["--config", "/home/fpp/.ai_memory/config.toml", "serve"]
    }
  }
}
```

## Основной поток Hermes

Перед ответом:

```text
memory.get_today
memory.get_context
```

После ответа:

```text
memory.save_turn
```

Если пользователь сказал важный постоянный факт:

```text
memory.save_forever_fact
```

Если пользователь сказал временное событие, например "я буду там 10 дней":

```text
memory.create_event
```

## MCP tools

```text
memory.get_today
memory.get_context
memory.save_turn
memory.append_day_memory
memory.get_10_day_detailed_memory
memory.rotate_10_day_memory
memory.save_forever_fact
memory.list_forever_facts
memory.create_event
memory.update_event
memory.list_events
memory.active_events
memory.get_event_context
memory.link_memory_to_event
memory.search
memory.forget_memory
memory.day_stats
memory.doctor
```

## CLI примеры

Текущая дата и время:

```bash
.venv/bin/ai-memory-mcp today
```

Сохранить вечный факт:

```bash
.venv/bin/ai-memory-mcp fact "Пользователя зовут FPP." --category identity
```

Создать событие на 10 дней:

```bash
.venv/bin/ai-memory-mcp event-create "Поездка пользователя" \
  --type trip \
  --start-at "2026-06-17T00:00:00+03:00" \
  --duration-days 10 \
  --description "Пользователь находится в поездке 10 дней."
```

Сохранить ход диалога:

```bash
.venv/bin/ai-memory-mcp save-turn \
  --user "Сегодня первый день поездки, место очень понравилось." \
  --assistant "Запомнил это как часть поездки." \
  --at "2026-06-17T12:00:00+03:00"
```

Получить контекст для prompt:

```bash
.venv/bin/ai-memory-mcp context "что я говорил про поездку"
```

Проверить ротацию дней:

```bash
.venv/bin/ai-memory-mcp day-stats
.venv/bin/ai-memory-mcp rotate
```

## Конфиг

Файл:

```text
~/.ai_memory/config.toml
```

Пример:

```toml
db_path = "/home/fpp/.ai_memory/memory.sqlite3"
timezone = "Europe/Moscow"
detailed_retention_days = 10
gradual_delete_chars = 20000
max_context_chars = 120000
max_search_items = 20
auto_attach_active_events = true
```

## Тесты

```bash
.venv/bin/pytest
```

## Важно

Этот MCP не вызывает OpenAI сам. Он только хранит и выдает память. Hermes должен сам решать:

- когда вызвать память;
- какой контекст отправить в Codex/ChatGPT;
- какие факты или события сохранить навсегда.
