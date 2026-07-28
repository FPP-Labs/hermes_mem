"""Hermes Mem regression coverage for desktop YouTube routing."""

def test_acp_session_exposes_youtube_transcript():
    import model_tools
    from acp_adapter.session import _expand_acp_enabled_toolsets
    model_tools._tool_defs_cache.clear()

    enabled = _expand_acp_enabled_toolsets(["hermes-acp"])
    definitions = model_tools.get_tool_definitions(
        enabled_toolsets=enabled,
        quiet_mode=True,
    )
    names = {
        definition["function"]["name"]
        for definition in definitions
    }

    assert "youtube_transcript" in names


def test_bundled_youtube_skill_is_removed_for_native_prefetch():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    assert not (root / "skills/media/youtube-content").exists()
