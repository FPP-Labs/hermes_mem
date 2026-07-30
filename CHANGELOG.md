# Changelog

All notable changes to Hermes Mem are documented in this file.

## [0.2.0b11] - 2026-07-30

### Fixed

- Forced DDGS/Primp to use the operating system DNS resolver, preventing web
  search from breaking after sleep, Wi-Fi, VPN, or DNS network transitions.
- Added a keyless DuckDuckGo HTML fallback through `httpx` when the primary
  DDGS client still times out or fails.
- Made the search repair part of both installation and update while preserving
  existing chats, memory, and settings.

## [0.2.0b1] - 2026-07-28

Hermes Mem Beta 0.2 is based on the tested Hermes Agent 0.18.2 source pinned
to commit `36f2a966c7f9f69987494b867c3dcf96b69a5766`.

### Added

- Automatic code-level memory retrieval before ordinary assistant answers.
- Automatic exact archival of every completed user and assistant turn with
  local timestamps and ten-day retention.
- Exact-quote search and a detailed ten-day conversation timeline.
- Background semantic consolidation for long-term facts, summaries, plans,
  and events without blocking the visible response.
- Explicit plan and event states so intended work is not recalled as already
  completed.
- Temporary chats that neither read nor write Hermes Memory.
- Hermes Mem settings for DuckDuckGo and self-hosted SearXNG search.
- Automatic recognition of YouTube links and extraction of the available
  subtitles as timestamped text.

### Changed

- Renamed the custom settings area from FPP to Hermes Mem.
- Search and ElevenLabs configuration now lives in the desktop settings; the
  installer no longer asks for those values.
- The updater can download the current release from GitHub while preserving
  the isolated `~/.hermes-mem` chats, memory, configuration, and credentials.
- YouTube subtitles are prepared automatically before Hermes answers.
- Memory entries include explicit local date and time information.

### Fixed

- Fixed Linux installation when the official Hermes bootstrap creates a
  `uv`-managed Python environment without the `pip` module.
- Fixed Linux desktop builds when the official Hermes bootstrap uses system
  Node.js and npm instead of installing a Hermes-managed Node runtime.
- Prevented missed memory writes by moving exact capture out of model tool
  choice and into the completed-turn finalizer.
- Prevented concepts, wishes, and future plans from being recalled as finished
  projects or present-day facts.
- Preserved exact text until background semantic processing succeeds.
- Kept YouTube identifiers case-sensitive and stopped unrelated fallbacks when
  captions are unavailable.

## [0.1.0b1] - 2026-07-19

- First public Hermes Mem beta with isolated local storage and a simplified
  Hermes Desktop experience.
