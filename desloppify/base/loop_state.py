"""Shared loop-state evaluation for Codex loop95 and queue guidance."""

from __future__ import annotations

import os
import shlex
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

from desloppify.app.commands.helpers.state import state_path
from desloppify.base.review_commands import (
    build_review_prepare_command,
    build_review_run_batches_command,
)
from desloppify.engine._plan.policy.stale import (
    current_stale_ids,
    current_under_target_ids,
    current_unscored_ids,
    open_review_ids,
)
from desloppify.engine._plan.refresh_lifecycle import (
    current_lifecycle_phase,
    subjective_review_completed_for_scan,
)
from desloppify.engine._work_queue.context import queue_context
from desloppify.engine._work_queue.models import QueueBuildOptions
from desloppify.engine._work_queue.snapshot import build_queue_snapshot
from desloppify.engine.plan_state import load_plan
from desloppify.state_io import load_state
from desloppify.state_scoring import score_snapshot

LoopActionKind = Literal["scan", "review", "show_review", "next", "promote", "blocked", "done"]


@dataclass(frozen=True, slots=True)
class LoopAction:
    """Recommended next step for a score-driven loop."""

    kind: LoopActionKind
    reason: str
    primary_command: str | None = None
    secondary_command: str | None = None


@dataclass(frozen=True, slots=True)
class LoopStateSummary:
    """Canonical loop-state facts derived from persisted repo state."""

    strict_score: float
    target_strict: float
    scan_count: int
    scan_path: str
    phase: str | None
    review_completed_for_scan: bool
    stale_subjective_count: int
    unscored_subjective_count: int
    under_target_subjective_count: int
    open_review_count: int
    execution_count: int
    execution_primary_command: str | None
    execution_summary: str | None
    backlog_count: int
    objective_backlog_count: int
    backlog_promote_command: str | None
    backlog_summary: str | None
    review_prepare_command: str
    review_run_batches_command: str
    action: LoopAction


@contextmanager
def _pushd(cwd: str | Path):
    original_cwd = Path.cwd()
    os.chdir(cwd)
    try:
        yield
    finally:
        os.chdir(original_cwd)


def _normalized_scan_path(state: Mapping[str, Any]) -> str:
    return str(state.get("scan_path", "") or "").strip() or "."


def _first_item(items: tuple[dict[str, Any], ...]) -> dict[str, Any] | None:
    return items[0] if items else None


def _item_summary(item: Mapping[str, Any] | None) -> str | None:
    if item is None:
        return None
    summary = str(item.get("summary", "") or "").strip()
    return summary or None


def _item_primary_command(item: Mapping[str, Any] | None) -> str | None:
    if item is None:
        return None
    command = str(item.get("primary_command", "") or "").strip()
    return command or None


def _promote_pattern(item: Mapping[str, Any] | None) -> str | None:
    if item is None:
        return None
    cluster_name = str(item.get("cluster_name", "") or "").strip()
    if cluster_name:
        return cluster_name
    item_id = str(item.get("id", "") or "").strip()
    if item_id:
        return item_id
    return None


def build_plan_promote_command(item: Mapping[str, Any] | str | None) -> str | None:
    """Build a concrete `plan promote` command for the top backlog candidate."""
    pattern = item if isinstance(item, str) else _promote_pattern(item)
    if pattern is None:
        return None
    return f"desloppify plan promote {shlex.quote(pattern)} top"


def _load_state_and_plan_from_repo(cwd: str | Path) -> tuple[dict[str, Any], dict[str, Any]]:
    with _pushd(cwd):
        args = SimpleNamespace(state=None, lang=None, command="status")
        resolved_state_path = state_path(args)
        state = load_state(resolved_state_path)
        plan = load_plan()
    return state, plan if isinstance(plan, dict) else {}


def evaluate_loop_state(
    cwd: str | Path | None = None,
    *,
    state: dict[str, Any] | None = None,
    plan: dict[str, Any] | None = None,
    target_strict: float = 95.0,
) -> LoopStateSummary:
    """Evaluate persisted state and return the next score-loop action."""
    if state is None:
        if cwd is None:
            raise ValueError("cwd is required when state is not provided")
        state, plan = _load_state_and_plan_from_repo(cwd)
    effective_plan = plan if isinstance(plan, dict) else {}
    scan_path = _normalized_scan_path(state)
    scores = score_snapshot(state)
    strict_score = float(scores.strict if scores.strict is not None else 0.0)
    scan_count = int(state.get("scan_count", 0) or 0)
    review_prepare_command = build_review_prepare_command(scan_path=scan_path)
    review_run_batches_command = build_review_run_batches_command(scan_path=scan_path)
    review_completed = subjective_review_completed_for_scan(
        effective_plan,
        scan_count=scan_count,
    )

    ctx = queue_context(
        state,
        config=state.get("config"),
        plan=effective_plan,
        target_strict=target_strict,
    )
    snapshot = build_queue_snapshot(
        state,
        options=QueueBuildOptions(
            count=None,
            status="open",
            include_subjective=True,
            subjective_threshold=target_strict,
            context=ctx,
        ),
        target_strict=target_strict,
    )

    execution_item = _first_item(snapshot.execution_items)
    backlog_item = _first_item(snapshot.backlog_items)
    execution_count = len(snapshot.execution_items)
    backlog_count = len(snapshot.backlog_items)
    stale_count = len(current_stale_ids(state))
    unscored_count = len(current_unscored_ids(state))
    under_target_count = len(current_under_target_ids(state, target_strict=target_strict))
    open_review_count = len(open_review_ids(state))
    backlog_promote_command = build_plan_promote_command(backlog_item)

    if scan_count <= 0:
        action = LoopAction(
            kind="scan",
            reason="no scan state exists yet",
            primary_command=f"desloppify scan --path {scan_path}",
        )
    elif (
        strict_score >= target_strict
        and stale_count == 0
        and unscored_count == 0
        and open_review_count == 0
    ):
        action = LoopAction(
            kind="done",
            reason="strict target met and review state is fresh",
        )
    elif strict_score < target_strict and not review_completed:
        action = LoopAction(
            kind="review",
            reason="the current scan cycle has not had subjective review yet",
            primary_command=review_prepare_command,
            secondary_command=review_run_batches_command,
        )
    elif open_review_count > 0:
        action = LoopAction(
            kind="show_review",
            reason="review findings are still open",
            primary_command="desloppify show review --status open",
        )
    elif execution_count > 0:
        action = LoopAction(
            kind="next",
            reason="execution work is available in the living plan",
            primary_command="desloppify next",
            secondary_command=_item_primary_command(execution_item),
        )
    elif backlog_count > 0 and backlog_promote_command is not None:
        action = LoopAction(
            kind="promote",
            reason="execution queue is empty but promotable backlog remains",
            primary_command=backlog_promote_command,
            secondary_command="desloppify next",
        )
    else:
        action = LoopAction(
            kind="blocked",
            reason="no actionable review, execution, or backlog work remains below target",
        )

    return LoopStateSummary(
        strict_score=strict_score,
        target_strict=float(target_strict),
        scan_count=scan_count,
        scan_path=scan_path,
        phase=current_lifecycle_phase(effective_plan),
        review_completed_for_scan=review_completed,
        stale_subjective_count=stale_count,
        unscored_subjective_count=unscored_count,
        under_target_subjective_count=under_target_count,
        open_review_count=open_review_count,
        execution_count=execution_count,
        execution_primary_command=_item_primary_command(execution_item),
        execution_summary=_item_summary(execution_item),
        backlog_count=backlog_count,
        objective_backlog_count=snapshot.objective_backlog_count,
        backlog_promote_command=backlog_promote_command,
        backlog_summary=_item_summary(backlog_item),
        review_prepare_command=review_prepare_command,
        review_run_batches_command=review_run_batches_command,
        action=action,
    )


__all__ = [
    "LoopAction",
    "LoopActionKind",
    "LoopStateSummary",
    "build_plan_promote_command",
    "evaluate_loop_state",
]
