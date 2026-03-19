"""Shared builders for user-facing review command strings."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

_DEFAULT_RETROSPECTIVE_MAX_ISSUES = 30
_DEFAULT_RETROSPECTIVE_MAX_BATCH_ITEMS = 20


def _normalized_dimensions(dimensions: Iterable[str] | None) -> list[str]:
    """Return CLI-safe dimension keys, preserving order and removing duplicates."""
    seen: set[str] = set()
    normalized: list[str] = []
    if dimensions is None:
        return normalized
    for raw_dimension in dimensions:
        dimension = str(raw_dimension).strip()
        if not dimension or dimension in seen:
            continue
        seen.add(dimension)
        normalized.append(dimension)
    return normalized


def build_review_prepare_command(
    *,
    scan_path: str | Path | None = None,
    dimensions: Iterable[str] | None = None,
    force_review_rerun: bool = False,
) -> str:
    """Build the canonical `review --prepare` command for the current scan scope."""
    parts = ["desloppify", "review", "--prepare"]
    if scan_path is not None:
        path_text = str(scan_path).strip()
        if path_text:
            parts.extend(["--path", path_text])
    if force_review_rerun:
        parts.append("--force-review-rerun")
    normalized_dimensions = _normalized_dimensions(dimensions)
    if normalized_dimensions:
        parts.extend(["--dimensions", ",".join(normalized_dimensions)])
    return " ".join(parts)


def build_review_run_batches_command(
    *,
    scan_path: str | Path | None = None,
    state_path: str | Path | None = None,
    dimensions: Iterable[str] | None = None,
    retrospective: bool = True,
    retrospective_max_issues: int = _DEFAULT_RETROSPECTIVE_MAX_ISSUES,
    retrospective_max_batch_items: int = _DEFAULT_RETROSPECTIVE_MAX_BATCH_ITEMS,
) -> str:
    """Build the canonical `review --run-batches` command for the current scope."""
    parts = [
        "desloppify",
        "review",
        "--run-batches",
        "--runner",
        "codex",
        "--parallel",
        "--scan-after-import",
    ]
    if scan_path is not None:
        path_text = str(scan_path).strip()
        if path_text:
            parts.extend(["--path", path_text])
    if state_path is not None:
        state_text = str(state_path).strip()
        if state_text:
            parts.extend(["--state", state_text])
    normalized_dimensions = _normalized_dimensions(dimensions)
    if normalized_dimensions:
        parts.extend(["--dimensions", ",".join(normalized_dimensions)])
    if not retrospective:
        parts.append("--no-retrospective")
    else:
        if retrospective_max_issues != _DEFAULT_RETROSPECTIVE_MAX_ISSUES:
            parts.extend(["--retrospective-max-issues", str(retrospective_max_issues)])
        if retrospective_max_batch_items != _DEFAULT_RETROSPECTIVE_MAX_BATCH_ITEMS:
            parts.extend(
                ["--retrospective-max-batch-items", str(retrospective_max_batch_items)]
            )
    return " ".join(parts)


__all__ = [
    "build_review_prepare_command",
    "build_review_run_batches_command",
]
