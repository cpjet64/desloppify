from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

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


def _state_summary_from_repo(cwd: str) -> dict[str, object]:
    original_cwd = Path.cwd()
    os.chdir(cwd)
    try:
        from desloppify.app.commands.helpers.state import state_path
        from desloppify.base.review_commands import build_review_prepare_command
        from desloppify.engine._plan.policy.stale import (
            current_stale_ids,
            current_under_target_ids,
            current_unscored_ids,
            open_review_ids,
        )
        from desloppify.state_io import load_state
        from desloppify.state_scoring import score_snapshot

        args = SimpleNamespace(state=None, lang=None, command="status")
        resolved_state_path = state_path(args)
        state = load_state(resolved_state_path)
        scores = score_snapshot(state)
        scan_count = int(state.get("scan_count", 0) or 0)
        scan_path = str(state.get("scan_path", "") or "").strip() or "."
        return {
            "strict_score": float(scores.strict),
            "scan_count": scan_count,
            "scan_path": scan_path,
            "review_prepare_command": build_review_prepare_command(scan_path=scan_path),
            "stale_subjective_count": len(current_stale_ids(state)),
            "unscored_subjective_count": len(current_unscored_ids(state)),
            "under_target_subjective_count": len(
                current_under_target_ids(state, target_strict=TARGET_STRICT)
            ),
            "open_review_count": len(open_review_ids(state)),
        }
    finally:
        os.chdir(original_cwd)


def _stop_reason(summary: dict[str, object]) -> str:
    strict_score = float(summary.get("strict_score", 0.0) or 0.0)
    scan_path = str(summary.get("scan_path", ".") or ".").strip() or "."
    prepare_command = str(summary.get("review_prepare_command", "desloppify review --prepare"))
    stale = int(summary.get("stale_subjective_count", 0) or 0)
    unscored = int(summary.get("unscored_subjective_count", 0) or 0)
    under_target = int(summary.get("under_target_subjective_count", 0) or 0)
    open_review = int(summary.get("open_review_count", 0) or 0)

    details = [
        f"strict {strict_score:.1f}/{TARGET_STRICT:.1f}",
        f"open_review={open_review}",
        f"stale_subjective={stale}",
        f"unscored_subjective={unscored}",
        f"under_target_subjective={under_target}",
    ]
    if stale > 0 or unscored > 0 or open_review > 0:
        return (
            "desloppify-loop95 is still active "
            f"({', '.join(details)}). Continue the loop from the current repo state. "
            f"If review context is stale or missing, run `{prepare_command}` and then "
            "`desloppify review --run-batches --runner codex --parallel --scan-after-import`. "
            f"Otherwise use `desloppify next`, implement the current work, resolve it, rescan with "
            f"`desloppify scan --path {scan_path}`, and re-check `desloppify status`. "
            f"Stop only at strict >= {TARGET_STRICT:.1f}, or report `{BLOCKER_TOKEN}` with the exact command, "
            "exact error, and current strict score."
        )
    return (
        "desloppify-loop95 is still active "
        f"({', '.join(details)}). Continue with `desloppify next`, implement the current work, "
        f"resolve it, rescan with `desloppify scan --path {scan_path}`, and re-check `desloppify status`. "
        f"Stop only at strict >= {TARGET_STRICT:.1f}, or report `{BLOCKER_TOKEN}` with the exact command, "
        "exact error, and current strict score."
    )


def handle_user_prompt_submit(payload: dict, *, config_root: Path) -> dict:
    prompt = str(payload.get("prompt", "") or "")
    if not _skill_activated(prompt):
        return {}
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
                "desloppify-loop95 is active for this session. Do not stop until `desloppify status` "
                f"shows `strict >= {TARGET_STRICT:.1f}` and review is fresh. If you are genuinely blocked, "
                f"stop only with `{BLOCKER_TOKEN}` followed by the exact command, exact error, and current strict score."
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

    strict_score = float(summary.get("strict_score", 0.0) or 0.0)
    scan_count = int(summary.get("scan_count", 0) or 0)
    stale = int(summary.get("stale_subjective_count", 0) or 0)
    unscored = int(summary.get("unscored_subjective_count", 0) or 0)
    open_review = int(summary.get("open_review_count", 0) or 0)

    if scan_count <= 0:
        return {
            "decision": "block",
            "reason": (
                "desloppify-loop95 is active but no scan state exists yet. Run `desloppify scan --path .` "
                f"and continue until `desloppify status` shows `strict >= {TARGET_STRICT:.1f}`."
            ),
        }
    if strict_score >= TARGET_STRICT and stale == 0 and unscored == 0 and open_review == 0:
        return {
            "systemMessage": f"desloppify-loop95 target met: strict {strict_score:.1f}/{TARGET_STRICT:.1f}.",
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
