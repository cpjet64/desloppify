from __future__ import annotations

import json
import re
import sys
from pathlib import Path

TARGET_STRICT = 95.0
SKILL_TOKEN = "$desloppify-loop95"
BLOCKER_TOKEN = "LOOP95_BLOCKED:"
SESSION_STATE_DIR = Path("hook_state") / "desloppify_loop95"


def _config_root(script_path: Path) -> Path:
    return script_path.resolve().parent.parent


def _session_state_path(config_root: Path, session_id: str) -> Path:
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", session_id).strip("._") or "session"
    return config_root / SESSION_STATE_DIR / f"{safe_name}.json"


def _read_session_state(config_root: Path, session_id: str) -> dict:
    path = _session_state_path(config_root, session_id)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_session_state(config_root: Path, session_id: str, payload: dict) -> None:
    path = _session_state_path(config_root, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _skill_activated(prompt: str) -> bool:
    return SKILL_TOKEN in prompt


def _is_blocked_message(last_assistant_message: str | None) -> bool:
    return BLOCKER_TOKEN in str(last_assistant_message or "")


def _state_summary_from_repo(cwd: str):
    from desloppify.base.loop_state import evaluate_loop_state

    return evaluate_loop_state(cwd, target_strict=TARGET_STRICT)


def _summary_details(summary) -> str:
    return ", ".join(
        [
            f"strict {summary.strict_score:.1f}/{summary.target_strict:.1f}",
            f"phase={summary.phase or 'none'}",
            f"open_review={summary.open_review_count}",
            f"stale_subjective={summary.stale_subjective_count}",
            f"unscored_subjective={summary.unscored_subjective_count}",
            f"under_target_subjective={summary.under_target_subjective_count}",
            f"execution={summary.execution_count}",
            f"backlog={summary.backlog_count}",
        ]
    )


def _stop_reason(summary) -> str:
    details = _summary_details(summary)
    action = summary.action
    scan_cmd = f"desloppify scan --path {summary.scan_path}"
    if action.kind == "review":
        return (
            "desloppify-loop95 is still active "
            f"({details}). This scan cycle still needs subjective review before more execution work. "
            f"Run `{summary.review_prepare_command}` and then `{summary.review_run_batches_command}`. "
            "Do not inspect backlog or edit code until this review step is complete. "
            "After review import, continue with `desloppify next`. "
            f"Stop only at strict >= {TARGET_STRICT:.1f}, or report `{BLOCKER_TOKEN}` with the exact command, "
            "exact error, and current strict score."
        )
    if action.kind == "show_review":
        return (
            "desloppify-loop95 is still active "
            f"({details}). Review findings are still open. "
            f"Run `{action.primary_command}` and work through that review queue before returning to `desloppify next`. "
            "Do not inspect backlog or continue implementation work until the open review queue is clear. "
            f"When the current work chunk is exhausted, rescan with `{scan_cmd}` and check `desloppify status` again. "
            f"Stop only at strict >= {TARGET_STRICT:.1f}, or report `{BLOCKER_TOKEN}` with the exact command, "
            "exact error, and current strict score."
        )
    if action.kind == "next":
        top_item = f" Top execution item: {summary.execution_summary}." if summary.execution_summary else ""
        primary = f" Primary action: `{summary.execution_primary_command}`." if summary.execution_primary_command else ""
        return (
            "desloppify-loop95 is still active "
            f"({details}). Continue with `desloppify next`.{top_item}{primary} "
            f"When the current work chunk is exhausted, rescan with `{scan_cmd}` and repeat. "
            f"Stop only at strict >= {TARGET_STRICT:.1f}, or report `{BLOCKER_TOKEN}` with the exact command, "
            "exact error, and current strict score."
        )
    if action.kind == "promote":
        backlog_hint = f" Top backlog item: {summary.backlog_summary}." if summary.backlog_summary else ""
        return (
            "desloppify-loop95 is still active "
            f"({details}). The execution queue is empty, but promotable backlog remains.{backlog_hint} "
            f"Run `{action.primary_command}` and then `{action.secondary_command}`. "
            f"When the current work chunk is exhausted, rescan with `{scan_cmd}` and repeat. "
            f"Stop only at strict >= {TARGET_STRICT:.1f}, or report `{BLOCKER_TOKEN}` with the exact command, "
            "exact error, and current strict score."
        )
    if action.kind == "blocked":
        return (
            "desloppify-loop95 is still active "
            f"({details}), but no actionable review, execution, or backlog work remains below target. "
            f"Stop only with `{BLOCKER_TOKEN}` followed by the exact command, exact error, and current strict score. "
            f"If you still believe more work exists, verify with `{scan_cmd}`, `desloppify plan queue`, "
            "and then `desloppify backlog --count 10`."
        )
    return (
        "desloppify-loop95 is still active "
        f"({details}). Continue from the current repo state, then re-check `desloppify status`. "
        f"Stop only at strict >= {TARGET_STRICT:.1f}, or report `{BLOCKER_TOKEN}` with the exact command, "
        "exact error, and current strict score."
    )


def _user_prompt_context(summary) -> str:
    scan_cmd = f"desloppify scan --path {summary.scan_path}"
    state = _summary_details(summary)
    action = summary.action
    if action.kind == "done":
        return (
            f"target state achieved ({state}). Continue normal cleanup, "
            "and do not resume loop actions unless strict drops below target."
        )
    if action.kind == "scan":
        return (
            "No loop state exists yet. Run "
            f"`{action.primary_command}` first and then `desloppify status` before making changes."
        )
    if action.kind == "review":
        return (
            f"State ({state}) is below target or review is not fresh. "
            f"Run `{summary.review_prepare_command}` and then `{summary.review_run_batches_command}` now. "
            f"After review import, run `{scan_cmd}`, then `desloppify status`."
        )
    if action.kind == "show_review":
        return (
            f"State ({state}) has open review findings. "
            f"Run `{action.primary_command}` and clear those findings before any new code changes. "
            f"Then run `{scan_cmd}` and `desloppify status` again."
        )
    if action.kind == "next":
        top_item = f" Top execution item: {summary.execution_summary}." if summary.execution_summary else ""
        primary = f" Primary action: `{summary.execution_primary_command}`." if summary.execution_primary_command else ""
        return (
            f"State ({state}) is in execution mode. Use `desloppify next`.{top_item}{primary} "
            "If execution queue is empty, run `desloppify plan queue` and then follow that exact output."
        )
    if action.kind == "promote":
        backlog_hint = f" Top backlog item: {summary.backlog_summary}." if summary.backlog_summary else ""
        return (
            f"State ({state}) has no execution queue but promotable backlog is available.{backlog_hint} "
            f"Run `{action.primary_command}` and then `{action.secondary_command}`."
        )
    if action.kind == "blocked":
        return (
            f"State ({state}) has no actionable review, execution, or promotable backlog below target. "
            "Re-check `desloppify status`, `desloppify plan queue`, and `desloppify backlog --count 10`. "
            f"If genuinely blocked, use `{BLOCKER_TOKEN}` with exact command, exact error, and current strict score."
        )
    return (
        f"State ({state}) still needs work. "
        "Run `desloppify status` and continue from the next recommended command path."
    )


def handle_user_prompt_submit(
    payload: dict,
    *,
    config_root: Path,
    state_summary_fn=_state_summary_from_repo,
) -> dict:
    prompt = str(payload.get("prompt", "") or "")
    if not _skill_activated(prompt):
        return {}
    try:
        summary = state_summary_fn(str(payload.get("cwd", "") or "."))
    except Exception as exc:
        summary = None
        summary_error = str(exc)
    else:
        summary_error = None
    session_id = str(payload.get("session_id", "") or "").strip()
    if session_id:
        _write_session_state(
            config_root,
            session_id,
            {
                "enabled": True,
                "cwd": str(payload.get("cwd", "") or ""),
            },
        )
    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": (
                "desloppify-loop95 is active for this session. "
                + _user_prompt_context(summary)
                if summary is not None
                else f"desloppify-loop95 is active for this session, but it could not read repo state: {summary_error}. "
                "Run `desloppify scan --path .` first, then retry this hook."
            ),
        }
    }


def handle_stop(
    payload: dict,
    *,
    config_root: Path,
    state_summary_fn=_state_summary_from_repo,
) -> dict:
    if str(payload.get("permission_mode", "") or "") == "plan":
        return {}
    session_id = str(payload.get("session_id", "") or "").strip()
    if not session_id:
        return {}
    session_state = _read_session_state(config_root, session_id)
    if not session_state.get("enabled"):
        return {}
    if _is_blocked_message(payload.get("last_assistant_message")):
        return {}
    try:
        summary = state_summary_fn(str(payload.get("cwd", "") or ""))
    except Exception as exc:
        return {
            "systemMessage": f"desloppify-loop95 hook could not inspect repo state: {exc}",
        }

    if summary.action.kind == "scan":
        return {
            "decision": "block",
            "reason": f"desloppify-loop95 is active but no scan state exists yet. Run `{summary.action.primary_command}`.",
        }
    if summary.action.kind == "done":
        return {
            "systemMessage": (
                "desloppify-loop95 target met: "
                f"strict {summary.strict_score:.1f}/{summary.target_strict:.1f}."
            ),
        }
    return {
        "decision": "block",
        "reason": _stop_reason(summary),
    }


def main() -> int:
    payload = json.load(sys.stdin)
    config_root = _config_root(Path(__file__))
    event_name = str(payload.get("hook_event_name", "") or "")
    if event_name == "UserPromptSubmit":
        response = handle_user_prompt_submit(payload, config_root=config_root)
    elif event_name == "Stop":
        response = handle_stop(payload, config_root=config_root)
    else:
        response = {}
    print(json.dumps(response))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
