from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "install.sh"
UI_PATCHER = ROOT / "scripts" / "apply-hermes-simple-ui.sh"
SOUL = ROOT / "hermes-soul.md"


def run_installer(
    *args: str,
    platform: str = "Darwin",
    home: Path | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "AI_MEMORY_PLATFORM": platform}
    env["HERMES_MEM_LATEST_VERSION"] = "0.2.0b11"
    if home is not None:
        env["HOME"] = str(home)
    return subprocess.run(
        ["bash", str(INSTALLER), *args],
        cwd=ROOT,
        env=env,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )


def test_shell_scripts_parse_with_macos_bash() -> None:
    for script in (INSTALLER, UI_PATCHER):
        result = subprocess.run(["bash", "-n", str(script)], text=True, capture_output=True, check=False)
        assert result.returncode == 0, result.stderr


def test_help_exposes_only_the_three_actions() -> None:
    result = run_installer("--help")
    assert result.returncode == 0, result.stderr
    for command in ("install", "delete", "update"):
        assert command in result.stdout
    for old_command in ("doctor", "backup", "restore", "reset-memory", "uninstall"):
        assert old_command not in result.stdout


def make_installed(home: Path, version: str = "0.2.0b11", directory: str = ".hermes-mem") -> Path:
    mem_home = home / directory
    (mem_home / "hermes/hermes-agent").mkdir(parents=True)
    (mem_home / "memory").mkdir()
    (mem_home / "memory/config.toml").write_text("timezone = \"UTC\"\n", encoding="utf-8")
    (mem_home / ".installed-version").write_text(f"{version}\n", encoding="utf-8")
    return mem_home


def test_menu_has_exactly_three_actions(tmp_path: Path) -> None:
    result = run_installer(home=tmp_path, input_text="2\n")
    assert result.returncode == 0, result.stderr
    assert "1) Install" in result.stdout
    assert "2) Delete" in result.stdout
    assert "3) Update" in result.stdout
    assert "Select [1-3]" in result.stdout


def test_install_reports_when_already_installed(tmp_path: Path) -> None:
    make_installed(tmp_path)
    result = run_installer(home=tmp_path, input_text="1\n")
    assert result.returncode == 0, result.stderr
    assert "Hermes Mem Beta 0.2 is already installed." in result.stdout


def test_delete_reports_when_not_installed(tmp_path: Path) -> None:
    result = run_installer(home=tmp_path, input_text="2\n")
    assert result.returncode == 0, result.stderr
    assert "Hermes Mem is not installed." in result.stdout


def test_update_fails_when_not_installed(tmp_path: Path) -> None:
    result = run_installer(home=tmp_path, input_text="3\n")
    assert result.returncode != 0
    assert "Hermes Mem is not installed." in result.stderr


def test_update_reports_latest_version_without_network(tmp_path: Path) -> None:
    make_installed(tmp_path)
    result = run_installer(home=tmp_path, input_text="3\n")
    assert result.returncode == 0, result.stderr
    assert "already on the latest version: Beta 0.2 (0.2.0b11)" in result.stdout


def run_update_decision_probe(
    tmp_path: Path,
    *,
    installed_version: str,
    online_version: str,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    probe_installer = tmp_path / "install-probe.sh"
    installer_text = INSTALLER.read_text(encoding="utf-8")
    marker = "    update_flow\n    ;;\n"
    assert installer_text.count(marker) == 1
    probe_installer.write_text(
        installer_text.replace(marker, "    printf 'PROBE_UPDATE_FLOW\\n'\n    ;;\n"),
        encoding="utf-8",
    )
    mem_home = make_installed(tmp_path, version=installed_version)
    db = mem_home / "memory/memory.sqlite3"
    db.write_text("preserve-memory", encoding="utf-8")
    env = {
        **os.environ,
        "AI_MEMORY_PLATFORM": "Darwin",
        "HERMES_MEM_LATEST_VERSION": online_version,
        "HOME": str(tmp_path),
    }
    result = subprocess.run(
        ["bash", str(probe_installer), "update"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    return result, db


def test_update_prefers_a_newer_local_beta_without_touching_memory(tmp_path: Path) -> None:
    result, db = run_update_decision_probe(
        tmp_path,
        installed_version="0.1.0b1",
        online_version="0.1.0b1",
    )
    assert result.returncode == 0, result.stderr
    assert "Updating Hermes Mem from this folder: 0.1.0b1 -> Beta 0.2 (0.2.0b11)." in result.stdout
    assert "PROBE_UPDATE_FLOW" in result.stdout
    assert db.read_text(encoding="utf-8") == "preserve-memory"


def test_beta_02_b10_can_update_to_search_hotfix_without_touching_memory(
    tmp_path: Path,
) -> None:
    result, db = run_update_decision_probe(
        tmp_path,
        installed_version="0.2.0b10",
        online_version="0.2.0b10",
    )
    assert result.returncode == 0, result.stderr
    assert (
        "Updating Hermes Mem from this folder: 0.2.0b10 -> "
        "Beta 0.2 (0.2.0b11)."
    ) in result.stdout
    assert "PROBE_UPDATE_FLOW" in result.stdout
    assert db.read_text(encoding="utf-8") == "preserve-memory"


def test_update_refuses_to_downgrade_a_newer_install(tmp_path: Path) -> None:
    result, db = run_update_decision_probe(
        tmp_path,
        installed_version="0.3.0b1",
        online_version="0.2.0b11",
    )
    assert result.returncode == 0, result.stderr
    assert "newer than the online release 0.2.0b11; refusing to downgrade" in result.stdout
    assert "PROBE_UPDATE_FLOW" not in result.stdout
    assert db.read_text(encoding="utf-8") == "preserve-memory"


def test_delete_requires_exact_phrase_and_only_removes_mem(tmp_path: Path) -> None:
    mem_home = make_installed(tmp_path)
    regular_hermes = tmp_path / ".hermes"
    regular_hermes.mkdir()
    sentinel = regular_hermes / "keep-me"
    sentinel.write_text("regular Hermes data", encoding="utf-8")

    cancelled = run_installer(home=tmp_path, input_text="2\nDELETE\n")
    assert cancelled.returncode != 0
    assert "DELETE_HERMES_MEM" in cancelled.stdout
    assert mem_home.exists()

    deleted = run_installer(home=tmp_path, input_text="2\nDELETE_HERMES_MEM\n")
    assert deleted.returncode == 0, deleted.stderr
    assert "all Hermes Mem memory and chats will be permanently deleted" in deleted.stdout
    assert "first back up this entire folder" in deleted.stdout
    assert not mem_home.exists()
    assert sentinel.read_text(encoding="utf-8") == "regular Hermes data"


def test_legacy_fpp_install_is_migrated_before_deletion(tmp_path: Path) -> None:
    legacy_home = make_installed(tmp_path, version="0.2.0", directory=".hermes-fpp")
    deleted = run_installer(home=tmp_path, input_text="2\nDELETE_HERMES_MEM\n")
    assert deleted.returncode == 0, deleted.stderr
    assert "[1/2] Stopping Hermes Mem... done" in deleted.stdout
    assert "[2/2] Deleting Hermes Mem data... done" in deleted.stdout
    assert not legacy_home.exists()
    assert not (tmp_path / ".hermes-mem").exists()


def test_legacy_migration_replaces_the_old_default_timezone(tmp_path: Path, monkeypatch) -> None:
    make_installed(tmp_path, version="0.2.0", directory=".hermes-fpp")
    monkeypatch.setenv("HERMES_MEMORY_TIMEZONE", "Europe/Moscow")
    cancelled = run_installer(home=tmp_path, input_text="2\nCANCEL\n")
    assert cancelled.returncode != 0
    assert not (tmp_path / ".hermes-fpp").exists()
    config = (tmp_path / ".hermes-mem/memory/config.toml").read_text(encoding="utf-8")
    assert 'timezone = "Europe/Moscow"' in config


def test_legacy_install_rebuilds_only_relocatable_environments() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    migration = text[text.index("migrate_legacy_install() {") : text.index("migrate_legacy_install\n")]
    assert 'rm -rf -- "$HERMES_ROOT/venv" "$VENV_DIR"' in migration
    assert '"$DB_PATH"' not in migration


def test_installer_and_package_versions_match() -> None:
    installer_text = INSTALLER.read_text(encoding="utf-8")
    project_text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    package_text = (ROOT / "src/ai_memory_mcp/__init__.py").read_text(encoding="utf-8")
    installer_version = re.search(r'^MEM_VERSION="\$\{HERMES_MEM_VERSION:-(.+)\}"$', installer_text, re.MULTILINE)
    project_version = re.search(r'^version = "(.+)"$', project_text, re.MULTILINE)
    package_version = re.search(r'^__version__ = "(.+)"$', package_text, re.MULTILINE)
    assert installer_version and project_version and package_version
    assert installer_version.group(1) == project_version.group(1)
    assert project_version.group(1) == package_version.group(1)


def test_project_metadata_points_to_the_release_repository() -> None:
    project_text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "0.2.0b11"' in project_text
    assert 'readme = "README.md"' in project_text
    assert project_text.count("https://github.com/FPP-Labs/hermes_mem") == 2


def test_beta_brand_and_upstream_attribution_are_distributed() -> None:
    installer_text = INSTALLER.read_text(encoding="utf-8")
    patcher_text = UI_PATCHER.read_text(encoding="utf-8")
    project_text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    soul_text = SOUL.read_text(encoding="utf-8")
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    notice_text = (ROOT / "NOTICE").read_text(encoding="utf-8")
    assert "Hermes Mem" in installer_text
    assert 'MEM_VERSION_LABEL="Beta 0.2"' in installer_text
    assert 'package_data["version"] = "0.2.0-beta.11"' in patcher_text
    assert 'build["appId"] = "app.hermesmem.desktop"' in patcher_text
    assert '"schemes": ["hermes-mem"]' in patcher_text
    assert "FPP-Labs/hermes_mem" in installer_text
    assert '"const APP_NAME = \'Hermes Mem\'"' in patcher_text
    assert "return app.getVersion()" in patcher_text
    assert 'package_data["author"]' not in patcher_text
    assert 'build["copyright"]' not in patcher_text
    for text in (installer_text, patcher_text, project_text, soul_text, license_text, notice_text):
        assert "Nous Research" in text
    assert "Hermes Mem Beta 0.2" in notice_text
    assert "not an official Nous Research product" in notice_text


def test_installer_avoids_gnu_only_path_and_bash4_operations() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    assert "realpath -m" not in text
    assert "readlink -f" not in text
    assert ",,}" not in text


def test_macos_install_has_native_app_and_browser_checks() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    assert 'Darwin) PLATFORM="macos"' in text
    assert 'BROWSER_CACHE_DIR="$MEM_HOME/browser-cache"' in text
    assert "npx playwright install chromium" not in text
    assert 'codesign --verify --deep --strict' in text
    assert 'Hermes Mem.app' in text


def test_installer_repairs_desktop_dependencies_before_building() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    for dependency in ("@vitejs/plugin-react", "@tailwindcss/vite", "electron-builder"):
        assert dependency in text
    assert 'install --workspace apps/desktop --include=dev --no-audit --no-fund' in text
    assert "node_command() {" in text
    assert "npm_command() {" in text
    assert 'command -v node 2>/dev/null' in text
    assert 'command -v npm 2>/dev/null' in text
    assert 'npm_bin="$(npm_command || true)"' in text
    assert "Hermes-managed runtime or system PATH" in text
    assert "for attempt in 1 2 3 4 5 6" in text
    assert "--prefer-offline" in text
    assert "NPM_CONFIG_FETCH_RETRIES=10" in text
    assert "NPM_CONFIG_FETCH_TIMEOUT=300000" in text
    assert "NPM_CONFIG_MAXSOCKETS=3" in text
    assert "dependency download failed after 6 attempts" in text
    assert "recover_desktop_npm_tarballs" in text
    assert "https://registry.npmjs.org/" in text
    assert "crypto.createHash('sha512')" in text
    assert '"$npm_bin" cache add "$tarball"' in text
    assert "CI=1 \\" in text
    desktop_phase = text[text.index("desktop_build_phase() {") : text.index("launcher_phase() {")]
    assert desktop_phase.index("ensure_desktop_dependencies") < desktop_phase.index("apply_hermes_desktop_ui")


def test_duckduckgo_search_is_installed_and_selected_by_default() -> None:
    installer_text = INSTALLER.read_text(encoding="utf-8")
    patcher_text = UI_PATCHER.read_text(encoding="utf-8")
    provider_text = (ROOT / "hermes-patches/hermes_ddgs_provider.py").read_text(
        encoding="utf-8"
    )
    agent_phase = installer_text[installer_text.index("agent_phase() {") : installer_text.index("install_memory_phase() {")]
    search_config = installer_text[
        installer_text.index("configure_web_search() {") : installer_text.index("install_hermes_soul() {")
    ]
    assert 'DDGS_VERSION="9.14.4"' in installer_text
    assert '"ddgs==$DDGS_VERSION"' in installer_text
    assert "ensure_ddgs_dependency" in agent_phase
    assert 'install_agent_python_package "ddgs==$DDGS_VERSION"' in installer_text
    assert 'set_web_backend "ddgs"' in search_config
    assert 'patch_assets / "hermes_ddgs_provider.py"' in patcher_text
    assert 'hermes_root / "plugins/web/ddgs/provider.py"' in patcher_text
    assert 'dns_resolver="system"' in provider_text
    assert "def _run_html_fallback(" in provider_text


def test_agent_dependencies_support_uv_venvs_without_pip() -> None:
    installer_text = INSTALLER.read_text(encoding="utf-8")
    helper = installer_text[
        installer_text.index("install_agent_python_package() {") :
        installer_text.index("ensure_ddgs_dependency() {")
    ]
    assert 'managed_uv="$HERMES_HOME/bin/uv"' in helper
    assert '"$managed_uv" pip install' in helper
    assert '--python "$python_bin"' in helper
    assert '"$python_bin" -m ensurepip --upgrade' in helper
    assert helper.index('"$managed_uv" pip install') < helper.index('"$python_bin" -m pip install')


def test_youtube_understanding_dependency_tool_and_policy_are_distributed() -> None:
    installer_text = INSTALLER.read_text(encoding="utf-8")
    patcher_text = UI_PATCHER.read_text(encoding="utf-8")
    soul_text = SOUL.read_text(encoding="utf-8")
    agent_phase = installer_text[
        installer_text.index("agent_phase() {") : installer_text.index("install_memory_phase() {")
    ]

    assert 'YOUTUBE_TRANSCRIPT_API_VERSION="1.2.4"' in installer_text
    assert '"youtube-transcript-api==$YOUTUBE_TRANSCRIPT_API_VERSION"' in installer_text
    assert "ensure_youtube_dependency" in agent_phase
    assert 'install_agent_python_package "youtube-transcript-api==$YOUTUBE_TRANSCRIPT_API_VERSION"' in installer_text
    assert 'patch_assets / "hermes_youtube_transcript_tool.py"' in patcher_text
    assert 'hermes_root / "tools/hermes_youtube_transcript_tool.py"' in patcher_text
    assert 'name="youtube_transcript"' in patcher_text
    assert "prefetch_youtube_context(original_user_message)" in patcher_text
    assert 'hermes_root / "skills/media/youtube-content"' in patcher_text
    assert "shutil.rmtree(youtube_skill_directory)" in patcher_text
    for text in (installer_text, soul_text):
        assert "loaded automatically before the main model answers" in text
        assert "transcript_only" in text
        assert "untrusted source material" in text


def test_mem_settings_expose_duckduckgo_and_searxng() -> None:
    patcher_text = UI_PATCHER.read_text(encoding="utf-8")
    for marker in (
        "Search provider",
        "DuckDuckGo",
        "SearXNG server",
        "SearXNG port",
        "SEARXNG_URL",
        "web', 'search_backend",
    ):
        assert marker in patcher_text


def test_installer_never_prompts_for_voice_or_search_settings() -> None:
    installer_text = INSTALLER.read_text(encoding="utf-8")
    for forbidden_prompt in (
        "ElevenLabs API key (",
        "ElevenLabs voice id (",
        "Web search API key",
        "Web search provider [",
        "SearXNG URL/IP",
    ):
        assert forbidden_prompt not in installer_text
    assert "configure_elevenlabs" not in installer_text
    assert "CONFIGURE_ELEVENLABS" not in installer_text
    assert "CONFIGURE_WEB_SEARCH" not in installer_text


def test_hermes_agent_is_pinned_to_the_tested_release() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    assert 'HERMES_AGENT_VERSION="0.18.2"' in text
    assert 'HERMES_AGENT_COMMIT="36f2a966c7f9f69987494b867c3dcf96b69a5766"' in text
    assert 'HERMES_AGENT_BOOTSTRAP_URL="https://raw.githubusercontent.com/NousResearch/hermes-agent/$HERMES_AGENT_COMMIT/scripts/install.sh"' in text
    assert '--commit "$HERMES_AGENT_COMMIT"' in text
    assert "hermes_agent_is_pinned" in text


def test_install_and_update_use_seven_quiet_numbered_steps() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    install_flow = text[text.index("install_flow() {") : text.index("update_flow() {")]
    update_flow = text[text.index("update_flow() {") : text.index("cleanup_legacy_brand_artifacts() {")]
    assert install_flow.count("quiet_step") == 7
    assert update_flow.count("quiet_step") == 7
    assert 'quiet_step 1 7 "Preparing your system"' in install_flow
    assert 'quiet_step 7 7 "Verifying the installation"' in install_flow
    assert 'quiet_step 1 7 "Preparing the update"' in update_flow
    assert 'quiet_step 7 7 "Verifying the update"' in update_flow
    assert "tail -n 20" in text
    assert 'error_log="$MEM_HOME/install-error.log"' in text


def test_install_only_reports_complete_for_the_current_version() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    install_case = text[text.index("  install)\n") : text.index("  delete)\n")]
    assert 'if [ "$(installed_version)" = "$MEM_VERSION" ]; then' in install_case
    assert 'rm -f -- "$INSTALL_MARKER"' in text


def test_installer_skips_revalidating_an_existing_memory_server() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    assert "memory_server_is_configured" in text
    assert 'log "Hermes MCP server is already configured"' in text
    configure = text[text.index("configure_hermes() {") : text.index("backup_hermes_config() {")]
    assert configure.index("memory_server_is_configured") < configure.index("run_hermes mcp remove")
    assert 'HERMES_MCP_ADD_TIMEOUT_SECONDS:-60' in configure


def test_mem_paths_are_isolated_from_regular_hermes() -> None:
    installer_text = INSTALLER.read_text(encoding="utf-8")
    patcher_text = UI_PATCHER.read_text(encoding="utf-8")
    assert 'MEM_HOME="${HERMES_MEM_HOME:-"$USER_HOME/.hermes-mem"}"' in installer_text
    assert 'HOME="$MEM_RUNTIME_HOME"' in installer_text
    assert '--dir "$HERMES_ROOT" --hermes-home "$HERMES_HOME"' in installer_text
    assert 'const MEM_INSTALL_HOME =' in patcher_text
    for shared_path in (
        '$HOME/.hermes"',
        '$HOME/.config/Hermes',
        '$HOME/.cache/Hermes',
        '$HOME/Library/Application Support/Hermes',
    ):
        assert shared_path not in installer_text


def test_ui_patcher_enforces_the_cross_platform_mem_contract() -> None:
    text = UI_PATCHER.read_text(encoding="utf-8")
    for marker in (
        "MEM_SIDEBAR_NAV",
        "MEM_THEME_DEFAULT",
        "MEM_FILE_BROWSER_HIDDEN",
        "tool.id === 'settings'",
        "Temporary chat active",
        "ephemeral: true",
        "disable_memory_mcp",
        "MemoryDashboardSettings",
        "hermes:memory:dashboard",
        "hermes:memory:clear-all",
        "DELETE_ALL_MEMORY",
    ):
        assert marker in text
    assert "FppSettings" not in text
    assert "'fpp'" not in text
    assert 'legacy_settings = desktop / "src/app/settings/fpp-settings.tsx"' in text
    assert "legacy_settings.unlink()" in text

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


def test_readme_has_one_command_install_and_release_safety_details() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "git clone https://github.com/FPP-Labs/hermes_mem.git && cd hermes_mem && ./install.sh" in text
    assert "Hermes Agent `0.18.2`" in text
    assert "36f2a966c7f9f69987494b867c3dcf96b69a5766" in text
    assert "DELETE_ALL_MEMORY" in text
    assert "Nous Research" in text

def test_unsupported_platform_fails_before_installing() -> None:
    result = run_installer("--help", platform="Windows_NT")
    assert result.returncode != 0
    assert "unsupported operating system" in result.stderr


def test_prompt_follows_the_users_current_language() -> None:
    required_rules = (
        "Detect the language of the user's current message and answer in that same language.",
        "Never let stored memory, profile data, examples, tool output, or the system's default locale override",
    )
    for path in (SOUL, INSTALLER):
        text = path.read_text(encoding="utf-8")
        for rule in required_rules:
            assert rule in text


def test_prompt_documents_automatic_memory_quotes_and_preserves_unresolved_plans() -> None:
    required_rules = (
        "Relevant memory is loaded automatically",
        "exact visible user/assistant turn is archived automatically",
        "memory.search_exact_quotes",
        "Only results marked as exact verbatim turns",
        "Preserve negation, uncertainty, and modality exactly",
        'use event_type "plan" and status "planned"; never invent a start date.',
        "ask for an update instead of assuming it happened.",
    )
    for path in (SOUL, INSTALLER):
        text = path.read_text(encoding="utf-8")
        for rule in required_rules:
            assert rule in text


def test_desktop_patcher_installs_code_level_memory_read_and_write_bridges() -> None:
    patcher = UI_PATCHER.read_text(encoding="utf-8")
    bridge = (ROOT / "hermes-patches/hermes_mem_autocapture.py").read_text(encoding="utf-8")
    assert "prefetch_memory_context(agent, original_user_message)" in patcher
    assert "capture_completed_turn(" in patcher
    assert "turn_finalizer.py" in patcher
    assert "turn_context.py" in patcher
    assert "def prefetch_memory_context(" in bridge
    assert "def capture_completed_turn(" in bridge
    assert "if not _memory_enabled(agent):" in bridge
    assert "memory.search_exact_quotes" in SOUL.read_text(encoding="utf-8")


def test_distributed_project_text_is_english_only() -> None:
    paths = [SOUL, INSTALLER, UI_PATCHER]
    paths.extend((ROOT / "src").rglob("*.py"))
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert not any("\u0400" <= character <= "\u04ff" for character in text), path
