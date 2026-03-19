"""Direct tests for the shared loop-state evaluator."""

from __future__ import annotations

from types import SimpleNamespace

import desloppify.base.loop_state as loop_state_mod


def _snapshot(*, execution_items=(), backlog_items=(), objective_backlog_count=0):
    return SimpleNamespace(
        execution_items=execution_items,
        backlog_items=backlog_items,
        objective_backlog_count=objective_backlog_count,
    )


def _patch_common(monkeypatch, *, strict: float, review_completed: bool, snapshot) -> None:
    monkeypatch.setattr(
        loop_state_mod,
        "score_snapshot",
        lambda _state: SimpleNamespace(strict=strict),
    )
    monkeypatch.setattr(loop_state_mod, "current_stale_ids", lambda _state: set())
    monkeypatch.setattr(loop_state_mod, "current_unscored_ids", lambda _state: set())
    monkeypatch.setattr(
        loop_state_mod,
        "current_under_target_ids",
        lambda _state, *, target_strict: {"subjective::naming"} if strict < target_strict else set(),
    )
    monkeypatch.setattr(loop_state_mod, "open_review_ids", lambda _state: set())
    monkeypatch.setattr(loop_state_mod, "subjective_review_completed_for_scan", lambda _plan, *, scan_count: review_completed)
    monkeypatch.setattr(loop_state_mod, "current_lifecycle_phase", lambda _plan: "execute")
    monkeypatch.setattr(loop_state_mod, "queue_context", lambda *_a, **_k: SimpleNamespace(plan={}))
    monkeypatch.setattr(loop_state_mod, "build_queue_snapshot", lambda *_a, **_k: snapshot)


def test_evaluate_loop_state_requires_review_before_execution(monkeypatch) -> None:
    _patch_common(
        monkeypatch,
        strict=84.0,
        review_completed=False,
        snapshot=_snapshot(
            execution_items=(
                {
                    "id": "workflow::create-plan",
                    "summary": "Create prioritized plan",
                    "primary_command": "desloppify plan triage --run-stages --runner codex",
                },
            ),
        ),
    )

    summary = loop_state_mod.evaluate_loop_state(
        state={"scan_count": 2, "scan_path": "."},
        plan={},
        target_strict=95.0,
    )

    assert summary.action.kind == "review"
    assert summary.action.primary_command == "desloppify review --prepare --path ."
    assert "--run-batches" in str(summary.action.secondary_command)
    assert "--path ." in str(summary.action.secondary_command)


def test_evaluate_loop_state_promotes_backlog_when_execution_empty(monkeypatch) -> None:
    _patch_common(
        monkeypatch,
        strict=90.0,
        review_completed=True,
        snapshot=_snapshot(
            backlog_items=(
                {
                    "id": "smells::src/a.py::dead-branch",
                    "summary": "Remove dead branch",
                },
            ),
            objective_backlog_count=1,
        ),
    )

    summary = loop_state_mod.evaluate_loop_state(
        state={"scan_count": 3, "scan_path": "."},
        plan={},
        target_strict=95.0,
    )

    assert summary.action.kind == "promote"
    assert summary.backlog_count == 1
    assert summary.action.primary_command == "desloppify plan promote smells::src/a.py::dead-branch top"
    assert summary.action.secondary_command == "desloppify next"


def test_evaluate_loop_state_blocks_when_no_actions_left_below_target(monkeypatch) -> None:
    _patch_common(
        monkeypatch,
        strict=91.0,
        review_completed=True,
        snapshot=_snapshot(),
    )

    summary = loop_state_mod.evaluate_loop_state(
        state={"scan_count": 4, "scan_path": "."},
        plan={},
        target_strict=95.0,
    )

    assert summary.action.kind == "blocked"
    assert "below target" in summary.action.reason

