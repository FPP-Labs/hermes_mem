from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "install.sh"
UI_PATCHER = ROOT / "scripts" / "apply-hermes-simple-ui.sh"


def run_installer(*args: str, platform: str = "Darwin") -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "AI_MEMORY_PLATFORM": platform}
    return subprocess.run(
        ["bash", str(INSTALLER), *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_shell_scripts_parse_with_macos_bash() -> None:
    for script in (INSTALLER, UI_PATCHER):
        result = subprocess.run(["bash", "-n", str(script)], text=True, capture_output=True, check=False)
        assert result.returncode == 0, result.stderr


def test_help_exposes_the_small_command_surface() -> None:
    result = run_installer("--help")
    assert result.returncode == 0, result.stderr
    for command in ("update", "doctor", "backup", "restore PATH", "desktop", "reset-memory", "uninstall"):
        assert command in result.stdout
    assert "Choose an action" not in result.stdout


def test_installer_avoids_gnu_only_path_and_bash4_operations() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    assert "realpath -m" not in text
    assert "readlink -f" not in text
    assert ",,}" not in text


def test_macos_install_has_native_app_and_browser_checks() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    assert 'Darwin) PLATFORM="macos"' in text
    assert 'Library/Caches/ms-playwright' in text
    assert 'codesign --verify --deep --strict' in text
    assert '$mac_app/Contents/MacOS/Hermes' in text


def test_ui_patcher_enforces_the_cross_platform_fpp_contract() -> None:
    text = UI_PATCHER.read_text(encoding="utf-8")
    for marker in (
        "FPP_SIDEBAR_NAV",
        "FPP_THEME_DEFAULT",
        "FPP_FILE_BROWSER_HIDDEN",
        "tool.id === 'settings'",
        "Temporary chat active",
        "FPP_TUI_PRIVACY_SIGNATURE",
        "ephemeral: true",
        "disable_memory_mcp",
    ):
        assert marker in text

    grouped_menu_items = '''r"""\\1

          <ContextMenuItem icon={Clock} onSelect={onStartTemporaryChat}>'''
    split_menu_items = '''r"""\\1

          <DropdownMenuSeparator />
          <ContextMenuItem icon={Clock} onSelect={onStartTemporaryChat}>'''
    assert grouped_menu_items in text
    assert split_menu_items not in text
    assert "tui_gateway._make_agent privacy flags are missing" in text
    assert "test_temporary_agent_factory_accepts_privacy_flags" in text
    assert "<FileBrowserPanelRow />" in text


def test_unsupported_platform_fails_before_installing() -> None:
    result = run_installer("--help", platform="Windows_NT")
    assert result.returncode != 0
    assert "unsupported operating system" in result.stderr
