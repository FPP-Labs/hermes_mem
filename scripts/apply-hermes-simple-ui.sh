#!/usr/bin/env bash
set -Eeuo pipefail

HERMES_ROOT="${HERMES_ROOT:-"$HOME/.hermes-mem/hermes/hermes-agent"}"
DESKTOP_DIR="$HERMES_ROOT/apps/desktop"
DO_PACK=0

usage() {
  cat <<EOF
Apply the minimal Hermes Desktop UI patch.

Usage:
  scripts/apply-hermes-simple-ui.sh [--pack]

Options:
  --pack       Rebuild the launchable Desktop app after patching
  -h, --help   Show this help

Environment:
  HERMES_ROOT=/path/to/hermes-agent
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --pack)
      DO_PACK=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'ERROR: unknown option: %s\n' "$1" >&2
      exit 1
      ;;
  esac
  shift
done

[ -d "$DESKTOP_DIR/src" ] || {
  printf 'ERROR: Hermes Desktop source not found: %s\n' "$DESKTOP_DIR" >&2
  exit 1
}

python3 - "$DESKTOP_DIR" <<'PY'
from pathlib import Path
import json
import re
import sys

desktop = Path(sys.argv[1])
hermes_root = desktop.parent.parent

package_json = desktop / "package.json"
package_data = json.loads(package_json.read_text(encoding="utf-8"))
package_data["version"] = "0.1.0-beta.1"
package_data["productName"] = "Hermes Mem"
package_data["description"] = "Independent community edition based on Hermes Agent by Nous Research."
build = package_data.setdefault("build", {})
build["appId"] = "app.hermesmem.desktop"
build["productName"] = "Hermes Mem"
build["artifactName"] = "Hermes-Mem-Beta-0.1-${os}-${arch}.${ext}"
build["protocols"] = [{"name": "Hermes Mem Protocol", "schemes": ["hermes-mem"]}]
mac = build.setdefault("mac", {})
extend_info = mac.setdefault("extendInfo", {})
extend_info["CFBundleDisplayName"] = "Hermes Mem"
extend_info["CFBundleName"] = "Hermes Mem"
package_json.write_text(json.dumps(package_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

legacy_settings = desktop / "src/app/settings/fpp-settings.tsx"
mem_settings_path = desktop / "src/app/settings/mem-settings.tsx"
if legacy_settings.exists():
    migrated_text = legacy_settings.read_text(encoding="utf-8")
    migrated_text = migrated_text.replace("FPP", "MEM").replace("Fpp", "Mem").replace("fpp", "mem")
    mem_settings_path.write_text(migrated_text, encoding="utf-8")
    legacy_settings.unlink()

legacy_privacy_test = hermes_root / "tests/tui_gateway/test_fpp_temporary_chat.py"
mem_privacy_test = hermes_root / "tests/tui_gateway/test_mem_temporary_chat.py"
if legacy_privacy_test.exists():
    migrated_text = legacy_privacy_test.read_text(encoding="utf-8")
    migrated_text = migrated_text.replace("FPP", "MEM").replace("Fpp", "Mem").replace("fpp", "mem")
    mem_privacy_test.parent.mkdir(parents=True, exist_ok=True)
    mem_privacy_test.write_text(migrated_text, encoding="utf-8")
    legacy_privacy_test.unlink()

for legacy_path in (
    desktop / "src/app/chat/sidebar/sidebar.tsx",
    desktop / "src/store/layout.ts",
    desktop / "src/app/settings/types.ts",
    desktop / "src/app/settings/index.tsx",
    desktop / "src/themes/context.tsx",
    desktop / "src/styles.css",
):
    if not legacy_path.exists():
        continue
    migrated_text = legacy_path.read_text(encoding="utf-8")
    if "FPP" not in migrated_text and "Fpp" not in migrated_text and "fpp" not in migrated_text:
        continue
    migrated_text = migrated_text.replace("FPP", "MEM").replace("Fpp", "Mem").replace("fpp", "mem")
    legacy_path.write_text(migrated_text, encoding="utf-8")

def replace(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        return
    path.write_text(text.replace(old, new), encoding="utf-8")

def ensure_named_import(text: str, module: str, names: list[str]) -> str:
    pattern = re.compile(rf"^import \{{([^}}]+)\}} from '{re.escape(module)}'$", re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return text

    existing = [item.strip() for item in match.group(1).split(",") if item.strip()]
    for name in names:
        if name not in existing:
            existing.append(name)

    return text[: match.start(1)] + " " + ", ".join(existing) + " " + text[match.end(1) :]

icons = desktop / "src/lib/icons.ts"
icons_text = icons.read_text(encoding="utf-8")
if "IconSparkles as Sparkles" not in icons_text:
    icons_text = icons_text.replace(
        "  IconSettings2 as Settings2,\n",
        "  IconSettings2 as Settings2,\n  IconSparkles as Sparkles,\n",
    )
if re.search(r"^\s*Sparkles,\s*$", icons_text, re.MULTILINE) is None:
    icons_text = icons_text.replace("  Settings2,\n", "  Settings2,\n  Sparkles,\n")
icons.write_text(icons_text, encoding="utf-8")

chat_messages = desktop / "src/lib/chat-messages.ts"
chat_messages_text = chat_messages.read_text(encoding="utf-8")
if "MODEL_SWITCH_MARKER_RE" not in chat_messages_text:
    chat_messages_text = chat_messages_text.replace(
        "export type ChatMessage = {\n",
        "const MODEL_SWITCH_MARKER_RE = /^\\[System: The active model for this chat has changed to [\\s\\S]+?\\. From this point forward, use this runtime metadata when answering questions about what model\\/provider is active\\.\\]$/\n\nexport type ChatMessage = {\n",
    )
chat_messages_text = chat_messages_text.replace(
    """    result.push({
      id: `${message.timestamp || Date.now()}-${index}-${message.role}`,
      role: message.role,
      parts,
      timestamp: message.timestamp
    })""",
    """    result.push({
      id: `${message.timestamp || Date.now()}-${index}-${message.role}`,
      role: message.role,
      parts,
      timestamp: message.timestamp,
      hidden: message.role === 'user' && MODEL_SWITCH_MARKER_RE.test(displayContent.trim())
    })""",
)
chat_messages_text = chat_messages_text.replace(
    "      hidden: message.role === 'user' && MODEL_SWITCH_MARKER_RE.test(displayContent.trim()),\n      hidden: message.role === 'user' && MODEL_SWITCH_MARKER_RE.test(displayContent.trim())",
    "      hidden: message.role === 'user' && MODEL_SWITCH_MARKER_RE.test(displayContent.trim())",
)
chat_messages.write_text(chat_messages_text, encoding="utf-8")

sidebar = desktop / "src/app/chat/sidebar/index.tsx"
replace(
    sidebar,
    "import { type AppView, ARTIFACTS_ROUTE, MESSAGING_ROUTE, SKILLS_ROUTE } from '../../routes'",
    "import { type AppView } from '../../routes'",
)
replace(
    sidebar,
    """const SIDEBAR_NAV: SidebarNavItem[] = [
  {
    id: 'new-session',
    label: '',
    icon: props => <Codicon name="robot" {...props} />,
    action: 'new-session'
  },
  {
    id: 'skills',
    label: '',
    icon: props => <Codicon name="symbol-misc" {...props} />,
    route: SKILLS_ROUTE
  },
  { id: 'messaging', label: '', icon: props => <Codicon name="comment" {...props} />, route: MESSAGING_ROUTE },
  { id: 'artifacts', label: '', icon: props => <Codicon name="files" {...props} />, route: ARTIFACTS_ROUTE }
]""",
    """const SIDEBAR_NAV: SidebarNavItem[] = [
  {
    id: 'new-session',
    label: '',
    icon: props => <Codicon name="robot" {...props} />,
    action: 'new-session'
  },
]""",
)
replace(sidebar, "  const trimmedQuery = searchQuery.trim()", "  const trimmedQuery = ''")
replace(
    sidebar,
    """  const unpinnedAgentSessions = useMemo(
    () => sortedSessions.filter(s => !pinnedRealIdSet.has(s.id)),
    [sortedSessions, pinnedRealIdSet]
  )""",
    """  const unpinnedAgentSessions = useMemo(
    () => sortedSessions.filter(s => !pinnedRealIdSet.has(s.id)),
    [sortedSessions, pinnedRealIdSet]
  )""",
)
replace(
    sidebar,
    "  const unpinnedAgentSessions = useMemo(() => sortedSessions, [sortedSessions])",
    """  const unpinnedAgentSessions = useMemo(
    () => sortedSessions.filter(s => !pinnedRealIdSet.has(s.id)),
    [sortedSessions, pinnedRealIdSet]
  )""",
)
replace(
    sidebar,
    "        {contentVisible && showSessionSections && (\n          <div className=\"shrink-0 px-2 pb-1 pt-1\">",
    "        {false && contentVisible && showSessionSections && (\n          <div className=\"shrink-0 px-2 pb-1 pt-1\">",
)
replace(
    sidebar,
    "            {!trimmedQuery && (\n              <SidebarSessionsSection\n                activeSessionId={activeSidebarSessionId}\n                contentClassName={cn('flex max-h-44 flex-col gap-px rounded-lg pb-2 pt-1', GROUP_BODY)}",
    "            {!trimmedQuery && (\n              <SidebarSessionsSection\n                activeSessionId={activeSidebarSessionId}\n                contentClassName={cn('flex max-h-44 flex-col gap-px rounded-lg pb-2 pt-1', GROUP_BODY)}",
)
replace(
    sidebar,
    "            {false && !trimmedQuery && (\n              <SidebarSessionsSection\n                activeSessionId={activeSidebarSessionId}\n                contentClassName={cn('flex max-h-44 flex-col gap-px rounded-lg pb-2 pt-1', GROUP_BODY)}",
    "            {!trimmedQuery && (\n              <SidebarSessionsSection\n                activeSessionId={activeSidebarSessionId}\n                contentClassName={cn('flex max-h-44 flex-col gap-px rounded-lg pb-2 pt-1', GROUP_BODY)}",
)
replace(sidebar, "import { ProfileRail } from './profile-switcher'\n", "")
replace(
    sidebar,
    """        {contentVisible && (
          <div className="shrink-0 px-0.5 pb-1 pt-0.5">
            <ProfileRail />
          </div>
        )}
""",
    "",
)
replace(
    sidebar,
    """        <div className="shrink-0 px-0.5 pb-1 pt-0.5">
          <ProfileRail />
        </div>
""",
    "",
)

sidebar_text = sidebar.read_text(encoding="utf-8")
sidebar_text = sidebar_text.replace("import { useContributions } from '@/contrib/react/use-contributions'\n", "")
sidebar_text = re.sub(
    r"import \{\n  type AppView,[\s\S]*?\n\} from '../../routes'",
    "import { type AppView } from '../../routes'",
    sidebar_text,
    count=1,
)
sidebar_text = re.sub(
    r"(?:// MEM_SIDEBAR_NAV:[^\n]*\n)*const SIDEBAR_NAV: SidebarNavItem\[\] = \[[\s\S]*?\n\]\n\n// Two modes",
    """// MEM_SIDEBAR_NAV: intentionally minimal on Linux and macOS.
const SIDEBAR_NAV: SidebarNavItem[] = [
  {
    id: 'new-session',
    label: '',
    icon: props => <Codicon name="robot" {...props} />,
    action: 'new-session',
    keybindActionId: 'session.new'
  }
]

// Two modes""",
    sidebar_text,
    count=1,
)
sidebar_text = re.sub(
    r"  // Contributed nav rows \(plugins pairing a page with a sidebar entry\)[\s\S]*?\n  const panesFlipped =",
    """  // MEM keeps optional workspace panels in Settings > Hidden Panels.
  const contributedNav: SidebarNavItem[] = []

  const panesFlipped =""",
    sidebar_text,
    count=1,
)
sidebar.write_text(sidebar_text, encoding="utf-8")

section_states = desktop / "src/app/chat/sidebar/section-states.tsx"
section_states_text = section_states.read_text(encoding="utf-8")
section_states_text = section_states_text.replace("import { Button } from '@/components/ui/button'\n", "")
section_states_text = re.sub(
    r"export function SidebarBlankState\([\s\S]*?\n\}\n\nexport function SidebarPinnedEmptyState",
    """export function SidebarBlankState({ onNewProject: _onNewProject }: { onNewProject: () => void }) {
  const { t } = useI18n()

  return (
    <div className="grid min-h-0 flex-1 place-items-center px-4 text-center">
      <div className="flex flex-col items-center gap-2">
        <Codicon className="text-(--ui-text-quaternary)" name="comment-discussion" size="1.25rem" />
        <p className="text-xs text-(--ui-text-tertiary)">{t.sidebar.noSessions}</p>
      </div>
    </div>
  )
}

export function SidebarPinnedEmptyState""",
    section_states_text,
    count=1,
)
section_states.write_text(section_states_text, encoding="utf-8")

titlebar = desktop / "src/app/shell/titlebar-controls.tsx"
text = titlebar.read_text(encoding="utf-8")
text = text.replace("import { $hapticsMuted, toggleHapticsMuted } from '@/store/haptics'\n", "")
text = text.replace("import { toggleKeybindPanel } from '@/store/keybinds'\n", "")
text = text.replace(
    """import {
  $fileBrowserOpen,
  $panesFlipped,
  $sidebarOpen,
  toggleFileBrowserOpen,
  togglePanesFlipped,
  toggleSidebarOpen
} from '@/store/layout'""",
    "import { $sidebarOpen, toggleSidebarOpen } from '@/store/layout'",
)
text = text.replace("  const hapticsMuted = useStore($hapticsMuted)\n", "")
text = text.replace("  const fileBrowserOpen = useStore($fileBrowserOpen)\n", "")
text = text.replace("  const panesFlipped = useStore($panesFlipped)\n\n", "")
start = text.find("  const toggleHaptics = () => {")
end = text.find("  const leftToolbarTools: TitlebarTool[] = [", start)
if start != -1 and end != -1:
    text = text[:start] + text[end:]
text = text.replace(
    """  const fileBrowserEdge = { open: fileBrowserOpen, toggle: toggleFileBrowserOpen }
  const sessionsEdge = { open: sidebarOpen, toggle: toggleSidebarOpen }
  const leftEdge = panesFlipped ? fileBrowserEdge : sessionsEdge
  const rightEdge = panesFlipped ? sessionsEdge : fileBrowserEdge

""",
    "",
)
text = text.replace("      label: leftEdge.open ? t.titlebar.hideSidebar : t.titlebar.showSidebar,", "      label: sidebarOpen ? t.titlebar.hideSidebar : t.titlebar.showSidebar,")
text = text.replace("        leftEdge.toggle()", "        toggleSidebarOpen()")
text = text.replace(
    """    {
      icon: <Codicon name="arrow-swap" />,
      id: 'flip-panes',
      label: t.titlebar.swapSidebarSides,
      onSelect: () => {
        triggerHaptic('tap')
        togglePanesFlipped()
      },
      title: t.titlebar.swapSidebarSidesTitle
    },
""",
    "",
)
start = text.find("  const rightSidebarTool: TitlebarTool = {")
end = text.find("  // Static system tools", start)
if start != -1 and end != -1:
    text = text[:start] + text[end:]
text = text.replace(
    """    {
      active: hapticsMuted,
      icon: <Codicon name={hapticsMuted ? 'mute' : 'unmute'} />,
      id: 'haptics',
      label: hapticsMuted ? t.titlebar.unmuteHaptics : t.titlebar.muteHaptics,
      onSelect: toggleHaptics
    },
    {
      icon: <Codicon name="keyboard" />,
      id: 'keybinds',
      label: t.titlebar.openKeybinds,
      onSelect: () => {
        triggerHaptic('open')
        toggleKeybindPanel()
      }
    },
""",
    "",
)
text = re.sub(
    r"\n    \{\n      active: hapticsMuted,\n      icon: <Codicon name=\{hapticsMuted \? 'mute' : 'unmute'\} />,\n      id: 'haptics',\n      label: hapticsMuted \? t\.titlebar\.unmuteHaptics : t\.titlebar\.muteHaptics,\n      onSelect: toggleHaptics\n    \},",
    "",
    text,
)
text = text.replace("        <TitlebarToolButton navigate={navigate} tool={rightSidebarTool} />\n", "")
text = text.replace(
    "const visibleSystemTools = systemTools.filter(tool => !tool.hidden)",
    "const visibleSystemTools = systemTools.filter(tool => !tool.hidden && tool.id === 'settings')",
)
text = text.replace(
    ".filter(tool => !tool.hidden)\n          .map(tool => (",
    ".filter(tool => !tool.hidden && tool.id === 'sidebar')\n          .map(tool => (",
)
titlebar.write_text(text, encoding="utf-8")

layout_store = desktop / "src/store/layout.ts"
layout_store_text = layout_store.read_text(encoding="utf-8")
if "MEM_FILE_BROWSER_HIDDEN" not in layout_store_text:
    layout_store_text = layout_store_text.replace(
        """ensurePaneRegistered(CHAT_SIDEBAR_PANE_ID, { open: true })
ensurePaneRegistered(FILE_BROWSER_PANE_ID, { open: false })
ensurePaneRegistered(PREVIEW_PANE_ID, { open: true })""",
        """ensurePaneRegistered(CHAT_SIDEBAR_PANE_ID, { open: true })
ensurePaneRegistered(FILE_BROWSER_PANE_ID, { open: false })
ensurePaneRegistered(PREVIEW_PANE_ID, { open: true })

// MEM_FILE_BROWSER_HIDDEN: migrate existing installations once so the main
// chat opens cleanly. Afterwards the user's choice in Settings > Hidden Panels
// is preserved normally across launches.
const MEM_FILE_BROWSER_HIDDEN_KEY = 'hermes.mem.fileBrowserHidden.v1'

if (typeof window !== 'undefined') {
  try {
    if (window.localStorage.getItem(MEM_FILE_BROWSER_HIDDEN_KEY) !== '1') {
      setPaneOpen(FILE_BROWSER_PANE_ID, false)
      window.localStorage.setItem(MEM_FILE_BROWSER_HIDDEN_KEY, '1')
    }
  } catch {
    setPaneOpen(FILE_BROWSER_PANE_ID, false)
  }
}""",
        1,
    )
layout_store.write_text(layout_store_text, encoding="utf-8")

app_shell = desktop / "src/app/shell/app-shell.tsx"
if not app_shell.exists():
    app_shell = desktop / "src/app/contrib/controller.tsx"
replace(
    app_shell,
    """  const titlebarToolsWidth =
    paneToolCount > 0
      ? `calc(${previewToolbarGap} + ${paneToolCount} * (var(--titlebar-control-size) + 0.25rem))`
      : systemToolsWidth""",
    """  const titlebarToolsWidth =
    paneToolCount > 0
      ? `calc(${previewToolbarGap} + ${paneToolCount} * (var(--titlebar-control-size) + 0.25rem))`
      : systemToolsWidth
  const showStatusbar = false""",
)
replace(
    app_shell,
    "        {!isSecondaryWindow() && <StatusbarControls items={statusbarItems} leftItems={leftStatusbarItems} />}",
    """        {showStatusbar && !isSecondaryWindow() && (
          <StatusbarControls items={statusbarItems} leftItems={leftStatusbarItems} />
        )}""",
)
replace(
    app_shell,
    '          <WiredPane part="statusbar" />',
    '          {false && <WiredPane part="statusbar" />}',
)

session_actions = desktop / "src/app/chat/sidebar/session-actions-menu.tsx"
replace(
    session_actions,
    "      {renderMenuItem(Item, pinItem)}",
    "      {onPin ? renderMenuItem(Item, pinItem) : null}",
)

session_row = desktop / "src/app/chat/sidebar/session-row.tsx"
replace(
    session_row,
    """            if (event.shiftKey) {
              event.preventDefault()
              event.stopPropagation()
              triggerHaptic('selection')
              onPin()

              return
            }

""",
    """            if (event.shiftKey) {
              event.preventDefault()
              event.stopPropagation()
              triggerHaptic('selection')
              onPin()

              return
            }

""",
)
replace(
    session_row,
    "      title={title}\n    >",
    "      title={title}\n      onPin={onPin}\n    >",
)
replace(
    session_row,
    "              title={title}\n            >",
    "              title={title}\n              onPin={onPin}\n            >",
)
replace(
    session_row,
    "      onPin={onPin}\n      onPin={onPin}\n",
    "      onPin={onPin}\n",
)
replace(
    session_row,
    "                      pinned={isPinned}",
    "              pinned={isPinned}",
)

session_row_text = session_row.read_text(encoding="utf-8")
session_row_text = session_row_text.replace(
    """      title={title}
      onPin={onPin}
    >""",
    """      title={title}
    >""",
)
session_row_text = session_row_text.replace(
    """              title={title}
              onPin={onPin}
            >""",
    """              title={title}
            >""",
)
if "if (event.shiftKey)" not in session_row_text:
    session_row_text = session_row_text.replace(
        """            onResume()
          }}""",
        """            if (event.shiftKey) {
              event.preventDefault()
              event.stopPropagation()
              triggerHaptic('selection')
              onPin()

              return
            }

            onResume()
          }}""",
    )
session_row.write_text(session_row_text, encoding="utf-8")

en = desktop / "src/i18n/en.ts"
replace(en, "      'new-session': 'New session',", "      'new-session': 'New chat',")

types = desktop / "src/app/settings/types.ts"
replace(
    types,
    """  | 'gateway'
  | 'keys'""",
    """  | 'gateway'
  | 'mem'
  | 'hidden-panels'
  | 'keys'""",
)
replace(
    types,
    """  | 'gateway'
  | 'hidden-panels'
  | 'keys'""",
    """  | 'gateway'
  | 'mem'
  | 'hidden-panels'
  | 'keys'""",
)

settings_index = desktop / "src/app/settings/index.tsx"
replace(
    settings_index,
    "import { Archive, Bell, Globe, Info, KeyRound, Settings2, Sparkles, Wrench, Zap } from '@/lib/icons'",
    "import { Archive, Bell, Brain, Globe, Info, KeyRound, Layers3, Settings2, Sparkles, Wrench, Zap } from '@/lib/icons'",
)
replace(
    settings_index,
    "import { Archive, Bell, Globe, Info, KeyRound, Layers3, Settings2, Sparkles, Wrench, Zap } from '@/lib/icons'",
    "import { Archive, Bell, Brain, Globe, Info, KeyRound, Layers3, Settings2, Sparkles, Wrench, Zap } from '@/lib/icons'",
)
replace(
    settings_index,
    "import { GatewaySettings } from './gateway-settings'\n",
    "import { GatewaySettings } from './gateway-settings'\nimport { MemSettings } from './mem-settings'\nimport { HiddenPanelsSettings } from './hidden-panels-settings'\n",
)
replace(
    settings_index,
    "import { GatewaySettings } from './gateway-settings'\nimport { HiddenPanelsSettings } from './hidden-panels-settings'\n",
    "import { GatewaySettings } from './gateway-settings'\nimport { MemSettings } from './mem-settings'\nimport { HiddenPanelsSettings } from './hidden-panels-settings'\n",
)
replace(
    settings_index,
    """  'gateway',
  'keys',""",
    """  'gateway',
  'mem',
  'hidden-panels',
  'keys',""",
)
replace(
    settings_index,
    """  'gateway',
  'hidden-panels',
  'keys',""",
    """  'gateway',
  'mem',
  'hidden-panels',
  'keys',""",
)
replace(
    settings_index,
    """          <OverlayNavItem
            active={activeView === 'mcp'}
            icon={Wrench}
            label={t.settings.nav.mcp}
            onClick={() => setActiveView('mcp')}
          />
          <OverlayNavItem
            active={activeView === 'sessions'}""",
    """          <OverlayNavItem
            active={activeView === 'mcp'}
            icon={Wrench}
            label={t.settings.nav.mcp}
            onClick={() => setActiveView('mcp')}
          />
          <OverlayNavItem
            active={activeView === 'mem'}
            icon={Brain}
            label="Hermes Mem"
            onClick={() => setActiveView('mem')}
          />
          <OverlayNavItem
            active={activeView === 'hidden-panels'}
            icon={Layers3}
            label="Hidden Panels"
            onClick={() => setActiveView('hidden-panels')}
          />
          <OverlayNavItem
            active={activeView === 'sessions'}""",
)
replace(
    settings_index,
    """          <OverlayNavItem
            active={activeView === 'mcp'}
            icon={Wrench}
            label={t.settings.nav.mcp}
            onClick={() => setActiveView('mcp')}
          />
          <OverlayNavItem
            active={activeView === 'hidden-panels'}""",
    """          <OverlayNavItem
            active={activeView === 'mcp'}
            icon={Wrench}
            label={t.settings.nav.mcp}
            onClick={() => setActiveView('mcp')}
          />
          <OverlayNavItem
            active={activeView === 'mem'}
            icon={Brain}
            label="Hermes Mem"
            onClick={() => setActiveView('mem')}
          />
          <OverlayNavItem
            active={activeView === 'hidden-panels'}""",
)
replace(
    settings_index,
    """          ) : activeView === 'mcp' ? (
            <McpSettings gateway={gateway} onConfigSaved={onConfigSaved} />
          ) : activeView === 'notifications' ? (""",
    """          ) : activeView === 'mcp' ? (
            <McpSettings gateway={gateway} onConfigSaved={onConfigSaved} />
          ) : activeView === 'mem' ? (
            <MemSettings onConfigSaved={onConfigSaved} />
          ) : activeView === 'hidden-panels' ? (
            <HiddenPanelsSettings />
          ) : activeView === 'notifications' ? (""",
)
replace(
    settings_index,
    """          ) : activeView === 'mcp' ? (
            <McpSettings gateway={gateway} onConfigSaved={onConfigSaved} />
          ) : activeView === 'hidden-panels' ? (""",
    """          ) : activeView === 'mcp' ? (
            <McpSettings gateway={gateway} onConfigSaved={onConfigSaved} />
          ) : activeView === 'mem' ? (
            <MemSettings onConfigSaved={onConfigSaved} />
          ) : activeView === 'hidden-panels' ? (""",
)

replace(
    settings_index,
    """          ) : activeView === 'mcp' ? (
            <McpSettings gateway={gateway} onConfigSaved={onConfigSaved} />
          ) : activeView === 'notifications' ? (""",
    """          ) : activeView === 'mcp' ? (
            <McpSettings gateway={gateway} onConfigSaved={onConfigSaved} />
          ) : activeView === 'mem' ? (
            <MemSettings onConfigSaved={onConfigSaved} />
          ) : activeView === 'notifications' ? (""",
)

replace(
    types,
    """  | 'gateway'
  | 'keybinds'""",
    """  | 'gateway'
  | 'mem'
  | 'hidden-panels'
  | 'keybinds'""",
)
replace(
    settings_index,
    """  'providers',
  'gateway',
  'keybinds',""",
    """  'providers',
  'gateway',
  'mem',
  'hidden-panels',
  'keybinds',""",
)
replace(
    settings_index,
    """    {
      active: activeView === 'gateway',
      icon: Globe,
      id: 'gateway',
      label: t.settings.nav.gateway,
      onSelect: () => setActiveView('gateway')
    },
    {
      active: activeView === 'keybinds',""",
    """    {
      active: activeView === 'gateway',
      icon: Globe,
      id: 'gateway',
      label: t.settings.nav.gateway,
      onSelect: () => setActiveView('gateway')
    },
    {
      active: activeView === 'mem',
      icon: Brain,
      id: 'mem',
      label: 'Hermes Mem',
      onSelect: () => setActiveView('mem')
    },
    {
      active: activeView === 'hidden-panels',
      icon: Layers3,
      id: 'hidden-panels',
      label: 'Hidden Panels',
      onSelect: () => setActiveView('hidden-panels')
    },
    {
      active: activeView === 'keybinds',""",
)
replace(
    settings_index,
    """          ) : activeView === 'gateway' ? (
            <GatewaySettings />
          ) : activeView === 'keybinds' ? (""",
    """          ) : activeView === 'gateway' ? (
            <GatewaySettings />
          ) : activeView === 'mem' ? (
            <MemSettings onConfigSaved={onConfigSaved} />
          ) : activeView === 'hidden-panels' ? (
            <HiddenPanelsSettings />
          ) : activeView === 'keybinds' ? (""",
)

memory_dashboard_settings = desktop / "src/app/settings/memory-dashboard-settings.tsx"
memory_dashboard_settings.write_text(r'''import { useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Brain, Clock, RefreshCw, Search, Trash2 } from '@/lib/icons'
import { notify, notifyError } from '@/store/notifications'

import { Pill } from './primitives'

type MemoryScope = 'all' | 'long-term' | '10-day' | 'events'

interface MemorySearchItem {
  id?: string
  type?: string
  day?: string
  text?: string
  title?: string
  created_at?: string
  updated_at?: string
}

interface MemoryChunk {
  id: string
  text: string
  created_at?: string
}

interface MemoryDay {
  day: string
  chars: number
  chunks: MemoryChunk[]
}

interface ForeverFact {
  id: string
  fact: string
  category?: string
  importance?: number
}

interface ActiveEvent {
  id: string
  title: string
  description?: string
  summary?: string
  start_at?: string
  end_at?: string
}

interface MemoryDashboardData {
  today: { date: string; human: string; timezone: string }
  today_memory: MemoryDay
  ten_day_memory: MemoryDay[]
  forever_facts: ForeverFact[]
  active_events: ActiveEvent[]
  search: { query: string; scope: MemoryScope; results: MemorySearchItem[] }
  health: { active_chunks?: number; chat_sessions?: number; chat_notes?: number }
}

function memoryLabel(type?: string) {
  const labels: Record<string, string> = {
    chat_note: '10-day chat note',
    chat_session: '10-day chat',
    day_chunk: '10-day detail',
    event: 'Event',
    event_trace: 'Event trace',
    forever_fact: 'Long-term fact'
  }
  return labels[type || ''] || type || 'Memory'
}

function MemoryText({ text, meta }: { text: string; meta?: string }) {
  return (
    <div className="rounded-lg border border-(--ui-stroke-tertiary) bg-(--ui-bg-secondary) px-3 py-2.5">
      {meta && <div className="mb-1 text-[0.7rem] font-medium text-(--ui-text-tertiary)">{meta}</div>}
      <div className="whitespace-pre-wrap break-words text-[length:var(--conversation-caption-font-size)] leading-(--conversation-caption-line-height) text-(--ui-text-secondary)">
        {text}
      </div>
    </div>
  )
}

export function MemoryDashboardSettings() {
  const [dashboard, setDashboard] = useState<MemoryDashboardData | null>(null)
  const [query, setQuery] = useState('')
  const [scope, setScope] = useState<MemoryScope>('all')
  const [loading, setLoading] = useState(true)
  const [deleting, setDeleting] = useState(false)
  const [confirmation, setConfirmation] = useState('')

  const loadMemory = async (nextQuery = query, nextScope = scope) => {
    setLoading(true)
    try {
      const data = (await window.hermesDesktop.memory.dashboard({
        query: nextQuery.trim(),
        scope: nextScope
      })) as MemoryDashboardData
      setDashboard(data)
    } catch (err) {
      notifyError(err, 'Failed to load memory')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadMemory('', 'all')
  }, [])

  const clearMemory = async () => {
    if (confirmation !== 'DELETE_ALL_MEMORY') {
      return
    }
    setDeleting(true)
    try {
      await window.hermesDesktop.memory.clearAll({ confirmation })
      setConfirmation('')
      setQuery('')
      triggerReload()
      notify({ kind: 'success', title: 'Memory deleted', message: 'All Hermes Mem records were deleted.' })
    } catch (err) {
      notifyError(err, 'Failed to delete memory')
    } finally {
      setDeleting(false)
    }
  }

  const triggerReload = () => {
    void loadMemory('', scope)
  }

  const searchResults = dashboard?.search.results || []
  const todayChunks = dashboard?.today_memory.chunks || []

  return (
    <div className="mt-5 space-y-5">
      <div>
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <div className="inline-flex items-center gap-2 text-[length:var(--conversation-caption-font-size)] font-medium text-(--ui-text-secondary)">
            <Brain className="size-4" />
            Memory overview
          </div>
          <Button disabled={loading} onClick={triggerReload} size="sm" type="button" variant="outline">
            <RefreshCw className="mr-1.5 size-3.5" />
            Refresh
          </Button>
        </div>
        <div className="flex flex-wrap gap-2">
          <Pill>{dashboard?.forever_facts.length || 0} long-term facts</Pill>
          <Pill>{dashboard?.ten_day_memory.length || 0} retained days</Pill>
          <Pill>{dashboard?.active_events.length || 0} active events</Pill>
          {dashboard?.today && <Pill>{dashboard.today.timezone}</Pill>}
        </div>
      </div>

      <div>
        <div className="mb-2 text-[length:var(--conversation-caption-font-size)] font-medium text-(--ui-text-secondary)">
          Search memory
        </div>
        <div className="flex flex-col gap-2 @2xl:flex-row">
          <Input
            aria-label="Search memory"
            onChange={event => setQuery(event.currentTarget.value)}
            onKeyDown={event => {
              if (event.key === 'Enter') {
                void loadMemory()
              }
            }}
            placeholder="Search facts, events, chats, and daily memory"
            value={query}
          />
          <div className="flex gap-1">
            {(['all', 'long-term', '10-day', 'events'] as const).map(value => (
              <Button
                key={value}
                onClick={() => {
                  setScope(value)
                  void loadMemory(query, value)
                }}
                size="sm"
                type="button"
                variant={scope === value ? 'default' : 'outline'}
              >
                {value === 'all' ? 'All' : value === 'long-term' ? 'Long-term' : value === '10-day' ? '10-day' : 'Events'}
              </Button>
            ))}
          </div>
          <Button disabled={loading} onClick={() => void loadMemory()} size="sm" type="button">
            <Search className="mr-1.5 size-3.5" />
            Search
          </Button>
        </div>
        {dashboard?.search.query && (
          <div className="mt-3 space-y-2">
            {searchResults.length ? (
              searchResults.map((item, index) => (
                <MemoryText
                  key={item.id || `${item.type}-${index}`}
                  meta={`${memoryLabel(item.type)}${item.day ? ` · ${item.day}` : ''}`}
                  text={item.text || item.title || 'Empty memory record'}
                />
              ))
            ) : (
              <div className="text-[length:var(--conversation-caption-font-size)] text-(--ui-text-tertiary)">
                No matching memory found.
              </div>
            )}
          </div>
        )}
      </div>

      <div>
        <div className="mb-2 inline-flex items-center gap-2 text-[length:var(--conversation-caption-font-size)] font-medium text-(--ui-text-secondary)">
          <Clock className="size-4" />
          Today · {dashboard?.today.date || '—'}
        </div>
        <div className="max-h-72 space-y-2 overflow-y-auto pr-1">
          {todayChunks.length ? (
            todayChunks.map(chunk => <MemoryText key={chunk.id} meta={chunk.created_at} text={chunk.text} />)
          ) : (
            <MemoryText text="Nothing has been recorded today." />
          )}
        </div>
      </div>

      <div className="grid gap-5 @3xl:grid-cols-2">
        <div>
          <div className="mb-2 text-[length:var(--conversation-caption-font-size)] font-medium text-(--ui-text-secondary)">
            Active events
          </div>
          <div className="max-h-72 space-y-2 overflow-y-auto pr-1">
            {dashboard?.active_events.length ? (
              dashboard.active_events.map(event => (
                <MemoryText
                  key={event.id}
                  meta={[event.start_at, event.end_at].filter(Boolean).join(' → ') || 'Active now'}
                  text={[event.title, event.summary || event.description].filter(Boolean).join('\n')}
                />
              ))
            ) : (
              <MemoryText text="No active events." />
            )}
          </div>
        </div>

        <div>
          <div className="mb-2 text-[length:var(--conversation-caption-font-size)] font-medium text-(--ui-text-secondary)">
            Long-term facts
          </div>
          <div className="max-h-72 space-y-2 overflow-y-auto pr-1">
            {dashboard?.forever_facts.length ? (
              dashboard.forever_facts.map(fact => (
                <MemoryText key={fact.id} meta={fact.category || 'fact'} text={fact.fact} />
              ))
            ) : (
              <MemoryText text="No long-term facts saved." />
            )}
          </div>
        </div>
      </div>

      <div>
        <div className="mb-2 text-[length:var(--conversation-caption-font-size)] font-medium text-(--ui-text-secondary)">
          Rolling 10-day memory
        </div>
        <div className="max-h-96 space-y-2 overflow-y-auto pr-1">
          {dashboard?.ten_day_memory.length ? (
            [...dashboard.ten_day_memory].reverse().map(day => (
              <MemoryText
                key={day.day}
                meta={`${day.day} · ${day.chunks.length} records · ${day.chars} characters`}
                text={day.chunks.map(chunk => chunk.text).join('\n\n') || 'No active records'}
              />
            ))
          ) : (
            <MemoryText text="No 10-day memory saved." />
          )}
        </div>
      </div>

      <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-3">
        <div className="mb-1 inline-flex items-center gap-2 text-[length:var(--conversation-caption-font-size)] font-medium text-red-400">
          <Trash2 className="size-4" />
          Delete all memory
        </div>
        <p className="mb-3 text-[length:var(--conversation-caption-font-size)] text-(--ui-text-tertiary)">
          This permanently deletes long-term facts, events, 10-day memory, and memory chat cards. Regular Hermes Mem chat history is not deleted.
        </p>
        <div className="flex flex-col gap-2 @2xl:flex-row">
          <Input
            onChange={event => setConfirmation(event.currentTarget.value)}
            placeholder="Type DELETE_ALL_MEMORY"
            value={confirmation}
          />
          <Button
            disabled={confirmation !== 'DELETE_ALL_MEMORY' || deleting}
            onClick={() => void clearMemory()}
            type="button"
            variant="destructive"
          >
            {deleting ? 'Deleting…' : 'Delete all memory'}
          </Button>
        </div>
      </div>
    </div>
  )
}
''', encoding="utf-8")

mem_settings = desktop / "src/app/settings/mem-settings.tsx"
mem_settings.write_text(r'''import { useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { getHermesConfigRecord, saveHermesConfig, setEnvVar } from '@/hermes'
import { triggerHaptic } from '@/lib/haptics'
import { Brain, Clock, KeyRound, Mic, Save } from '@/lib/icons'
import { notify, notifyError } from '@/store/notifications'

import { ListRow, SectionHeading, SettingsContent } from './primitives'
import { MemoryDashboardSettings } from './memory-dashboard-settings'

interface MemSettingsProps {
  onConfigSaved?: () => void
}

function setNestedConfigValue(config: Record<string, unknown>, path: string[], value: unknown) {
  let cursor = config

  for (const key of path.slice(0, -1)) {
    const next = cursor[key]

    if (!next || typeof next !== 'object' || Array.isArray(next)) {
      cursor[key] = {}
    }

    cursor = cursor[key] as Record<string, unknown>
  }

  cursor[path[path.length - 1]] = value
}

export function MemSettings({ onConfigSaved }: MemSettingsProps) {
  const [apiKey, setApiKey] = useState('')
  const [voiceId, setVoiceId] = useState('')
  const [timeoutSeconds, setTimeoutSeconds] = useState('300')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let cancelled = false

    getHermesConfigRecord()
      .then(config => {
        if (cancelled) {
          return
        }

        const tts = (config.tts ?? {}) as Record<string, unknown>
        const elevenlabs = (tts.elevenlabs ?? {}) as Record<string, unknown>
        setVoiceId(typeof elevenlabs.voice_id === 'string' ? elevenlabs.voice_id : '')

        const timeout = elevenlabs.timeout ?? elevenlabs.timeout_seconds
        if (typeof timeout === 'number' && Number.isFinite(timeout) && timeout > 0) {
          setTimeoutSeconds(String(timeout))
        } else if (typeof timeout === 'string' && timeout.trim()) {
          setTimeoutSeconds(timeout.trim())
        }
      })
      .catch(err => notifyError(err, 'Failed to load Hermes Mem settings'))
      .finally(() => {
        if (!cancelled) {
          setLoading(false)
        }
      })

    return () => {
      cancelled = true
    }
  }, [])

  const saveVoice = async () => {
    setSaving(true)

    try {
      if (apiKey.trim()) {
        await setEnvVar('ELEVENLABS_API_KEY', apiKey.trim())
        setApiKey('')
      }

      const config = await getHermesConfigRecord()
      setNestedConfigValue(config, ['tts', 'provider'], 'elevenlabs')
      setNestedConfigValue(config, ['tts', 'elevenlabs', 'model_id'], 'eleven_multilingual_v2')

      if (voiceId.trim()) {
        setNestedConfigValue(config, ['tts', 'elevenlabs', 'voice_id'], voiceId.trim())
      }

      const timeoutValue = Number(timeoutSeconds)
      if (Number.isFinite(timeoutValue) && timeoutValue > 0) {
        setNestedConfigValue(config, ['tts', 'elevenlabs', 'timeout'], Math.round(timeoutValue))
      }

      await saveHermesConfig(config)
      triggerHaptic('success')
      notify({ kind: 'success', title: 'Voice settings saved', message: 'ElevenLabs is configured for Hermes.' })
      onConfigSaved?.()
    } catch (err) {
      notifyError(err, 'Failed to save voice settings')
    } finally {
      setSaving(false)
    }
  }

  return (
    <SettingsContent>
      <SectionHeading icon={Brain} meta="Beta 0.1" title="Hermes Mem" />
      <p className="max-w-2xl text-[length:var(--conversation-caption-font-size)] leading-(--conversation-caption-line-height) text-(--ui-text-tertiary)">
        Independent community edition based on Hermes Agent by Nous Research, with clean chat, local memory, and voice settings.
      </p>

      <MemoryDashboardSettings />

      <div className="mt-5">
        <div className="mb-1.5 text-[length:var(--conversation-caption-font-size)] font-medium text-(--ui-text-secondary)">
          Voice
        </div>
        <div className="divide-y divide-(--ui-stroke-tertiary)">
          <ListRow
            action={
              <Input
                autoComplete="off"
                onChange={event => setApiKey(event.currentTarget.value)}
                placeholder="Leave empty to keep current key"
                type="password"
                value={apiKey}
              />
            }
            description="Saved to Hermes .env as ELEVENLABS_API_KEY."
            title={
              <span className="inline-flex min-w-0 items-center gap-2">
                <KeyRound className="size-4 shrink-0 text-muted-foreground" />
                <span className="truncate">ElevenLabs API key</span>
              </span>
            }
          />
          <ListRow
            action={
              <Input
                disabled={loading}
                onChange={event => setVoiceId(event.currentTarget.value)}
                placeholder="Voice ID"
                value={voiceId}
              />
            }
            description="Saved to Hermes config as tts.elevenlabs.voice_id."
            title={
              <span className="inline-flex min-w-0 items-center gap-2">
                <Mic className="size-4 shrink-0 text-muted-foreground" />
                <span className="truncate">Voice ID</span>
              </span>
            }
          />
          <ListRow
            action={
              <Input
                disabled={loading}
                min={10}
                onChange={event => setTimeoutSeconds(event.currentTarget.value)}
                placeholder="300"
                step={10}
                type="number"
                value={timeoutSeconds}
              />
            }
            description="Seconds to wait for ElevenLabs on long text generation."
            title={
              <span className="inline-flex min-w-0 items-center gap-2">
                <Clock className="size-4 shrink-0 text-muted-foreground" />
                <span className="truncate">Request timeout</span>
              </span>
            }
          />
          <ListRow
            action={
              <Button className="gap-1.5" disabled={saving || loading} onClick={() => void saveVoice()} type="button">
                <Save className="size-3.5" />
                Save voice
              </Button>
            }
            description="This also selects ElevenLabs as the active TTS provider."
            title="Apply voice settings"
          />
        </div>
      </div>
    </SettingsContent>
  )
}
''', encoding="utf-8")

speech_text = desktop / "src/lib/speech-text.ts"
speech_text.write_text(r'''const EMOJI_RE = /(?:[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}]|[\u{FE0F}\u{200D}]|[\u{E0020}-\u{E007F}])+/gu

const FENCED_CODE_RE = /```[\s\S]*?(?:```|$)/g
const INLINE_CODE_RE = /`[^`]*`/g
const HTML_BLOCK_RE = /<[^>\n]+>/g
const MARKDOWN_LINK_RE = /\[([^\]]+)\]\(([^)]+)\)/g
const URL_RE = /\bhttps?:\/\/\S+/gi
const PATH_RE = /(?:~|\.{1,2}|\/)?(?:\/[\p{L}\p{N}_ .@%+=:,~_-]+){1,}|\b[\w.-]+\.(?:py|ts|tsx|js|jsx|json|yaml|yml|toml|md|txt|log|sh|sqlite3?|db|env)\b/giu
const COMMAND_RE = /^\s*(?:\$|>|#)?\s*(?:sudo\s+)?(?:apt|dnf|pacman|emerge|npm|pnpm|yarn|pip|python3?|node|git|hermes|codex|curl|grep|rg|cd|cp|mv|rm|mkdir|chmod|chown|systemctl|journalctl|pkill)\b.*$/gim
const TOOL_LABEL_RE = /^\s*(?:result|tool|mcp|memory\.[\w.-]+|code|json|output|log|traceback)\s*:?\s*/gim
const BULLET_RE = /^\s*(?:[-+*•]|\d+[.)])\s+/gm
const HEADER_RE = /^\s{0,3}#{1,6}\s*/gm
const TABLE_LINE_RE = /^\s*\|.*\|\s*$/gm

const TECHNICAL_DETAILS = 'Technical details omitted.'

function normalizeTechnicalWords(text: string): string {
  return text
    .replace(/\bGPT[- ]?5\.5\b/gi, 'G P T five point five')
    .replace(/\bGPT[- ]?5\b/gi, 'G P T five')
    .replace(/\bCtrl\+V\b/gi, 'Control V')
    .replace(/\bCtrl\+C\b/gi, 'Control C')
    .replace(/\bCtrl\+Z\b/gi, 'Control Z')
    .replace(/\bAPI\b/g, 'A P I')
    .replace(/\bTTS\b/g, 'T T S')
    .replace(/\bMCP\b/g, 'M C P')
}

function cleanForVoice(text: string): string {
  let out = text
    .replace(/\r\n?/g, '\n')
    .replace(FENCED_CODE_RE, ` ${TECHNICAL_DETAILS} `)
    .replace(COMMAND_RE, ` ${TECHNICAL_DETAILS} `)
    .replace(TABLE_LINE_RE, ' ')
    .replace(HTML_BLOCK_RE, ' ')
    .replace(MARKDOWN_LINK_RE, '$1')
    .replace(URL_RE, ' ')
    .replace(INLINE_CODE_RE, ` ${TECHNICAL_DETAILS} `)
    .replace(PATH_RE, ` ${TECHNICAL_DETAILS} `)
    .replace(TOOL_LABEL_RE, ' ')
    .replace(HEADER_RE, '')
    .replace(BULLET_RE, '')
    .replace(EMOJI_RE, ' ')

  out = normalizeTechnicalWords(out)
  out = out
    .replace(/[,\u2013\u2014:;]+/g, ' ')
    .replace(/[*_#>|~\\[\](){}"`]/g, ' ')
    .replace(/[^\p{L}\p{N}.!? ]+/gu, ' ')
    .replace(/\.{2,}/g, '.')
    .replace(/[!?]{2,}/g, match => match[0])
    .replace(/\s*[.!?]\s*/g, match => `${match.trim()} `)
    .replace(/\s+/g, ' ')
    .trim()

  return out
}

export function prepareTextForTTS(text: string): string {
  const cleaned = cleanForVoice(text || '')

  if (!cleaned) {
    return ''
  }

  return cleaned
    .replace(/(?:Technical details omitted\.\s*){2,}/g, TECHNICAL_DETAILS)
    .replace(/\s+/g, ' ')
    .trim()
}

export const sanitizeTextForSpeech = prepareTextForTTS
''', encoding="utf-8")

store_session = desktop / "src/store/session.ts"
store_session_text = store_session.read_text(encoding="utf-8")
if "$temporaryChatMode" not in store_session_text:
    store_session_text = store_session_text.replace(
        "export const $messages = atom<ChatMessage[]>([])\n",
        """export const $messages = atom<ChatMessage[]>([])

export const $temporaryChatMode = atom(false)
export const setTemporaryChatMode = (enabled: boolean) => $temporaryChatMode.set(enabled)

const temporarySessionIds = new Set<string>()

export function markTemporarySession(sessionId: string | null | undefined) {
  if (sessionId) {
    temporarySessionIds.add(sessionId)
  }
}

export function clearTemporarySession(sessionId: string | null | undefined) {
  if (sessionId) {
    temporarySessionIds.delete(sessionId)
  }
}

export function isTemporarySession(sessionId: string | null | undefined): boolean {
  return Boolean(sessionId && temporarySessionIds.has(sessionId))
}

export function filterTemporarySessions<T extends { id?: string | null; _lineage_root_id?: string | null }>(
  sessions: T[]
): T[] {
  return sessions.filter(session => !isTemporarySession(session.id) && !isTemporarySession(session._lineage_root_id))
}
""",
    )
if "filterTemporarySessions" not in store_session_text:
    store_session_text = store_session_text.replace(
        """export function isTemporarySession(sessionId: string | null | undefined): boolean {
  return Boolean(sessionId && temporarySessionIds.has(sessionId))
}
""",
        """export function isTemporarySession(sessionId: string | null | undefined): boolean {
  return Boolean(sessionId && temporarySessionIds.has(sessionId))
}

export function filterTemporarySessions<T extends { id?: string | null; _lineage_root_id?: string | null }>(
  sessions: T[]
): T[] {
  return sessions.filter(session => !isTemporarySession(session.id) && !isTemporarySession(session._lineage_root_id))
}
""",
    )
store_session.write_text(store_session_text, encoding="utf-8")

types_hermes = desktop / "src/types/hermes.ts"
types_hermes_text = types_hermes.read_text(encoding="utf-8")
if "session_key?: string" not in types_hermes_text:
    types_hermes_text = types_hermes_text.replace(
        """  messages?: SessionMessage[]
  session_id: string
  stored_session_id?: string""",
        """  messages?: SessionMessage[]
  session_id: string
  session_key?: string
  stored_session_id?: string""",
        1,
    )
types_hermes.write_text(types_hermes_text, encoding="utf-8")

desktop_controller = desktop / "src/app/desktop-controller.tsx"
if not desktop_controller.exists():
    desktop_controller = desktop / "src/app/session/hooks/use-session-list-actions.ts"
desktop_controller_text = desktop_controller.read_text(encoding="utf-8")
if "filterTemporarySessions" not in desktop_controller_text:
    desktop_controller_text = desktop_controller_text.replace(
        """  CRON_SECTION_LIMIT,
  getRecentlySettledSessionIds,""",
        """  CRON_SECTION_LIMIT,
  filterTemporarySessions,
  getRecentlySettledSessionIds,""",
        1,
    )
if "filterTemporarySessions" not in desktop_controller_text:
    desktop_controller_text = desktop_controller_text.replace(
        "  CRON_SECTION_LIMIT,\n",
        "  CRON_SECTION_LIMIT,\n  filterTemporarySessions,\n",
        1,
    )
desktop_controller_text = desktop_controller_text.replace(
    "setSessions(prev => mergeSessionPage(prev, result.sessions, sessionsToKeep()))",
    "setSessions(prev => filterTemporarySessions(mergeSessionPage(prev, result.sessions, sessionsToKeep())))",
)
desktop_controller_text = desktop_controller_text.replace(
    """    setSessions(prev => [
      ...prev.filter(s => !inKey(s)),
      ...mergeSessionPage(prev.filter(inKey), result.sessions, keep)
    ])""",
    """    setSessions(prev =>
      filterTemporarySessions([
        ...prev.filter(s => !inKey(s)),
        ...mergeSessionPage(prev.filter(inKey), result.sessions, keep)
      ])
    )""",
)
desktop_controller.write_text(desktop_controller_text, encoding="utf-8")

context_menu = desktop / "src/app/chat/composer/context-menu.tsx"
context_menu_text = context_menu.read_text(encoding="utf-8")
context_menu_text = context_menu_text.replace(
    "import { Clipboard, FileText, FolderOpen, type IconComponent, ImageIcon, Link, MessageSquareText } from '@/lib/icons'",
    "import { Clipboard, Clock, FileText, FolderOpen, type IconComponent, ImageIcon, Link, MessageSquareText } from '@/lib/icons'",
)
if "temporaryChatActive," not in context_menu_text:
    context_menu_text = context_menu_text.replace(
        """  onOpenUrlDialog,
  onPasteClipboardImage,""",
        """  onOpenUrlDialog,
  onPasteClipboardImage,
  onStartTemporaryChat,
  temporaryChatActive,""",
    )
context_menu_text = re.sub(
    r"\n\s*(?:<DropdownMenuSeparator />\n\s*)?<ContextMenuItem icon=\{Clock\} onSelect=\{onStartTemporaryChat\}>[\s\S]*?</ContextMenuItem>",
    "",
    context_menu_text,
)
context_menu_text = re.sub(
    r"(\s*<ContextMenuItem icon=\{MessageSquareText\} onSelect=\{\(\) => setSnippetsOpen\(true\)\}>\n\s*\{c\.promptSnippets\}\n\s*</ContextMenuItem>)",
    r"""\1

          <ContextMenuItem icon={Clock} onSelect={onStartTemporaryChat}>
            {temporaryChatActive ? 'Temporary chat active' : 'Temporary chat'}
          </ContextMenuItem>""",
    context_menu_text,
    count=1,
)
if "temporaryChatActive?: boolean" not in context_menu_text:
    context_menu_text = context_menu_text.replace(
        """  onPasteClipboardImage?: (opts?: { silent?: boolean }) => Promise<boolean> | void
  onPickFiles?: () => void""",
        """  onPasteClipboardImage?: (opts?: { silent?: boolean }) => Promise<boolean> | void
  onStartTemporaryChat?: () => void
  temporaryChatActive?: boolean
  onPickFiles?: () => void""",
    )
context_menu.write_text(context_menu_text, encoding="utf-8")

composer_index = desktop / "src/app/chat/composer/index.tsx"
composer_index_text = composer_index.read_text(encoding="utf-8")
composer_index_text = composer_index_text.replace(
    "import { $gatewayState, $messages, setSessionPickerOpen } from '@/store/session'",
    "import { $gatewayState, $messages, $temporaryChatMode, setSessionPickerOpen, setTemporaryChatMode } from '@/store/session'",
)
composer_index_text = composer_index_text.replace(
    "import { $gatewayState } from '@/store/session'",
    "import { $gatewayState, $temporaryChatMode, setTemporaryChatMode } from '@/store/session'",
)
composer_index_lines = [
    line
    for line in composer_index_text.splitlines()
    if line
    not in {
        "import { Clock } from '@/lib/icons'",
        "import { XIcon } from '@/lib/icons'",
        "import { Clock, XIcon } from '@/lib/icons'",
    }
]
composer_index_text = "\n".join(composer_index_lines) + "\n"
composer_index_text = composer_index_text.replace(
    "import { triggerHaptic } from '@/lib/haptics'\n",
    "import { triggerHaptic } from '@/lib/haptics'\nimport { Clock, XIcon } from '@/lib/icons'\n",
    1,
)
if "const temporaryChatMode = useStore($temporaryChatMode)" not in composer_index_text:
    composer_index_text = composer_index_text.replace(
        "  const aui = useAui()\n  const draft = useAuiState(s => s.composer.text)",
        "  const aui = useAui()\n  const draft = useAuiState(s => s.composer.text)\n  const temporaryChatMode = useStore($temporaryChatMode)",
    )
if "const temporaryChatMode = useStore($temporaryChatMode)" not in composer_index_text:
    composer_index_text = composer_index_text.replace(
        "  const { t } = useI18n()\n",
        "  const { t } = useI18n()\n  const temporaryChatMode = useStore($temporaryChatMode)\n",
        1,
    )
if "onStartTemporaryChat={() =>" not in composer_index_text:
    composer_index_text = composer_index_text.replace(
        """      onPasteClipboardImage={onPasteClipboardImage}
      onPickFiles={onPickFiles}""",
        """      onPasteClipboardImage={onPasteClipboardImage}
      onStartTemporaryChat={() => {
        setTemporaryChatMode(true)
      }}
      temporaryChatActive={temporaryChatMode}
      onPickFiles={onPickFiles}""",
    )
composer_index_text = composer_index_text.replace(
    """      onStartTemporaryChat={() => {
        setTemporaryChatMode(true)
      }}""",
    """      onStartTemporaryChat={() => {
        setTemporaryChatMode(!temporaryChatMode)
      }}""",
)
composer_index_text = re.sub(
    r"\n    // Backspace right after a temporary-chat chip: if the input is empty,[\s\S]*?\n    // Plain Backspace right after a directive chip:",
    "\n    // Plain Backspace right after a directive chip:",
    composer_index_text,
)
composer_index_text = composer_index_text.replace(
    "        notify({ kind: 'success', title: 'Temporary chat', message: 'Memory and history are disabled for the next chat.' })\n",
    "",
)
if "data-slot=\"temporary-chat-chip\"" not in composer_index_text:
    composer_index_text = composer_index_text.replace(
        "                {attachments.length > 0 && <AttachmentList attachments={attachments} onRemove={onRemoveAttachment} />}",
        """                {temporaryChatMode && (
                  <button
                    className="inline-flex w-fit items-center gap-1.5 rounded-md border border-sky-400/45 bg-sky-500/14 px-2 py-1 text-[0.75rem] font-medium text-sky-200 transition-colors hover:bg-sky-500/22 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/55"
                    data-slot="temporary-chat-chip"
                    onClick={() => setTemporaryChatMode(false)}
                    title="Temporary chat. Click to remove."
                    type="button"
                  >
                    <Clock className="size-3" />
                    <span>Temporary chat</span>
                    <XIcon className="size-3" />
                  </button>
                )}
                {attachments.length > 0 && <AttachmentList attachments={attachments} onRemove={onRemoveAttachment} />}""",
    )
composer_index_text = composer_index_text.replace(
    'title="Temporary chat. Click or press Backspace in an empty input to remove."',
    'title="Temporary chat. Click to remove."',
)
composer_index_text = re.sub(
    r'(\s*<Clock className="size-3" />\n)+(\s*<span>Temporary chat</span>\n\s*<XIcon className="size-3" />)',
    '                    <Clock className="size-3" />\n\\2',
    composer_index_text,
)
composer_index_text = re.sub(
    r'(type="button"\n\s*>)\s*<Clock className="size-3" />',
    '\\1\n                    <Clock className="size-3" />',
    composer_index_text,
)
composer_index.write_text(composer_index_text, encoding="utf-8")

session_actions_hook = desktop / "src/app/session/hooks/use-session-actions.ts"
if not session_actions_hook.exists():
    session_actions_hook = desktop / "src/app/session/hooks/use-session-actions/index.ts"
session_actions_text = session_actions_hook.read_text(encoding="utf-8")
if "$temporaryChatMode" not in session_actions_text:
    session_actions_text = session_actions_text.replace(
        """  $messages,
  $sessions,""",
        """  $messages,
  $sessions,
  $temporaryChatMode,""",
    )
if "isTemporarySession" not in session_actions_text:
    session_actions_text = session_actions_text.replace(
        """  sessionPinId,
  setActiveSessionId,""",
        """  clearTemporarySession,
  isTemporarySession,
  markTemporarySession,
  sessionPinId,
  setActiveSessionId,""",
    )
if "setTemporaryChatMode" not in session_actions_text:
    session_actions_text = session_actions_text.replace(
        """  setTurnStartedAt,
  setYoloActive,""",
        """  setTemporaryChatMode,
  setTurnStartedAt,
  setYoloActive,""",
    )
if "closingTemporaryRuntimeId" not in session_actions_text:
    session_actions_text = session_actions_text.replace(
        """  const startFreshSessionDraft = useCallback(
    (replaceRoute = false) => {
      busyRef.current = false""",
        """  const startFreshSessionDraft = useCallback(
    (replaceRoute = false) => {
      const closingTemporaryRuntimeId = activeSessionIdRef.current
      if (closingTemporaryRuntimeId && isTemporarySession(closingTemporaryRuntimeId)) {
        void requestGateway('session.close', { session_id: closingTemporaryRuntimeId })
          .catch(() => undefined)
          .finally(() => clearTemporarySession(closingTemporaryRuntimeId))
      }
      setTemporaryChatMode(false)
      busyRef.current = false""",
    )
session_actions_text = session_actions_text.replace(
    "    [activeSessionIdRef, busyRef, navigate, selectedStoredSessionIdRef]\n  )",
    "    [activeSessionIdRef, busyRef, navigate, requestGateway, selectedStoredSessionIdRef]\n  )",
    1,
)
if "const temporaryChat = $temporaryChatMode.get()" not in session_actions_text:
    session_actions_text = session_actions_text.replace(
        """      const startingActiveSessionId = activeSessionIdRef.current
      const startingStoredSessionId = selectedStoredSessionIdRef.current""",
        """      const temporaryChat = $temporaryChatMode.get()
      const startingActiveSessionId = activeSessionIdRef.current
      const startingStoredSessionId = selectedStoredSessionIdRef.current""",
        1,
    )
if "ephemeral: true" not in session_actions_text:
    session_actions_text = session_actions_text.replace(
        """          ...(uiEffort ? { reasoning_effort: uiEffort } : {}),
          ...(uiFast ? { fast: true } : {})""",
        """          ...(uiEffort ? { reasoning_effort: uiEffort } : {}),
          ...(uiFast ? { fast: true } : {}),
          ...(temporaryChat ? { disable_mcp: true, ephemeral: true } : {})""",
        1,
    )
session_actions_text = session_actions_text.replace(
    "        const stored = created.stored_session_id ?? null",
    "        const stored = temporaryChat ? null : (created.stored_session_id ?? null)",
    1,
)
if "markTemporarySession(created.session_id)" not in session_actions_text:
    session_actions_text = session_actions_text.replace(
        """        activeSessionIdRef.current = created.session_id
        selectedStoredSessionIdRef.current = stored""",
        """        if (temporaryChat) {
          markTemporarySession(created.session_id)
          setTemporaryChatMode(false)
        }

        activeSessionIdRef.current = created.session_id
        selectedStoredSessionIdRef.current = stored""",
        1,
    )
session_actions_text = session_actions_text.replace(
    """        if (temporaryChat) {
          markTemporarySession(created.session_id)
          setTemporaryChatMode(false)
        }""",
    """        if (temporaryChat) {
          markTemporarySession(created.session_id)
          markTemporarySession(created.session_key)
          setTemporaryChatMode(false)
        }""",
    1,
)
if "async (storedSessionId: string, replaceRoute = false) => {\n      const closingTemporaryRuntimeId" not in session_actions_text:
    session_actions_text = session_actions_text.replace(
        """  const resumeSession = useCallback(
    async (storedSessionId: string, replaceRoute = false) => {
      const requestId = resumeRequestRef.current + 1""",
        """  const resumeSession = useCallback(
    async (storedSessionId: string, replaceRoute = false) => {
      const closingTemporaryRuntimeId = activeSessionIdRef.current
      if (closingTemporaryRuntimeId && isTemporarySession(closingTemporaryRuntimeId)) {
        void requestGateway('session.close', { session_id: closingTemporaryRuntimeId })
          .catch(() => undefined)
          .finally(() => clearTemporarySession(closingTemporaryRuntimeId))
      }
      setTemporaryChatMode(false)
      const requestId = resumeRequestRef.current + 1""",
    )

if "  $temporaryChatMode,\n" not in session_actions_text:
    session_actions_text = session_actions_text.replace(
        "  $messages,\n",
        "  $messages,\n  $temporaryChatMode,\n",
        1,
    )
if "clearTemporarySession," not in session_actions_text:
    session_actions_text = session_actions_text.replace(
        "  sessionPinId,\n",
        "  clearTemporarySession,\n  isTemporarySession,\n  markTemporarySession,\n  sessionPinId,\n",
        1,
    )
if "setTemporaryChatMode," not in session_actions_text:
    session_actions_text = session_actions_text.replace(
        "  setTurnStartedAt,\n",
        "  setTemporaryChatMode,\n  setTurnStartedAt,\n",
        1,
    )
if "...(temporaryChat ? { disable_mcp: true, ephemeral: true } : {})" not in session_actions_text:
    session_actions_text = session_actions_text.replace(
        "    ...($currentFastMode.get() ? { fast: true } : {})\n",
        "    ...($currentFastMode.get() ? { fast: true } : {}),\n"
        "    ...($temporaryChatMode.get() ? { disable_mcp: true, ephemeral: true } : {})\n",
        1,
    )
if "const closingTemporaryRuntimeId = activeSessionIdRef.current\n      if (closingTemporaryRuntimeId" not in session_actions_text:
    session_actions_text = session_actions_text.replace(
        """      const workspaceTarget = hasWorkspaceTarget
        ? normalizeNewChatWorkspaceTarget(draftOptions.workspaceTarget)
        : undefined

      resetViewSync()""",
        """      const workspaceTarget = hasWorkspaceTarget
        ? normalizeNewChatWorkspaceTarget(draftOptions.workspaceTarget)
        : undefined

      const closingTemporaryRuntimeId = activeSessionIdRef.current
      if (closingTemporaryRuntimeId && isTemporarySession(closingTemporaryRuntimeId)) {
        void requestGateway('session.close', { session_id: closingTemporaryRuntimeId })
          .catch(() => undefined)
          .finally(() => clearTemporarySession(closingTemporaryRuntimeId))
      }
      setTemporaryChatMode(false)
      resetViewSync()""",
        1,
    )
session_actions_text = session_actions_text.replace(
    """    [activeSessionIdRef, busyRef, navigate, onFreshDraftRouteIntent, resetViewSync, selectedStoredSessionIdRef]
  )""",
    """    [
      activeSessionIdRef,
      busyRef,
      navigate,
      onFreshDraftRouteIntent,
      requestGateway,
      resetViewSync,
      selectedStoredSessionIdRef
    ]
  )""",
    1,
)
session_actions_hook.write_text(session_actions_text, encoding="utf-8")

acp_session = hermes_root / "acp_adapter/session.py"
acp_session_text = acp_session.read_text(encoding="utf-8")
if "    ephemeral: bool = False\n" not in acp_session_text:
    acp_session_text = acp_session_text.replace(
        "    interrupted_prompt_text: str = \"\"\n",
        "    interrupted_prompt_text: str = \"\"\n    ephemeral: bool = False\n",
    )
acp_session_text = acp_session_text.replace(
    "    def create_session(self, cwd: str = \".\") -> SessionState:\n",
    "    def create_session(self, cwd: str = \".\", *, ephemeral: bool = False, mcp_enabled: bool = True) -> SessionState:\n",
)
acp_session_text = acp_session_text.replace(
    "        agent = self._make_agent(session_id=session_id, cwd=cwd)\n",
    "        agent = self._make_agent(session_id=session_id, cwd=cwd, mcp_server_names=None if mcp_enabled else [])\n",
    1,
)
if "            ephemeral=ephemeral,\n" not in acp_session_text:
    acp_session_text = acp_session_text.replace(
        """            model=getattr(agent, "model", "") or "",
            cancel_event=threading.Event(),""",
        """            model=getattr(agent, "model", "") or "",
            cancel_event=threading.Event(),
            ephemeral=ephemeral,""",
        1,
    )
acp_session_text = acp_session_text.replace(
    "        self._persist(state)\n        logger.info(\"Created ACP session %s (cwd=%s)\", session_id, cwd)",
    "        if not ephemeral:\n            self._persist(state)\n        logger.info(\"Created ACP session %s (cwd=%s, ephemeral=%s)\", session_id, cwd, ephemeral)",
    1,
)
if "if getattr(s, \"ephemeral\", False):\n                    continue\n                history_len = len(s.history)" not in acp_session_text:
    acp_session_text = acp_session_text.replace(
        "            for s in self._sessions.values():\n                history_len = len(s.history)",
        "            for s in self._sessions.values():\n                if getattr(s, \"ephemeral\", False):\n                    continue\n                history_len = len(s.history)",
    )
acp_session_text = acp_session_text.replace(
    """        if state is not None:
            self._persist(state)""",
    """        if state is not None and not getattr(state, "ephemeral", False):
            self._persist(state)""",
)
if "        if getattr(state, \"ephemeral\", False):\n            return\n        db = self._get_db()" not in acp_session_text:
    acp_session_text = acp_session_text.replace(
        """        db = self._get_db()
        if db is None:
            return""",
        """        if getattr(state, "ephemeral", False):
            return
        db = self._get_db()
        if db is None:
            return""",
        1,
    )
if "mcp_server_names: list[str] | None = None" not in acp_session_text:
    acp_session_text = acp_session_text.replace(
        """        api_mode: str | None = None,
    ):""",
        """        api_mode: str | None = None,
        mcp_server_names: list[str] | None = None,
    ):""",
    )
if "list(mcp_server_names)" not in acp_session_text:
    acp_session_text = acp_session_text.replace(
        """        configured_mcp_servers = [
            name
            for name, cfg in (config.get("mcp_servers") or {}).items()
            if not isinstance(cfg, dict) or cfg.get("enabled", True) is not False
        ]""",
        """        configured_mcp_servers = (
            list(mcp_server_names)
            if mcp_server_names is not None
            else [
                name
                for name, cfg in (config.get("mcp_servers") or {}).items()
                if not isinstance(cfg, dict) or cfg.get("enabled", True) is not False
            ]
        )""",
    )
acp_session.write_text(acp_session_text, encoding="utf-8")

acp_server = hermes_root / "acp_adapter/server.py"
acp_server_text = acp_server.read_text(encoding="utf-8")
if "def _is_hermes_memory_tool_name(value: object) -> bool:" not in acp_server_text:
    acp_server_text = acp_server_text.replace(
        """def _is_image_resource(mime_type: str | None) -> bool:
    mime = (mime_type or "").split(";", 1)[0].strip().lower()
    return mime.startswith("image/")
""",
        """def _is_image_resource(mime_type: str | None) -> bool:
    mime = (mime_type or "").split(";", 1)[0].strip().lower()
    return mime.startswith("image/")


def _is_hermes_memory_tool_name(value: object) -> bool:
    normalized = str(value or "").lower().replace("-", "_")
    return "hermes_memory" in normalized or normalized.startswith("memory_")


def _disable_hermes_memory_tools(agent: Any) -> None:
    toolsets = list(getattr(agent, "enabled_toolsets", None) or [])
    filtered_toolsets = [
        name
        for name in toolsets
        if "hermes-memory" not in str(name).lower()
        and "hermes_memory" not in str(name).lower()
        and str(name).lower() != "session_search"
    ]
    if filtered_toolsets != toolsets:
        agent.enabled_toolsets = filtered_toolsets

    tools = list(getattr(agent, "tools", None) or [])
    filtered_tools = [
        tool
        for tool in tools
        if not _is_hermes_memory_tool_name((tool.get("function") or {}).get("name") if isinstance(tool, dict) else "")
    ]
    if filtered_tools != tools:
        agent.tools = filtered_tools
        agent.valid_tool_names = {
            (tool.get("function") or {}).get("name")
            for tool in filtered_tools
            if isinstance(tool, dict) and (tool.get("function") or {}).get("name")
        }

    invalidate = getattr(agent, "_invalidate_system_prompt", None)
    if callable(invalidate):
        invalidate()
""",
        1,
    )
if "disable_mcp: bool = False" not in acp_server_text:
    acp_server_text = acp_server_text.replace(
        """    async def new_session(
        self,
        cwd: str,
        mcp_servers: list | None = None,
        **kwargs: Any,
    ) -> NewSessionResponse:
        state = self.session_manager.create_session(cwd=cwd)
        await self._register_session_mcp_servers(state, mcp_servers)
        logger.info("New session %s (cwd=%s)", state.session_id, cwd)""",
        """    async def new_session(
        self,
        cwd: str,
        mcp_servers: list | None = None,
        ephemeral: bool = False,
        disable_mcp: bool = False,
        **kwargs: Any,
    ) -> NewSessionResponse:
        state = self.session_manager.create_session(cwd=cwd, ephemeral=bool(ephemeral), mcp_enabled=not bool(disable_mcp))
        if not disable_mcp:
            await self._register_session_mcp_servers(state, mcp_servers)
        logger.info("New session %s (cwd=%s, ephemeral=%s, disable_mcp=%s)", state.session_id, cwd, ephemeral, disable_mcp)""",
    )
if "if not getattr(state, \"ephemeral\", False):\n                self.session_manager.save_session(session_id)" not in acp_server_text:
    acp_server_text = re.sub(
        r'(        if result\.get\("messages"\):\n            state\.history = result\["messages"\]\n)(?:            \#[^\n]*\n)?            self\.session_manager\.save_session\(session_id\)',
        r'\1            if not getattr(state, "ephemeral", False):\n                self.session_manager.save_session(session_id)',
        acp_server_text,
        count=1,
    )
if "if getattr(state, \"ephemeral\", False):\n            _disable_hermes_memory_tools(agent)" not in acp_server_text:
    acp_server_text = acp_server_text.replace(
        """        agent = state.agent
        agent.tool_progress_callback = tool_progress_cb""",
        """        agent = state.agent
        if getattr(state, "ephemeral", False):
            _disable_hermes_memory_tools(agent)
        agent.tool_progress_callback = tool_progress_cb""",
        1,
    )
acp_server.write_text(acp_server_text, encoding="utf-8")

api_server = hermes_root / "gateway/platforms/api_server.py"
api_server_text = api_server.read_text(encoding="utf-8")
if "self._ephemeral_sessions: set[str] = set()" not in api_server_text:
    api_server_text = re.sub(
        r'(?m)^(        self\._session_db: Optional\[Any\] = None)(?:\s+\#[^\n]*)?$',
        r'\1\n        self._ephemeral_sessions: set[str] = set()',
        api_server_text,
        count=1,
    )
if "def _is_hermes_memory_tool_name(value: object) -> bool:" not in api_server_text:
    api_server_text = api_server_text.replace(
        """def _coerce_port(value: Any, default: int) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        return default
    return port if 0 < port < 65536 else default
""",
        """def _coerce_port(value: Any, default: int) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        return default
    return port if 0 < port < 65536 else default


def _is_hermes_memory_tool_name(value: object) -> bool:
    normalized = str(value or "").lower().replace("-", "_")
    return "hermes_memory" in normalized or normalized.startswith("memory_")


def _filter_hermes_memory_toolsets(toolsets: list[str]) -> list[str]:
    return [
        name
        for name in toolsets
        if "hermes-memory" not in str(name).lower()
        and "hermes_memory" not in str(name).lower()
        and str(name).lower() != "session_search"
    ]
""",
        1,
    )
if "def _filter_hermes_memory_toolsets(toolsets: list[str]) -> list[str]:" not in api_server_text:
    api_server_text = api_server_text.replace(
        """
_TRUE_REQUEST_BOOL_STRINGS = frozenset({"1", "true", "yes", "on"})""",
        """

def _is_hermes_memory_tool_name(value: object) -> bool:
    normalized = str(value or "").lower().replace("-", "_")
    return "hermes_memory" in normalized or normalized.startswith("memory_")


def _filter_hermes_memory_toolsets(toolsets: list[str]) -> list[str]:
    return [
        name
        for name in toolsets
        if "hermes-memory" not in str(name).lower()
        and "hermes_memory" not in str(name).lower()
        and str(name).lower() != "session_search"
    ]


_TRUE_REQUEST_BOOL_STRINGS = frozenset({"1", "true", "yes", "on"})""",
        1,
    )
api_server_text = api_server_text.replace(
    'if "hermes-memory" not in str(name).lower() and "hermes_memory" not in str(name).lower()',
    'if "hermes-memory" not in str(name).lower()\n        and "hermes_memory" not in str(name).lower()\n        and str(name).lower() != "session_search"',
)
if "disable_memory_mcp: bool = False," not in api_server_text:
    api_server_text = api_server_text.replace(
        """        tool_complete_callback=None,
        gateway_session_key: Optional[str] = None,
    ) -> Any:""",
        """        tool_complete_callback=None,
        gateway_session_key: Optional[str] = None,
        disable_memory_mcp: bool = False,
        ephemeral_session: bool = False,
    ) -> Any:""",
        1,
    )
if "if disable_memory_mcp:\n            enabled_toolsets = _filter_hermes_memory_toolsets(enabled_toolsets)" not in api_server_text:
    api_server_text = api_server_text.replace(
        """        user_config = _load_gateway_config()
        enabled_toolsets = sorted(_get_platform_tools(user_config, "api_server"))

        max_iterations = _current_max_iterations()""",
        """        user_config = _load_gateway_config()
        enabled_toolsets = sorted(_get_platform_tools(user_config, "api_server"))
        if disable_memory_mcp:
            enabled_toolsets = _filter_hermes_memory_toolsets(enabled_toolsets)

        max_iterations = _current_max_iterations()""",
        1,
    )
api_server_text = api_server_text.replace(
    "            session_db=None if ephemeral_session else self._ensure_session_db(),\n",
    "            session_db=False if ephemeral_session else self._ensure_session_db(),\n",
    1,
)
api_server_text = api_server_text.replace(
    "            session_db=self._ensure_session_db(),\n",
    "            session_db=False if ephemeral_session else self._ensure_session_db(),\n",
    1,
)
if "ephemeral_session = _coerce_request_bool(body.get(\"ephemeral\") or body.get(\"temporary\"), default=False)" not in api_server_text:
    api_server_text = api_server_text.replace(
        """        if db.get_session(session_id):
            return web.json_response(_openai_error(f"Session already exists: {session_id}", code="session_exists"), status=409)

        model = body.get("model") or self._model_name""",
        """        if db.get_session(session_id):
            return web.json_response(_openai_error(f"Session already exists: {session_id}", code="session_exists"), status=409)

        ephemeral_session = _coerce_request_bool(body.get("ephemeral") or body.get("temporary"), default=False)
        if ephemeral_session:
            self._ephemeral_sessions.add(session_id)

        model = body.get("model") or self._model_name""",
        1,
    )
if "self._ephemeral_sessions.discard(session_id)" not in api_server_text:
    api_server_text = api_server_text.replace(
        """        db = self._ensure_session_db()
        deleted = db.delete_session(session_id)""",
        """        self._ephemeral_sessions.discard(session_id)
        db = self._ensure_session_db()
        deleted = db.delete_session(session_id)""",
        1,
    )
if "ephemeral_session = session_id in self._ephemeral_sessions" not in api_server_text:
    api_server_text = api_server_text.replace(
        """        history = self._conversation_history_for_session(session_id)
        result, usage = await self._run_agent(
            user_message=user_message,
            conversation_history=history,
            ephemeral_system_prompt=system_prompt,
            session_id=session_id,
            gateway_session_key=gateway_session_key,
        )""",
        """        ephemeral_session = session_id in self._ephemeral_sessions
        history = [] if ephemeral_session else self._conversation_history_for_session(session_id)
        result, usage = await self._run_agent(
            user_message=user_message,
            conversation_history=history,
            ephemeral_system_prompt=system_prompt,
            session_id=session_id,
            gateway_session_key=gateway_session_key,
            disable_memory_mcp=ephemeral_session,
            ephemeral_session=ephemeral_session,
        )""",
        1,
    )
if "stream_ephemeral_session = session_id in self._ephemeral_sessions" not in api_server_text:
    api_server_text = api_server_text.replace(
        """                history = self._conversation_history_for_session(session_id)
                result, usage = await self._run_agent(
                    user_message=user_message,
                    conversation_history=history,
                    ephemeral_system_prompt=system_prompt,
                    session_id=session_id,
                    stream_delta_callback=_delta,
                    tool_progress_callback=_tool_progress,
                    gateway_session_key=gateway_session_key,
                )""",
        """                stream_ephemeral_session = session_id in self._ephemeral_sessions
                history = [] if stream_ephemeral_session else self._conversation_history_for_session(session_id)
                result, usage = await self._run_agent(
                    user_message=user_message,
                    conversation_history=history,
                    ephemeral_system_prompt=system_prompt,
                    session_id=session_id,
                    stream_delta_callback=_delta,
                    tool_progress_callback=_tool_progress,
                    gateway_session_key=gateway_session_key,
                    disable_memory_mcp=stream_ephemeral_session,
                    ephemeral_session=stream_ephemeral_session,
                )""",
        1,
    )
if "disable_memory_mcp: bool = False,\n        ephemeral_session: bool = False," not in api_server_text:
    api_server_text = api_server_text.replace(
        """        tool_complete_callback=None,
        agent_ref: Optional[list] = None,
        gateway_session_key: Optional[str] = None,
    ) -> tuple:""",
        """        tool_complete_callback=None,
        agent_ref: Optional[list] = None,
        gateway_session_key: Optional[str] = None,
        disable_memory_mcp: bool = False,
        ephemeral_session: bool = False,
    ) -> tuple:""",
        1,
    )
if "is_ephemeral_session = bool(ephemeral_session or (session_id and session_id in self._ephemeral_sessions))" not in api_server_text:
    api_server_text = api_server_text.replace(
        """        loop = asyncio.get_running_loop()

        def _run():""",
        """        loop = asyncio.get_running_loop()
        is_ephemeral_session = bool(ephemeral_session or (session_id and session_id in self._ephemeral_sessions))

        def _run():""",
        1,
    )
if "disable_memory_mcp=bool(disable_memory_mcp or is_ephemeral_session)," not in api_server_text:
    api_server_text = api_server_text.replace(
        """                    tool_start_callback=tool_start_callback,
                    tool_complete_callback=tool_complete_callback,
                    gateway_session_key=gateway_session_key,
                )""",
        """                    tool_start_callback=tool_start_callback,
                    tool_complete_callback=tool_complete_callback,
                    gateway_session_key=gateway_session_key,
                    disable_memory_mcp=bool(disable_memory_mcp or is_ephemeral_session),
                    ephemeral_session=is_ephemeral_session,
                )""",
        1,
    )
api_server.write_text(api_server_text, encoding="utf-8")

tui_server = hermes_root / "tui_gateway/server.py"
tui_server_text = tui_server.read_text(encoding="utf-8")
if "def _filter_hermes_memory_toolsets(toolsets: list[str] | None) -> list[str] | None:" not in tui_server_text:
    tui_server_text = tui_server_text.replace(
        """def _load_enabled_toolsets() -> list[str] | None:
    explicit = [
""",
        """def _filter_hermes_memory_toolsets(toolsets: list[str] | None) -> list[str] | None:
    if toolsets is None:
        return None
    return [
        name
        for name in toolsets
        if "hermes-memory" not in str(name).lower() and "hermes_memory" not in str(name).lower()
    ]


def _load_enabled_toolsets() -> list[str] | None:
    explicit = [
""",
        1,
    )
tui_server_text = tui_server_text.replace(
    'if "hermes-memory" not in str(name).lower() and "hermes_memory" not in str(name).lower()',
    'if "hermes-memory" not in str(name).lower()\n        and "hermes_memory" not in str(name).lower()\n        and str(name).lower() != "session_search"',
)
tui_make_agent_signature = re.search(
    r"def _make_agent\(\n(?P<params>(?:    [^\n]*\n)+?)\):",
    tui_server_text,
)
if tui_make_agent_signature is None:
    raise SystemExit("Hermes Mem patch validation failed: tui_gateway._make_agent signature not found")
privacy_parameter_lines = (
    "disable_memory_mcp: bool = False",
    "ephemeral_session: bool = False",
)
existing_privacy_params = {
    line.strip().rstrip(",") for line in tui_make_agent_signature.group("params").splitlines()
}
missing_privacy_params = [line for line in privacy_parameter_lines if line not in existing_privacy_params]
if missing_privacy_params:
    updated_signature = tui_make_agent_signature.group(0).replace(
        "\n):",
        "\n" + "\n".join(f"    {line}," for line in missing_privacy_params) + "\n):",
    )
    tui_server_text = (
        tui_server_text[: tui_make_agent_signature.start()]
        + updated_signature
        + tui_server_text[tui_make_agent_signature.end() :]
    )
if "enabled_toolsets = _load_enabled_toolsets()\n    if disable_memory_mcp or ephemeral_session:" not in tui_server_text:
    tui_server_text = tui_server_text.replace(
        """    _pr = _load_provider_routing()
    return AIAgent(""",
        """    enabled_toolsets = _load_enabled_toolsets()
    if disable_memory_mcp or ephemeral_session:
        enabled_toolsets = _filter_hermes_memory_toolsets(enabled_toolsets)

    _pr = _load_provider_routing()
    return AIAgent(""",
        1,
    )
tui_server_text = tui_server_text.replace(
    "        enabled_toolsets=_load_enabled_toolsets(),\n",
    "        enabled_toolsets=enabled_toolsets,\n",
    1,
)
tui_server_text = tui_server_text.replace(
    "        session_db=None if ephemeral_session else (session_db if session_db is not None else _get_db()),\n",
    "        session_db=False if ephemeral_session else (session_db if session_db is not None else _get_db()),\n",
    1,
)
tui_server_text = tui_server_text.replace(
    "        session_db=session_db if session_db is not None else _get_db(),\n",
    "        session_db=False if ephemeral_session else (session_db if session_db is not None else _get_db()),\n",
    1,
)
if "if current.get(\"ephemeral\"):\n                    session_db = None\n            elif profile_home:" not in tui_server_text:
    tui_server_text = tui_server_text.replace(
        """            session_db = None
            if profile_home:
                home_token = set_hermes_home_override(profile_home)""",
        """            session_db = None
            if current.get("ephemeral"):
                session_db = None
            elif profile_home:
                home_token = set_hermes_home_override(profile_home)""",
        1,
    )
if "\"ephemeral_session\": bool(current.get(\"ephemeral\"))" not in tui_server_text:
    tui_server_text = tui_server_text.replace(
        """                kw = {"session_db": session_db}
                if resume_sid := current.get("resume_session_id"):""",
        """                kw = {
                    "session_db": session_db,
                    "disable_memory_mcp": bool(current.get("disable_memory_mcp") or current.get("ephemeral")),
                    "ephemeral_session": bool(current.get("ephemeral")),
                }
                if resume_sid := current.get("resume_session_id"):""",
        1,
    )
if "disable_memory_mcp=bool(session.get(\"disable_memory_mcp\") or session.get(\"ephemeral\"))" not in tui_server_text:
    tui_server_text = tui_server_text.replace(
        """            model_override=session.get("model_override"),
        )""",
        """            model_override=session.get("model_override"),
            disable_memory_mcp=bool(session.get("disable_memory_mcp") or session.get("ephemeral")),
            ephemeral_session=bool(session.get("ephemeral")),
        )""",
        1,
    )
if "if session is None or session.get(\"agent\") is not agent:" in tui_server_text and "if session.get(\"disable_memory_mcp\") or session.get(\"ephemeral\"):\n                return" not in tui_server_text:
    tui_server_text = tui_server_text.replace(
        """            if session is None or session.get("agent") is not agent:
                return
""",
        """            if session is None or session.get("agent") is not agent:
                return
            if session.get("disable_memory_mcp") or session.get("ephemeral"):
                return
""",
        1,
    )
if "enabled_override=_filter_hermes_memory_toolsets(_load_enabled_toolsets())" not in tui_server_text:
    tui_server_text = tui_server_text.replace(
        """                refresh_agent_mcp_tools(
                    agent,
                    enabled_override=_load_enabled_toolsets(),
                    quiet_mode=True,
                )""",
        """                refresh_agent_mcp_tools(
                    agent,
                    enabled_override=(
                        _filter_hermes_memory_toolsets(_load_enabled_toolsets())
                        if session.get("disable_memory_mcp") or session.get("ephemeral")
                        else _load_enabled_toolsets()
                    ),
                    quiet_mode=True,
                )""",
        1,
    )

tui_make_agent_signature = re.search(
    r"def _make_agent\(\n(?P<params>(?:    [^\n]*\n)+?)\):",
    tui_server_text,
)
if tui_make_agent_signature is None or not {
    "disable_memory_mcp: bool = False",
    "ephemeral_session: bool = False",
}.issubset(set(line.strip().rstrip(",") for line in tui_make_agent_signature.group("params").splitlines())):
    raise SystemExit("Hermes Mem patch validation failed: tui_gateway._make_agent privacy flags are missing")
if "if session.get(\"ephemeral\"):\n        return" not in tui_server_text:
    tui_server_text = tui_server_text.replace(
        """    if not key:
        return
""",
        """    if not key:
        return
    if session.get("ephemeral"):
        return
""",
        1,
    )
if "if session.get(\"ephemeral\"):\n        yield None\n        return\n    db, close_db = None, False" not in tui_server_text:
    tui_server_text = tui_server_text.replace(
        """    db, close_db = None, False
    profile_home = session.get("profile_home")""",
        """    if session.get("ephemeral"):
        yield None
        return
    db, close_db = None, False
    profile_home = session.get("profile_home")""",
        1,
    )
if "ephemeral = is_truthy_value(params.get(\"ephemeral\", False))" not in tui_server_text:
    tui_server_text = tui_server_text.replace(
        """    title = str(params.get("title") or "").strip()
""",
        """    title = str(params.get("title") or "").strip()
    ephemeral = is_truthy_value(params.get("ephemeral", False)) or is_truthy_value(params.get("temporary", False))
    disable_memory_mcp = (
        ephemeral
        or is_truthy_value(params.get("disable_memory_mcp", False))
        or is_truthy_value(params.get("disable_mcp", False))
    )
""",
        1,
    )
if "\"disable_memory_mcp\": disable_memory_mcp," not in tui_server_text:
    tui_server_text = tui_server_text.replace(
        """            "created_at": now,
            "edit_snapshots": {},""",
        """            "created_at": now,
            "disable_memory_mcp": disable_memory_mcp,
            "edit_snapshots": {},
            "ephemeral": ephemeral,""",
        1,
    )
tui_server_text = tui_server_text.replace(
    '            "stored_session_id": key,\n',
    '            "stored_session_id": None if ephemeral else key,\n',
    1,
)
if '            "session_key": key,\n' not in tui_server_text:
    tui_server_text = tui_server_text.replace(
        '            "session_id": sid,\n',
        '            "session_id": sid,\n            "session_key": key,\n',
        1,
    )
if 'if session.get("ephemeral") and "title" not in params:' not in tui_server_text:
    tui_server_text = tui_server_text.replace(
        """    if err:
        return err
    db = _get_db()""",
        """    if err:
        return err
    if session.get("ephemeral") and "title" not in params:
        return _ok(
            rid,
            {
                "title": str(session.get("pending_title") or ""),
                "session_key": session["session_key"],
            },
        )
    if session.get("ephemeral"):
        title = (params.get("title", "") or "").strip()
        if not title:
            return _err(rid, 4021, "title required")
        session["pending_title"] = title
        return _ok(rid, {"pending": True, "title": title})
    db = _get_db()""",
        1,
    )
tui_server_text = tui_server_text.replace(
    '            if _pending and status == "complete":',
    '            if _pending and status == "complete" and not session.get("ephemeral"):',
    1,
)
tui_server_text = tui_server_text.replace(
    """            if (
                status == "complete"
                and isinstance(raw, str)""",
    """            if (
                status == "complete"
                and not session.get("ephemeral")
                and isinstance(raw, str)""",
    1,
)
tui_server.write_text(tui_server_text, encoding="utf-8")

tui_privacy_test = hermes_root / "tests/tui_gateway/test_mem_temporary_chat.py"
tui_privacy_test.parent.mkdir(parents=True, exist_ok=True)
tui_privacy_test.write_text(
    '''"""Hermes Mem regression coverage for Temporary chat agent construction."""

from unittest.mock import MagicMock, patch


def test_temporary_agent_factory_accepts_privacy_flags_and_disables_persistence():
    fake_runtime = {
        "provider": "anthropic",
        "base_url": "https://api.anthropic.com",
        "api_key": "test-key",
        "api_mode": "anthropic_messages",
        "command": None,
        "args": None,
        "credential_pool": None,
    }
    fake_cfg = {
        "model": {"default": "test-model", "provider": "anthropic"},
        "agent": {"system_prompt": ""},
    }

    with (
        patch("tui_gateway.server._load_cfg", return_value=fake_cfg),
        patch("tui_gateway.server._get_db", return_value=MagicMock()),
        patch("tui_gateway.server._load_reasoning_config", return_value=None),
        patch("tui_gateway.server._load_service_tier", return_value=None),
        patch(
            "tui_gateway.server._load_enabled_toolsets",
            return_value=["hermes-memory", "session_search", "web"],
        ),
        patch(
            "hermes_cli.runtime_provider.resolve_runtime_provider",
            return_value=fake_runtime,
        ),
        patch("run_agent.AIAgent") as mock_agent,
    ):
        from tui_gateway.server import _make_agent

        _make_agent(
            "temporary-runtime",
            "temporary-session",
            disable_memory_mcp=True,
            ephemeral_session=True,
        )

    kwargs = mock_agent.call_args.kwargs
    assert kwargs["enabled_toolsets"] == ["web"]
    assert kwargs["session_db"] is False
''',
    encoding="utf-8",
)

tts_tool = hermes_root / "tools/tts_tool.py"
if tts_tool.exists():
    tts_text = tts_tool.read_text(encoding="utf-8")
    tts_patch = r'''_MD_CODE_BLOCK = re.compile(r'```[\s\S]*?(?:```|$)')
_MD_LINK = re.compile(r'\[([^\]]+)\]\([^)]+\)')
_MD_URL = re.compile(r'https?://\S+')
_MD_INLINE_CODE = re.compile(r'`[^`]*`')
_MD_HEADER = re.compile(r'^\s{0,3}#{1,6}\s*', flags=re.MULTILINE)
_MD_LIST_ITEM = re.compile(r'^\s*(?:[-+*•]|\d+[.)])\s+', flags=re.MULTILINE)
_MD_TABLE_LINE = re.compile(r'^\s*\|.*\|\s*$', flags=re.MULTILINE)
_HTML_BLOCK = re.compile(r'<[^>\n]+>')
_PATH_TOKEN = re.compile(r'(?:~|\.{1,2}|/)?(?:/[\w .@%+=:,~_-]+){1,}|\b[\w.-]+\.(?:py|ts|tsx|js|jsx|json|yaml|yml|toml|md|txt|log|sh|sqlite3?|db|env)\b', flags=re.IGNORECASE)
_COMMAND_LINE = re.compile(r'^\s*(?:\$|>|#)?\s*(?:sudo\s+)?(?:apt|dnf|pacman|emerge|npm|pnpm|yarn|pip|python3?|node|git|hermes|codex|curl|grep|rg|cd|cp|mv|rm|mkdir|chmod|chown|systemctl|journalctl|pkill)\b.*$', flags=re.IGNORECASE | re.MULTILINE)
_TOOL_LABEL = re.compile(r'^\s*(?:result|tool|mcp|memory\.[\w.-]+|code|json|output|log|traceback)\s*:?\s*', flags=re.IGNORECASE | re.MULTILINE)
_TTS_TECHNICAL_DETAILS = 'Technical details omitted.'
_DEFAULT_ELEVENLABS_TIMEOUT_SECONDS = 300


def _get_elevenlabs_timeout(tts_config: dict) -> float:
    el_config = tts_config.get('elevenlabs', {}) if isinstance(tts_config, dict) else {}
    raw = el_config.get('timeout', el_config.get('timeout_seconds', el_config.get('request_timeout')))
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return float(_DEFAULT_ELEVENLABS_TIMEOUT_SECONDS)
    if value <= 0:
        return float(_DEFAULT_ELEVENLABS_TIMEOUT_SECONDS)
    return value


def _create_elevenlabs_client(ElevenLabs, api_key: str, tts_config: dict):
    timeout = _get_elevenlabs_timeout(tts_config)
    try:
        return ElevenLabs(api_key=api_key, timeout=timeout)
    except TypeError:
        logger.warning('Installed elevenlabs SDK does not support client timeout; using SDK default')
        return ElevenLabs(api_key=api_key)


def _normalize_tts_words(text: str) -> str:
    replacements = [
        (r'\bGPT[- ]?5\.5\b', 'G P T five point five'),
        (r'\bGPT[- ]?5\b', 'G P T five'),
        (r'\bCtrl\+V\b', 'Control V'),
        (r'\bCtrl\+C\b', 'Control C'),
        (r'\bCtrl\+Z\b', 'Control Z'),
        (r'\bAPI\b', 'A P I'),
        (r'\bTTS\b', 'T T S'),
        (r'\bMCP\b', 'M C P'),
    ]
    for pattern, value in replacements:
        text = re.sub(pattern, value, text, flags=re.IGNORECASE)
    return text


def prepare_text_for_tts(text: str) -> str:
    cleaned = (text or '').replace('\r\n', '\n').replace('\r', '\n')
    cleaned = _MD_CODE_BLOCK.sub(f' {_TTS_TECHNICAL_DETAILS} ', cleaned)
    cleaned = _COMMAND_LINE.sub(f' {_TTS_TECHNICAL_DETAILS} ', cleaned)
    cleaned = _MD_TABLE_LINE.sub(' ', cleaned)
    cleaned = _HTML_BLOCK.sub(' ', cleaned)
    cleaned = _MD_LINK.sub(r'\1', cleaned)
    cleaned = _MD_URL.sub(' ', cleaned)
    cleaned = _MD_INLINE_CODE.sub(f' {_TTS_TECHNICAL_DETAILS} ', cleaned)
    cleaned = _PATH_TOKEN.sub(f' {_TTS_TECHNICAL_DETAILS} ', cleaned)
    cleaned = _TOOL_LABEL.sub(' ', cleaned)
    cleaned = _MD_HEADER.sub('', cleaned)
    cleaned = _MD_LIST_ITEM.sub('', cleaned)
    cleaned = _normalize_tts_words(cleaned)
    cleaned = re.sub(r'[,\u2013\u2014:;]+', ' ', cleaned)
    cleaned = re.sub(r'[*_#>|~\\\[\](){}"`]', ' ', cleaned)
    cleaned = re.sub(r'[^\w.!? ]+', ' ', cleaned, flags=re.UNICODE)
    cleaned = re.sub(r'\.{2,}', '.', cleaned)
    cleaned = re.sub(r'[!?]{2,}', lambda match: match.group(0)[0], cleaned)
    cleaned = re.sub(r'\s*([.!?])\s*', r'\1 ', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    if not cleaned:
        return ''

    cleaned = re.sub(r'(?:Technical details omitted\.\s*){2,}', _TTS_TECHNICAL_DETAILS, cleaned)
    return re.sub(r'\s+', ' ', cleaned).strip()


def _strip_markdown_for_tts(text: str) -> str:
    """Prepare text that should be spoken aloud, not raw markdown."""
    return prepare_text_for_tts(text)
'''
    tts_text = re.sub(
        r"# Markdown (?:stripping patterns|and technical-text preparation for TTS\.).*?def stream_tts_to_speaker",
        lambda _match: tts_patch + "\n\ndef stream_tts_to_speaker",
        tts_text,
        flags=re.DOTALL,
    )
    tts_text = re.sub(
        r"    tts_config = _load_tts_config\(\)\n"
        r"    provider = _get_provider\(tts_config\)\n"
        r"(?:    text = prepare_text_for_tts\(text\)\n"
        r"    if not text:\n"
        r"        return tool_error\(\"Text is empty after TTS preprocessing\", success=False\)\n)*",
        "    tts_config = _load_tts_config()\n"
        "    provider = _get_provider(tts_config)\n"
        "    text = prepare_text_for_tts(text)\n"
        "    if not text:\n"
        "        return tool_error(\"Text is empty after TTS preprocessing\", success=False)\n",
        tts_text,
        count=1,
    )
    tts_text = tts_text.replace(
        "client = ElevenLabs(api_key=api_key)",
        "client = _create_elevenlabs_client(ElevenLabs, api_key, tts_config)",
    )
    tts_tool.write_text(tts_text, encoding="utf-8")

hermes_api = desktop / "src/hermes.ts"
if hermes_api.exists():
    hermes_api_text = hermes_api.read_text(encoding="utf-8")
    hermes_api_text = hermes_api_text.replace(
        """export function speakText(text: string): Promise<AudioSpeakResponse> {
  return window.hermesDesktop.api<AudioSpeakResponse>({
    path: '/api/audio/speak',
    method: 'POST',
    body: { text }
  })
}
""",
        """export function speakText(text: string): Promise<AudioSpeakResponse> {
  return window.hermesDesktop.api<AudioSpeakResponse>({
    path: '/api/audio/speak',
    method: 'POST',
    body: { text }
  })
}
""",
    )
    hermes_api.write_text(hermes_api_text, encoding="utf-8")

electron_main = desktop / "electron/main.cjs"
if not electron_main.exists():
    electron_main = desktop / "electron/main.ts"
if electron_main.exists():
    electron_main_text = electron_main.read_text(encoding="utf-8")
    electron_main_text = electron_main_text.replace("const APP_NAME = 'Hermes'", "const APP_NAME = 'Hermes Mem'")
    electron_main_text = re.sub(
        r"function resolveHermesVersion\(\) \{[\s\S]*?\n\}\n\n// Re-resolve",
        "function resolveHermesVersion() {\n  return app.getVersion()\n}\n\n// Re-resolve",
        electron_main_text,
        count=1,
    )
    isolation_patch = r'''const MEM_INSTALL_HOME = process.env.HERMES_MEM_HOME || path.join(app.getPath('home'), '.hermes-mem')
process.env.HERMES_HOME = path.join(MEM_INSTALL_HOME, 'hermes')
process.env.HERMES_DESKTOP_USER_DATA_DIR = path.join(MEM_INSTALL_HOME, 'desktop-data')
process.env.PLAYWRIGHT_BROWSERS_PATH = path.join(MEM_INSTALL_HOME, 'browser-cache')

'''
    electron_main_text = re.sub(
        r"const (?:FPP|MEM)_INSTALL_HOME =[^\n]+\nprocess\.env\.HERMES_HOME =[^\n]+\nprocess\.env\.HERMES_DESKTOP_USER_DATA_DIR =[^\n]+\nprocess\.env\.PLAYWRIGHT_BROWSERS_PATH =[^\n]+\n\n",
        isolation_patch,
        electron_main_text,
        count=1,
    )
    if "const MEM_INSTALL_HOME =" not in electron_main_text:
        isolation_anchor = "const USER_DATA_OVERRIDE = process.env.HERMES_DESKTOP_USER_DATA_DIR\n"
        if isolation_anchor not in electron_main_text:
            raise RuntimeError("Hermes Desktop user-data initialization anchor was not found")
        electron_main_text = electron_main_text.replace(
            isolation_anchor,
            isolation_patch + isolation_anchor,
        )
    timeout_helpers = r'''
const AUDIO_SPEAK_DEFAULT_TIMEOUT_MS = 300_000

function readElevenLabsSpeakTimeoutMs() {
  try {
    const configText = fs.readFileSync(path.join(HERMES_HOME, 'config.yaml'), 'utf8')
    let inTts = false
    let inElevenLabs = false
    let ttsIndent = -1
    let elevenLabsIndent = -1
    for (const rawLine of configText.split(/\r?\n/)) {
      const withoutComment = rawLine.replace(/\s+#.*$/, '')
      if (!withoutComment.trim()) continue
      const indent = withoutComment.match(/^\s*/)?.[0].length ?? 0
      const trimmed = withoutComment.trim()
      if (!inTts && trimmed === 'tts:') {
        inTts = true
        ttsIndent = indent
        continue
      }
      if (inTts && indent <= ttsIndent) {
        inTts = false
        inElevenLabs = false
      }
      if (inTts && !inElevenLabs && trimmed === 'elevenlabs:') {
        inElevenLabs = true
        elevenLabsIndent = indent
        continue
      }
      if (inElevenLabs && indent <= elevenLabsIndent) {
        inElevenLabs = false
      }
      if (inElevenLabs) {
        const match = /^(?:timeout|timeout_seconds|request_timeout):\s*([0-9]+(?:\.[0-9]+)?)/.exec(trimmed)
        if (match) {
          const seconds = Number(match[1])
          if (Number.isFinite(seconds) && seconds > 0) {
            return Math.max(1_000, Math.round(seconds * 1_000))
          }
        }
      }
    }
  } catch {
    // Fall back to the historical short request timeout only for non-TTS calls.
  }
  return AUDIO_SPEAK_DEFAULT_TIMEOUT_MS
}

function defaultTimeoutMsForHermesApiRequest(request) {
  return request?.path === '/api/audio/speak' ? readElevenLabsSpeakTimeoutMs() : DEFAULT_FETCH_TIMEOUT_MS
}
'''
    if "function readElevenLabsSpeakTimeoutMs()" not in electron_main_text:
        electron_main_text = electron_main_text.replace(
            "const DESKTOP_LOG_BUFFER_MAX_CHARS = 64 * 1024\n",
            "const DESKTOP_LOG_BUFFER_MAX_CHARS = 64 * 1024\n" + timeout_helpers,
        )
    electron_main_text = electron_main_text.replace(
        "const timeoutMs = resolveTimeoutMs(request?.timeoutMs, DEFAULT_FETCH_TIMEOUT_MS)",
        "const timeoutMs = resolveTimeoutMs(request?.timeoutMs, defaultTimeoutMsForHermesApiRequest(request))",
    )
    memory_ipc = r'''function runHermesMemCommand(args) {
  const executable = path.join(MEM_INSTALL_HOME, 'memory', 'venv', 'bin', 'ai-memory-mcp')
  const config = path.join(MEM_INSTALL_HOME, 'memory', 'config.toml')
  return new Promise((resolve, reject) => {
    execFile(
      executable,
      ['--config', config, ...args],
      {
        env: { ...process.env, HERMES_MEM_HOME: MEM_INSTALL_HOME },
        maxBuffer: 8 * 1024 * 1024,
        timeout: 20_000
      },
      (error, stdout, stderr) => {
        if (error) {
          reject(new Error(String(stderr || error.message || 'Hermes Mem command failed').trim()))
          return
        }
        try {
          resolve(JSON.parse(String(stdout || '{}')))
        } catch {
          reject(new Error('Hermes Mem returned invalid data'))
        }
      }
    )
  })
}

ipcMain.handle('hermes:memory:dashboard', async (_event, payload = {}) => {
  const query = String(payload?.query || '').slice(0, 500)
  const requestedScope = String(payload?.scope || 'all')
  const scope = ['all', 'long-term', '10-day', 'events'].includes(requestedScope) ? requestedScope : 'all'
  return runHermesMemCommand(['dashboard', '--query', query, '--scope', scope, '--limit', '40'])
})

ipcMain.handle('hermes:memory:clear-all', async (_event, payload = {}) => {
  const confirmation = String(payload?.confirmation || '')
  if (confirmation !== 'DELETE_ALL_MEMORY') {
    throw new Error('Type DELETE_ALL_MEMORY to confirm')
  }
  return runHermesMemCommand(['clear-all', '--confirm', confirmation])
})

'''
    if "ipcMain.handle('hermes:memory:dashboard'" not in electron_main_text:
        memory_ipc_anchor = "ipcMain.handle('hermes:api', async (_event, request) => {"
        if memory_ipc_anchor not in electron_main_text:
            raise RuntimeError("Hermes Desktop API IPC anchor was not found")
        electron_main_text = electron_main_text.replace(memory_ipc_anchor, memory_ipc + memory_ipc_anchor, 1)
    electron_main_text = electron_main_text.replace(
        "const scope = ['all', 'long-term', '10-day'].includes(requestedScope) ? requestedScope : 'all'",
        "const scope = ['all', 'long-term', '10-day', 'events'].includes(requestedScope) ? requestedScope : 'all'",
    )
    electron_main.write_text(electron_main_text, encoding="utf-8")

preload = desktop / "electron/preload.ts"
if preload.exists():
    preload_text = preload.read_text(encoding="utf-8")
    if "hermes:memory:dashboard" not in preload_text:
        preload_anchor = "  api: request => ipcRenderer.invoke('hermes:api', request),\n"
        memory_preload = """  memory: {
    dashboard: payload => ipcRenderer.invoke('hermes:memory:dashboard', payload),
    clearAll: payload => ipcRenderer.invoke('hermes:memory:clear-all', payload)
  },
"""
        if preload_anchor not in preload_text:
            raise RuntimeError("Hermes Desktop preload API anchor was not found")
        preload_text = preload_text.replace(preload_anchor, memory_preload + preload_anchor, 1)
    preload.write_text(preload_text, encoding="utf-8")

global_types = desktop / "src/global.d.ts"
if global_types.exists():
    global_types_text = global_types.read_text(encoding="utf-8")
    global_types_text = global_types_text.replace(
        "scope?: 'all' | 'long-term' | '10-day'",
        "scope?: 'all' | 'long-term' | '10-day' | 'events'",
    )
    if "clearAll: (payload: { confirmation: string })" not in global_types_text:
        global_types_anchor = "      api: <T>(request: HermesApiRequest) => Promise<T>\n"
        memory_global_types = """      memory: {
        dashboard: (payload?: { query?: string; scope?: 'all' | 'long-term' | '10-day' | 'events' }) => Promise<unknown>
        clearAll: (payload: { confirmation: string }) => Promise<unknown>
      }
"""
        if global_types_anchor not in global_types_text:
            raise RuntimeError("Hermes Desktop global API type anchor was not found")
        global_types_text = global_types_text.replace(global_types_anchor, memory_global_types + global_types_anchor, 1)
    global_types.write_text(global_types_text, encoding="utf-8")

hidden_panels = desktop / "src/app/settings/hidden-panels-settings.tsx"
hidden_panels.write_text(r'''import { useStore } from '@nanostores/react'
import { useNavigate } from 'react-router-dom'

import { Button } from '@/components/ui/button'
import {
  AGENTS_ROUTE,
  ARTIFACTS_ROUTE,
  COMMAND_CENTER_ROUTE,
  CRON_ROUTE,
  MESSAGING_ROUTE,
  PROFILES_ROUTE,
  SKILLS_ROUTE
} from '@/app/routes'
import { Archive, ArrowUpRight, Clock, Command, FolderOpen, Globe, Layers3, MessageCircle, Users, Wrench, Zap } from '@/lib/icons'
import { $fileBrowserOpen, setFileBrowserOpen } from '@/store/layout'

import { ListRow, SectionHeading, SettingsContent } from './primitives'

interface HiddenPanel {
  title: string
  description: string
  icon: typeof Wrench
  route: string
}

const WORKSPACE_PANELS: HiddenPanel[] = [
  {
    title: 'Skills & Tools',
    description: 'Browse installed skills and tool surfaces without keeping the button in the chat sidebar.',
    icon: Wrench,
    route: SKILLS_ROUTE
  },
  {
    title: 'Messaging',
    description: 'Open Telegram, Discord, and other gateway conversation surfaces.',
    icon: MessageCircle,
    route: MESSAGING_ROUTE
  },
  {
    title: 'Artifacts',
    description: 'Open generated files and saved outputs when you need them.',
    icon: Archive,
    route: ARTIFACTS_ROUTE
  }
]

const SYSTEM_PANELS: HiddenPanel[] = [
  {
    title: 'Command Center',
    description: 'System overview, usage details, and runtime controls.',
    icon: Command,
    route: COMMAND_CENTER_ROUTE
  },
  {
    title: 'Agents',
    description: 'Background work, subagents, and running desktop tasks.',
    icon: Zap,
    route: AGENTS_ROUTE
  },
  {
    title: 'Cron',
    description: 'Scheduled tasks and automated runs.',
    icon: Clock,
    route: CRON_ROUTE
  }
]

const PROFILE_PANELS: HiddenPanel[] = [
  {
    title: 'Profiles',
    description: 'Manage profiles, profile colors, persona files, and profile-specific sessions.',
    icon: Users,
    route: PROFILES_ROUTE
  },
  {
    title: 'Gateway',
    description: 'Configure the messaging gateway without showing its status controls on the main screen.',
    icon: Globe,
    route: '/settings?tab=gateway'
  }
]

function PanelRow({ panel }: { panel: HiddenPanel }) {
  const navigate = useNavigate()
  const Icon = panel.icon

  return (
    <ListRow
      action={
        <Button className="gap-1.5" onClick={() => navigate(panel.route)} size="sm" type="button" variant="outline">
          Open
          <ArrowUpRight className="size-3.5" />
        </Button>
      }
      description={panel.description}
      title={
        <span className="inline-flex min-w-0 items-center gap-2">
          <Icon className="size-4 shrink-0 text-muted-foreground" />
          <span className="truncate">{panel.title}</span>
        </span>
      }
    />
  )
}

function PanelGroup({ panels }: { panels: HiddenPanel[] }) {
  return (
    <div className="divide-y divide-(--ui-stroke-tertiary)">
      {panels.map(panel => (
        <PanelRow key={panel.title} panel={panel} />
      ))}
    </div>
  )
}

function FileBrowserPanelRow() {
  const open = useStore($fileBrowserOpen)

  return (
    <ListRow
      action={
        <Button onClick={() => setFileBrowserOpen(!open)} size="sm" type="button" variant="outline">
          {open ? 'Hide' : 'Show'}
        </Button>
      }
      description="Browse workspace files when needed without keeping the panel in the main chat."
      title={
        <span className="inline-flex min-w-0 items-center gap-2">
          <FolderOpen className="size-4 shrink-0 text-muted-foreground" />
          <span className="truncate">File browser</span>
        </span>
      }
    />
  )
}

export function HiddenPanelsSettings() {
  return (
    <SettingsContent>
      <SectionHeading icon={Layers3} title="Hidden Panels" />
      <p className="max-w-2xl text-[length:var(--conversation-caption-font-size)] leading-(--conversation-caption-line-height) text-(--ui-text-tertiary)">
        Main chat stays clean. The removed Hermes panels are still available here when you need them.
      </p>

      <div className="mt-4">
        <div className="mb-1.5 text-[length:var(--conversation-caption-font-size)] font-medium text-(--ui-text-secondary)">
          Workspace
        </div>
        <div className="divide-y divide-(--ui-stroke-tertiary)">
          <FileBrowserPanelRow />
          {WORKSPACE_PANELS.map(panel => (
            <PanelRow key={panel.title} panel={panel} />
          ))}
        </div>
      </div>

      <div className="mt-5">
        <div className="mb-1.5 text-[length:var(--conversation-caption-font-size)] font-medium text-(--ui-text-secondary)">
          Automation
        </div>
        <PanelGroup panels={SYSTEM_PANELS} />
      </div>

      <div className="mt-5">
        <div className="mb-1.5 text-[length:var(--conversation-caption-font-size)] font-medium text-(--ui-text-secondary)">
          Profiles & Gateway
        </div>
        <PanelGroup panels={PROFILE_PANELS} />
      </div>
    </SettingsContent>
  )
}
''', encoding="utf-8")

settings_index_text = settings_index.read_text(encoding="utf-8")
settings_index_text = ensure_named_import(settings_index_text, "@/lib/icons", ["Brain", "Layers3"])
settings_index_text = settings_index_text.replace(
    "import { HiddenPanelsSettings } from './hidden-panels-settings'\nimport { HiddenPanelsSettings } from './hidden-panels-settings'\n",
    "import { HiddenPanelsSettings } from './hidden-panels-settings'\n",
)
while "import { HiddenPanelsSettings } from './hidden-panels-settings'\nimport { HiddenPanelsSettings } from './hidden-panels-settings'\n" in settings_index_text:
    settings_index_text = settings_index_text.replace(
        "import { HiddenPanelsSettings } from './hidden-panels-settings'\nimport { HiddenPanelsSettings } from './hidden-panels-settings'\n",
        "import { HiddenPanelsSettings } from './hidden-panels-settings'\n",
    )
settings_index_text = settings_index_text.replace(
    "import { MemSettings } from './mem-settings'\nimport { MemSettings } from './mem-settings'\n",
    "import { MemSettings } from './mem-settings'\n",
)
while "import { MemSettings } from './mem-settings'\nimport { MemSettings } from './mem-settings'\n" in settings_index_text:
    settings_index_text = settings_index_text.replace(
        "import { MemSettings } from './mem-settings'\nimport { MemSettings } from './mem-settings'\n",
        "import { MemSettings } from './mem-settings'\n",
    )
settings_index_text = settings_index_text.replace(
    "import { MemSettings } from './mem-settings'\nimport { HiddenPanelsSettings } from './hidden-panels-settings'\nimport { MemSettings } from './mem-settings'\n",
    "import { MemSettings } from './mem-settings'\nimport { HiddenPanelsSettings } from './hidden-panels-settings'\n",
)
settings_index_text = settings_index_text.replace("Archive, Bell, Brain, Brain,", "Archive, Bell, Brain,")
settings_index_text = settings_index_text.replace("  'mem',\n  'mem',\n", "  'mem',\n")
settings_index_text = settings_index_text.replace(
    "  'hidden-panels',\n  'hidden-panels',\n",
    "  'hidden-panels',\n",
)
settings_index_text = settings_index_text.replace(
    """          <OverlayNavItem
            active={activeView === 'mem'}
            icon={Brain}
            label="Hermes Mem"
            onClick={() => setActiveView('mem')}
          />
          <OverlayNavItem
            active={activeView === 'mem'}
            icon={Brain}
            label="Hermes Mem"
            onClick={() => setActiveView('mem')}
          />""",
    """          <OverlayNavItem
            active={activeView === 'mem'}
            icon={Brain}
            label="Hermes Mem"
            onClick={() => setActiveView('mem')}
          />""",
)
settings_index_text = settings_index_text.replace(
    """          ) : activeView === 'mem' ? (
            <MemSettings onConfigSaved={onConfigSaved} />
          ) : activeView === 'mem' ? (
            <MemSettings onConfigSaved={onConfigSaved} />
          ) :""",
    """          ) : activeView === 'mem' ? (
            <MemSettings onConfigSaved={onConfigSaved} />
          ) :""",
)
deduped_lines = []
seen_exact_imports = set()
for line in settings_index_text.splitlines():
    if line.startswith("import { MemSettings } from './mem-settings'") or line.startswith(
        "import { HiddenPanelsSettings } from './hidden-panels-settings'"
    ):
        if line in seen_exact_imports:
            continue
        seen_exact_imports.add(line)
    deduped_lines.append(line)
settings_index_text = "\n".join(deduped_lines) + "\n"
settings_index.write_text(settings_index_text, encoding="utf-8")

types_text = types.read_text(encoding="utf-8")
types_text = types_text.replace("  | 'mem'\n  | 'mem'\n", "  | 'mem'\n")
types_text = types_text.replace("  | 'hidden-panels'\n  | 'hidden-panels'\n", "  | 'hidden-panels'\n")
types.write_text(types_text, encoding="utf-8")

app_shell_text = app_shell.read_text(encoding="utf-8")
while "  const showStatusbar = false\n  const showStatusbar = false\n" in app_shell_text:
    app_shell_text = app_shell_text.replace(
        "  const showStatusbar = false\n  const showStatusbar = false\n",
        "  const showStatusbar = false\n",
    )
app_shell_text = app_shell_text.replace("  const SYSTEM_TOOL_COUNT = 4", "  const SYSTEM_TOOL_COUNT = 1")
app_shell_text = app_shell_text.replace(
    '<Slot area="titleBar.right" />',
    '{false && <Slot area="titleBar.right" />}',
)
app_shell_text = app_shell_text.replace(
    '{false && {false && <Slot area="titleBar.right" />}}',
    '{false && <Slot area="titleBar.right" />}',
)
app_shell.write_text(app_shell_text, encoding="utf-8")

wiring = desktop / "src/app/contrib/wiring.tsx"
if wiring.exists():
    wiring_text = wiring.read_text(encoding="utf-8")
    wiring_text = wiring_text.replace("  const SYSTEM_TOOL_COUNT = 4", "  const SYSTEM_TOOL_COUNT = 1")
    wiring.write_text(wiring_text, encoding="utf-8")

theme_context = desktop / "src/themes/context.tsx"
theme_context_text = theme_context.read_text(encoding="utf-8")
theme_context_text = theme_context_text.replace("const RETIRED_SKINS = new Set(['nous-light', 'default', 'gold'])\n", "")
theme_context_text = re.sub(
    r"const normalizeSkin = \(name: string \| null\): string =>\n\s*name && resolveTheme\(name\) && !RETIRED_SKINS\.has\(name\) \? name : DEFAULT_SKIN_NAME",
    """// MEM_THEME_DEFAULT: the original Linux MEM appearance on every OS.
const normalizeSkin = (_name: string | null): string => 'mono'""",
    theme_context_text,
    count=1,
)
theme_context_text = re.sub(
    r"const normalizeMode = \(value: string \| null\): ThemeMode =>\n\s*value === 'light' \|\| value === 'dark' \|\| value === 'system' \? value : 'light'",
    "const normalizeMode = (_value: string | null): ThemeMode => 'dark'",
    theme_context_text,
    count=1,
)
theme_context.write_text(theme_context_text, encoding="utf-8")

native_notifications = desktop / "src/store/native-notifications.ts"
if native_notifications.exists():
    native_notifications_text = native_notifications.read_text(encoding="utf-8")
    native_notifications_text = native_notifications_text.replace(
        "const DEFAULT_PREFS: NativeNotificationPrefs = {\n  enabled: false,",
        "const DEFAULT_PREFS: NativeNotificationPrefs = {\n  enabled: true,",
    )
    native_notifications_text = native_notifications_text.replace(
        "export function dispatchNativeNotification(input: NativeNotificationInput): void {\n  void input\n  return\n\n  void input\n  return\n\n  const prefs = $nativeNotifyPrefs.get()",
        "export function dispatchNativeNotification(input: NativeNotificationInput): void {\n  const prefs = $nativeNotifyPrefs.get()",
    )
    native_notifications_text = native_notifications_text.replace(
        "export function dispatchNativeNotification(input: NativeNotificationInput): void {\n  void input\n  return\n\n  const prefs = $nativeNotifyPrefs.get()",
        "export function dispatchNativeNotification(input: NativeNotificationInput): void {\n  const prefs = $nativeNotifyPrefs.get()",
    )
    native_notifications.write_text(native_notifications_text, encoding="utf-8")

composer_context_menu = desktop / "src/app/chat/composer/context-menu.tsx"
if composer_context_menu.exists():
    composer_context_menu_text = composer_context_menu.read_text(encoding="utf-8")
    composer_context_menu_text = composer_context_menu_text.replace(
        """                GHOST_ICON_BTN,
                'rounded-full! border border-(--ui-stroke-tertiary) bg-(--ui-control-hover-background) data-[state=open]:bg-(--chrome-action-hover) data-[state=open]:text-foreground'""",
        """                GHOST_ICON_BTN,
                'data-[state=open]:bg-(--chrome-action-hover) data-[state=open]:text-foreground'""",
    )
    composer_context_menu.write_text(composer_context_menu_text, encoding="utf-8")

styles = desktop / "src/styles.css"
styles_text = styles.read_text(encoding="utf-8")
readability_css = r"""
/* MEM readable UI scale: Hermes defaults are compact; this keeps the clean UI
   but makes chat usable on large desktop monitors. */
:root {
  --conversation-text-font-size: 0.96875rem;
  --conversation-tool-font-size: 0.875rem;
  --conversation-caption-font-size: 0.875rem;
  --conversation-line-height: 1.5rem;
  --conversation-caption-line-height: 1.2rem;
  --paragraph-gap: 0.85rem;
  --composer-width: 68rem;
  --composer-control-size: 1.875rem;
  --composer-control-primary-size: 2rem;
  --composer-input-min-height: 2.0625rem;
  --composer-fallback-height: 3.25rem;
  --sidebar-width: 22rem;
  --chat-min-width: 38rem;
}

body {
  font-size: 1rem;
}

[data-slot='sidebar'] {
  font-size: 1rem;
}

[data-slot='sidebar-menu-button'] {
  min-height: 1.75rem;
  font-size: 0.875rem;
  line-height: 1.15;
}

[data-slot='sidebar-group-label'] {
  font-size: 0.875rem;
}

[data-slot='sidebar'] [class*='SidebarRow'],
[data-slot='sidebar'] [data-slot='sidebar-group-content'] {
  font-size: 1rem;
}

[data-slot='sidebar'] [class*='min-h-\[1\.625rem\]'] {
  min-height: 2rem;
}

[data-slot='sidebar'] [class*='text-\[0\.8125rem\]'] {
  font-size: 1rem !important;
  line-height: 1.25 !important;
}

[data-slot='sidebar'] [class*='text-\[0\.75rem\]'] {
  font-size: 0.875rem !important;
}

[data-slot='aui_thread-content'] {
  max-width: min(var(--composer-width), calc(100vw - 3rem));
}

[data-slot='composer-rich-input'] {
  font-size: var(--conversation-text-font-size);
}
"""
styles_text = re.sub(
    r"\n/\* MEM readable UI scale:.*?\n\[data-slot='composer-rich-input'\] \{\n  font-size: var\(--conversation-text-font-size\);\n\}\n",
    "\n",
    styles_text,
    flags=re.DOTALL,
)
styles.write_text(styles_text.rstrip() + "\n" + readability_css.strip() + "\n", encoding="utf-8")

required_markers = [
    (mem_settings, "export function MemSettings"),
    (mem_settings, "<MemoryDashboardSettings />"),
    (memory_dashboard_settings, "export function MemoryDashboardSettings"),
    (memory_dashboard_settings, "DELETE_ALL_MEMORY"),
    (hidden_panels, "export function HiddenPanelsSettings"),
    (hidden_panels, "<FileBrowserPanelRow />"),
    (settings_index, "<MemSettings"),
    (sidebar, "MEM_SIDEBAR_NAV"),
    (titlebar, "tool.id === 'settings'"),
    (store_session, "$temporaryChatMode"),
    (context_menu, "Temporary chat active"),
    (composer_index, 'data-slot="temporary-chat-chip"'),
    (theme_context, "MEM_THEME_DEFAULT"),
    (layout_store, "MEM_FILE_BROWSER_HIDDEN"),
    (session_actions_hook, "ephemeral: true"),
    (acp_session, "ephemeral"),
    (acp_server, "_disable_hermes_memory_tools"),
    (tui_privacy_test, "test_temporary_agent_factory_accepts_privacy_flags"),
    (styles, "MEM readable UI scale"),
]
if electron_main.exists():
    required_markers.append((electron_main, "hermes:memory:dashboard"))
if preload.exists():
    required_markers.append((preload, "hermes:memory:clear-all"))
if global_types.exists():
    required_markers.append((global_types, "clearAll: (payload: { confirmation: string })"))
for backend_path in (api_server, tui_server):
    if backend_path.exists():
        required_markers.append((backend_path, "disable_memory_mcp"))

missing_markers = []
for required_path, marker in required_markers:
    if not required_path.exists() or marker not in required_path.read_text(encoding="utf-8"):
        missing_markers.append(f"{required_path}: {marker}")
if missing_markers:
    details = "\n  - ".join(missing_markers)
    raise SystemExit(f"Hermes Mem patch validation failed; upstream Hermes is incompatible:\n  - {details}")

print("Hermes Desktop simple UI patch applied.")
PY

if [ "$DO_PACK" -eq 1 ]; then
  cd "$HERMES_ROOT"
  CSC_IDENTITY_AUTO_DISCOVERY=false npm run pack --workspace apps/desktop
fi
