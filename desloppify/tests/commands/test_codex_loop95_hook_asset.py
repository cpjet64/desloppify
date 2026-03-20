from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[3]
HOOK_ASSET = REPO_ROOT / "docs" / "CODEX_LOOP95.hook.py"


def _load_hook_module():
    spec = importlib.util.spec_from_file_location("desloppify_codex_loop95_hook", HOOK_ASSET)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _summary(
    *,
    strict: float,
    kind: str,
    primary_command: str | None = None,
    secondary_command: str | None = None,
    backlog_summary: str | None = None,
    execution_summary: str | None = None,
    execution_primary_command: str | None = None,
) -> SimpleNamespace:
    scan_path = "."
    return SimpleNamespace(
        strict_score=strict,
        target_strict=95.0,
        scan_count=2,
        scan_path=scan_path,
        phase="execute",
        review_completed_for_scan=kind != "review",
        stale_subjective_count=0,
        unscored_subjective_count=0,
        under_target_subjective_count=2 if strict < 95.0 else 0,
        open_review_count=0,
        execution_count=1 if kind == "next" else 0,
        execution_primary_command=execution_primary_command,
        execution_summary=execution_summary,
        backlog_count=1 if kind == "promote" else 0,
        objective_backlog_count=1 if kind == "promote" else 0,
        backlog_promote_command=primary_command if kind == "promote" else None,
        backlog_summary=backlog_summary,
        review_prepare_command="desloppify review --prepare --path .",
        review_run_batches_command=(
            "desloppify review --run-batches --runner codex --parallel "
            "--scan-after-import --path ."
        ),
        action=SimpleNamespace(
            kind=kind,
            primary_command=primary_command or (f"desloppify scan --path {scan_path}" if kind == "scan" else None),
            secondary_command=secondary_command,
        ),
    )


def test_user_prompt_submit_activates_session_and_injects_context(tmp_path) -> None:
    hook_mod = _load_hook_module()
    payload = {
        "hook_event_name": "UserPromptSubmit",
        "prompt": "$desloppify-loop95 improve this repo",
        "session_id": "abc-123",
        "cwd": str(tmp_path),
    }

    response = hook_mod.handle_user_prompt_submit(
        payload,
        config_root=tmp_path,
        state_summary_fn=lambda _cwd: _summary(strict=84.0, kind="scan"),
    )

    assert "hookSpecificOutput" in response
    assert "No loop state exists yet" in response["hookSpecificOutput"]["additionalContext"]
    assert "`desloppify scan --path .`" in response["hookSpecificOutput"]["additionalContext"]
    session_state = hook_mod._read_session_state(tmp_path, "abc-123")
    assert session_state["enabled"] is True


def test_user_prompt_submit_uses_state_driven_next_guidance(tmp_path) -> None:
    hook_mod = _load_hook_module()
    payload = {
        "hook_event_name": "UserPromptSubmit",
        "prompt": "$desloppify-loop95 keep going",
        "session_id": "abc-124",
        "cwd": str(tmp_path),
    }

    response = hook_mod.handle_user_prompt_submit(
        payload,
        config_root=tmp_path,
        state_summary_fn=lambda _cwd: _summary(
            strict=90.0,
            kind="next",
            execution_summary="Fix stale plan item",
            execution_primary_command="desloppify next",
        ),
    )

    assert "Use `desloppify next`" in response["hookSpecificOutput"]["additionalContext"]
    assert "Top execution item: Fix stale plan item" in response["hookSpecificOutput"]["additionalContext"]
    assert "desloppify plan queue" in response["hookSpecificOutput"]["additionalContext"]


def test_stop_hook_blocks_for_review_before_execution(tmp_path) -> None:
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
        state_summary_fn=lambda _cwd: _summary(strict=84.0, kind="review"),
    )

    assert response["decision"] == "block"
    assert "strict 84.0/95.0" in response["reason"]
    assert "subjective review" in response["reason"]
    assert "review --run-batches --runner codex --parallel --scan-after-import" in response["reason"]
    assert "Do not inspect backlog or edit code" in response["reason"]


def test_stop_hook_blocks_open_review_before_backlog_or_code(tmp_path) -> None:
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
        state_summary_fn=lambda _cwd: _summary(
            strict=88.0,
            kind="show_review",
            primary_command="desloppify show review --status open",
        ),
    )

    assert response["decision"] == "block"
    assert "show review --status open" in response["reason"]
    assert "Do not inspect backlog or continue implementation work" in response["reason"]


def test_stop_hook_blocks_with_backlog_promotion_when_execution_is_empty(tmp_path) -> None:
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
        state_summary_fn=lambda _cwd: _summary(
            strict=88.0,
            kind="promote",
            primary_command="desloppify plan promote smells::src/a.py::dead-branch top",
            secondary_command="desloppify next",
            backlog_summary="Remove dead branch",
        ),
    )

    assert response["decision"] == "block"
    assert "promotable backlog remains" in response["reason"]
    assert "plan promote smells::src/a.py::dead-branch top" in response["reason"]
    assert "`desloppify next`" in response["reason"]


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
        state_summary_fn=lambda _cwd: _summary(strict=81.0, kind="blocked"),
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
        state_summary_fn=lambda _cwd: _summary(strict=95.6, kind="done"),
    )

    assert "target met" in response["systemMessage"]
