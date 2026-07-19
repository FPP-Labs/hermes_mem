# Hermes Mem Beta 0.1

Hermes Mem is an independent community fork of [Hermes Agent](https://github.com/NousResearch/hermes-agent) focused on isolated local memory and a simplified desktop experience.

Hermes Mem Beta 0.1 uses the tested Hermes Agent `0.18.2` build pinned to commit `36f2a966c7f9f69987494b867c3dcf96b69a5766`. New upstream changes are not downloaded automatically.

## Install

Linux and macOS:

```bash
git clone https://github.com/FodorProPro/hermes_fpp.git && cd hermes_fpp && ./install.sh
```

Choose `1) Install`. The first installation downloads Hermes Agent, Python packages, Node.js packages, Chromium, and the desktop application, so it can take several minutes.

## Installer menu

```text
1) Install
2) Delete
3) Update
```

- Install creates or completes Hermes Mem Beta 0.1.
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

- scoped search across long-term facts, rolling 10-day memory, and events;
- long-term facts;
- active events;
- everything recorded today;
- the retained 10-day timeline;
- permanent deletion of all memory using `DELETE_ALL_MEMORY`.

Deleting memory does not delete regular Hermes Mem chat history. Deleting Hermes Mem from the installer removes the entire isolated Hermes Mem folder, including its chats and memory.

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
