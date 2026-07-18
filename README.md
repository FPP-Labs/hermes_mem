# Hermes FPP

Hermes Agent с локальной долгой памятью, упрощённым Desktop UI и одинаковой установкой на Linux и macOS.

Проект начинался как отдельный MCP памяти, но теперь это FPP-сборка Hermes: установщик ставит официальный Hermes, подключает память, накладывает UI-патч и собирает нативное Desktop-приложение.

```text
Hermes FPP Desktop (Linux / macOS)
  ├── Hermes Agent
  ├── Hermes Memory MCP
  │   ├── подробная память последних 10 дней
  │   ├── отдельные 10-дневные карточки чатов
  │   ├── постоянные факты
  │   ├── постоянные события и их следы
  │   └── SQLite + FTS5
  └── FPP UI
      ├── Temporary chat
      ├── FPP settings
      ├── Hidden Panels
      └── ElevenLabs settings
```

## Установка

Поддерживаются Linux и macOS 12+. Для первого запуска нужны Git и curl. Остальные управляемые runtime-зависимости устанавливает официальный bootstrap Hermes.

```bash
./install.sh
```

Команда не задаёт длинную анкету. Она:

1. устанавливает официальный Hermes Agent, если его ещё нет;
2. ставит Memory MCP в `~/.ai_memory`;
3. подключает `hermes-memory` и отключает конфликтующую встроенную память Hermes;
4. применяет FPP UI-патч;
5. собирает и устанавливает Desktop-приложение;
6. сохраняет существующую базу памяти и настройки.

На macOS приложение появляется здесь:

```text
~/Applications/Hermes FPP.app
```

На Linux создаётся launcher `Hermes FPP` в меню приложений. Запустить Desktop из терминала на обеих системах можно так:

```bash
hermes-fpp-desktop
```

Модель и провайдер настраиваются при первом запуске Hermes. Web search и ElevenLabs можно настроить позже в обычных настройках приложения; установщик по умолчанию ключи не спрашивает.

## Команды установщика

```bash
./install.sh                       # установить/обновить, память сохранить
./install.sh update                # восстановить установку, память сохранить
./install.sh doctor                # проверить БД, MCP и Desktop
./install.sh backup                # создать переносимый backup памяти
./install.sh restore PATH          # восстановить память из backup
./install.sh desktop               # пересобрать только FPP Desktop
./install.sh reset-memory          # удалить только память и переустановить
./install.sh uninstall             # удалить Hermes FPP и пользовательские данные
```

`reset-memory` и `uninstall` требуют явно ввести `DELETE`. Обычная установка и `update` никогда не удаляют `memory.sqlite3`.

Дополнительные параметры:

```bash
./install.sh --no-deps
./install.sh --no-install-hermes
./install.sh --no-desktop-ui-build
./install.sh --configure-web-search
./install.sh --configure-elevenlabs
./install.sh --help
```

Старые алиасы (`-reinstallsoft`, `-reinstall`, `-pak`, `-unpak`, `-patchui`, `-check`) пока поддерживаются для обратной совместимости.

## Где лежат данные

```text
~/.ai_memory/
  mcp/              # установленный код Memory MCP
  venv/             # отдельное Python-окружение
  config.toml       # параметры памяти
  memory.sqlite3    # база памяти

~/.hermes/          # Hermes Agent, конфиг, runtime и исходники Desktop
```

Backup содержит `memory.sqlite3` и переносится между Linux и macOS:

```bash
./install.sh backup
./install.sh restore ~/.ai_memory/ai_memory_pack_YYYYMMDD_HHMMSS.tar.gz
```

## Как устроена память

### Подробная память

Последние 10 дней хранятся подробными текстовыми чанками. После истечения срока самые старые данные удаляются постепенно, а не одним большим обрывом.

### Карточки чатов

Большой или завершённый чат может получить отдельную карточку: название, алиасы, summary, заметки и связи с событиями. Карточки живут 10 дней и доступны через поиск, поэтому новый чат может восстановить решение из предыдущего без загрузки всей старой переписки.

### Постоянные факты

Короткие устойчивые сведения о пользователе хранятся без срока жизни. Секреты и ключи память автоматически сохранять не должна.

### События

Проекты, поездки, покупки и другие события имеют даты и хранятся постоянно. Память активного периода привязывается к событию; после ротации подробного текста остаётся короткий след события.

Перед ответом Hermes использует:

```text
memory.get_today
memory.get_context
```

После ответа — `memory.save_turn`. Для постоянных сведений, событий и карточек чатов доступны отдельные MCP-инструменты. Всего сервер публикует 24 инструмента, включая полнотекстовый `memory.search` и `memory.doctor`.

## Разработка Memory MCP

Требуется Python 3.11+:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/pytest
```

Проверка CLI в репозитории:

```bash
.venv/bin/ai-memory-mcp init
.venv/bin/ai-memory-mcp doctor
.venv/bin/ai-memory-mcp context "что я говорил про поездку"
```

По умолчанию используется `~/.ai_memory/memory.sqlite3`. Для изолированного запуска:

```bash
HERMES_MEMORY_DB=/tmp/hermes-memory.sqlite3 .venv/bin/ai-memory-mcp serve
```

Основные параметры находятся в `~/.ai_memory/config.toml`:

```toml
db_path = "/Users/name/.ai_memory/memory.sqlite3"
timezone = "Europe/Moscow"
detailed_retention_days = 10
chat_retention_days = 10
gradual_delete_chars = 20000
max_context_chars = 16000
max_search_items = 8
auto_attach_active_events = true
```

Memory MCP сам не вызывает модель и не отправляет данные наружу: это локальное SQLite-хранилище, которым управляет Hermes через MCP.
