# Hermes Mem Beta 0.2

Hermes Mem is an independent community fork of [Hermes Agent](https://github.com/NousResearch/hermes-agent) focused on isolated local memory and a simplified desktop experience.

Hermes Mem Beta 0.2 uses the tested Hermes Agent `0.18.2` build pinned to commit `36f2a966c7f9f69987494b867c3dcf96b69a5766`. New upstream changes are not downloaded automatically.

Release version: `0.2.0b11`. See [CHANGELOG.md](CHANGELOG.md) for the Beta 0.2 release notes.

## Install

Linux and macOS:

```bash
git clone https://github.com/FPP-Labs/hermes_mem.git && cd hermes_mem && ./install.sh
```

Choose `1) Install`. The first installation downloads Hermes Agent, Python packages, Node.js packages, Chromium, and the desktop application, so it can take several minutes.

## Installer menu

```text
1) Install
2) Delete
3) Update
```

- Install creates or completes Hermes Mem Beta 0.2.
- Delete permanently removes only Hermes Mem data after the exact confirmation phrase `DELETE_HERMES_MEM`.
- Update downloads the latest Hermes Mem release while keeping chats and memory. The pinned Hermes Agent build remains unchanged.

## Isolated data

Hermes Mem stores everything under:

```text
~/.hermes-mem
```

It does not use or delete the regular Hermes directory at `~/.hermes`.

On macOS, the application is installed as:

```text
~/Applications/Hermes Mem.app
```

## Memory settings

Open Settings and select Hermes Mem. The Memory screen provides:

- code-level automatic memory loading before every ordinary answer;
- a verbatim 10-day archive of every completed user/assistant turn, with exact local timestamps and quote-safe search;
- background semantic consolidation into compact long-term summaries, facts, plans, and events;
- retry-safe retention: exact text awaiting a failed semantic review is not deleted until the review succeeds;
- scoped search across exact turns, long-term summaries and facts, rolling 10-day memory, and events;
- explicit plan states so wishes and unresolved intentions are not treated as completed facts;
- long-term facts;
- active events;
- everything recorded today;
- the retained 10-day timeline;
- permanent deletion of all memory using `DELETE_ALL_MEMORY`.

Temporary chats do not read from memory, write exact turns, or run semantic consolidation.

Deleting memory does not delete regular Hermes Mem chat history. Deleting Hermes Mem from the installer removes the entire isolated Hermes Mem folder, including its chats and memory.

## Search settings

Open Settings, select Hermes Mem, and use the Search section:

- DuckDuckGo is selected by default and works without an API key or a separate server;
- SearXNG can be selected by entering the IP address or hostname of the server and its port;
- the selected provider is saved as `web.search_backend`;
- Hermes uses the active provider automatically when a question needs current or external information.

Search and ElevenLabs are configured only in Settings → Hermes Mem. The installer never asks for API keys, voice IDs, search providers, or SearXNG server details.

## YouTube subtitles

Send a public YouTube, youtu.be, Shorts, live, or embed link. Hermes recognizes the link, extracts the available subtitles, and turns them into timestamped text before answering.

- supported YouTube links are recognized automatically;
- available video subtitles are extracted as timestamped text;
- video files are not downloaded and there is no separate video-analysis charge;
- the exact case-sensitive video ID is extracted from the original message;
- subtitles are cached locally for seven days;
- subtitle text is treated as untrusted source material and cannot issue instructions to the agent;
- responses are explicitly transcript-only and never presented as visual understanding;
- when captions are disabled or unavailable, Hermes reports that limitation instead of trying unrelated web or browser tools.

Hermes uses the extracted subtitles as context for its reply.

## Troubleshooting

Normal installation output is intentionally minimal. If a step fails, detailed output is saved to:

```text
~/.hermes-mem/install-error.log
```

Run `./install.sh` again and choose `1) Install` to continue an incomplete installation.

## License and attribution

Both the original Hermes Agent portions and the Hermes Mem modifications are distributed under the MIT License.

Original Hermes Agent portions are Copyright (c) 2025 Nous Research. Hermes Mem modifications are Copyright (c) 2026 FPP Labs.

Under the MIT License, users may use, copy, modify, distribute, sublicense, and sell the software, including modified versions, provided that the applicable copyright and license notices are preserved.

Hermes Mem is not affiliated with, endorsed by, or an official product of Nous Research. See [LICENSE](LICENSE) and [NOTICE](NOTICE) for the complete license and attribution notices.
