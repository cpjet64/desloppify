"""Shared builders for user-facing review command strings."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path


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


__all__ = ["build_review_prepare_command"]
