from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
HOOK_ASSET = REPO_ROOT / "docs" / "CODEX_LOOP95.hook.py"


def _load_hook_module():
    spec = importlib.util.spec_from_file_location("desloppify_codex_loop95_hook", HOOK_ASSET)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_user_prompt_submit_activates_session_and_injects_context(tmp_path) -> None:
    hook_mod = _load_hook_module()
    payload = {
        "hook_event_name": "UserPromptSubmit",
        "prompt": "$desloppify-loop95 improve this repo",
        "session_id": "abc-123",
        "cwd": str(tmp_path),
    }

    response = hook_mod.handle_user_prompt_submit(payload, config_root=tmp_path)

    assert "hookSpecificOutput" in response
    assert "strict >= 95.0" in response["hookSpecificOutput"]["additionalContext"]
    session_state = hook_mod._read_session_state(tmp_path, "abc-123")
    assert session_state["enabled"] is True


def test_stop_hook_blocks_when_loop95_session_is_active(tmp_path) -> None:
    hook_mod = _load_hook_module()
    hook_mod._write_session_state(tmp_path, "abc-123", {"enabled": True})
    payload = {
        "hook_event_name": "Stop",
        "permission_mode": "default",
        "session_id": "abc-123",
        "cwd": str(tmp_path),
        "last_assistant_message": "I think this is done.",
    }

    response = hook_mod.handle_stop(
        payload,
        config_root=tmp_path,
        state_summary_fn=lambda _cwd: {
            "strict_score": 84.0,
            "scan_count": 2,
            "scan_path": ".",
            "review_prepare_command": "desloppify review --prepare --path .",
            "stale_subjective_count": 1,
            "unscored_subjective_count": 0,
            "under_target_subjective_count": 2,
            "open_review_count": 0,
        },
    )

    assert response["decision"] == "block"
    assert "strict 84.0/95.0" in response["reason"]
    assert "review --run-batches --runner codex --parallel --scan-after-import" in response["reason"]


def test_stop_hook_allows_blocker_escape_hatch(tmp_path) -> None:
    hook_mod = _load_hook_module()
    hook_mod._write_session_state(tmp_path, "abc-123", {"enabled": True})
    payload = {
        "hook_event_name": "Stop",
        "permission_mode": "default",
        "session_id": "abc-123",
        "cwd": str(tmp_path),
        "last_assistant_message": "LOOP95_BLOCKED: `desloppify scan --path .` failed with Permission denied. strict 81.0",
    }

    response = hook_mod.handle_stop(
        payload,
        config_root=tmp_path,
        state_summary_fn=lambda _cwd: {
            "strict_score": 81.0,
            "scan_count": 2,
            "scan_path": ".",
            "review_prepare_command": "desloppify review --prepare --path .",
            "stale_subjective_count": 0,
            "unscored_subjective_count": 0,
            "under_target_subjective_count": 3,
            "open_review_count": 0,
        },
    )

    assert response == {}


def test_stop_hook_allows_completion_once_target_and_review_fresh(tmp_path) -> None:
    hook_mod = _load_hook_module()
    hook_mod._write_session_state(tmp_path, "abc-123", {"enabled": True})
    payload = {
        "hook_event_name": "Stop",
        "permission_mode": "default",
        "session_id": "abc-123",
        "cwd": str(tmp_path),
        "last_assistant_message": "All done.",
    }

    response = hook_mod.handle_stop(
        payload,
        config_root=tmp_path,
        state_summary_fn=lambda _cwd: {
            "strict_score": 95.6,
            "scan_count": 3,
            "scan_path": ".",
            "review_prepare_command": "desloppify review --prepare --path .",
            "stale_subjective_count": 0,
            "unscored_subjective_count": 0,
            "under_target_subjective_count": 0,
            "open_review_count": 0,
        },
    )

    assert "target met" in response["systemMessage"]
