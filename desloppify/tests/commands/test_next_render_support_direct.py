"""Direct tests for next empty-state guidance helpers."""

from __future__ import annotations

from types import SimpleNamespace

import desloppify.app.commands.next.render_support as support_mod


def _summary(*, strict=90.0, target=95.0, execution_count=0, kind="promote", primary=None):
    return SimpleNamespace(
        strict_score=strict,
        target_strict=target,
        execution_count=execution_count,
        backlog_count=1 if kind == "promote" else 0,
        backlog_summary="Remove dead branch",
        backlog_promote_command=primary or "desloppify plan promote smells::x top",
        review_prepare_command="desloppify review --prepare --path .",
        action=SimpleNamespace(kind=kind),
    )


def test_build_empty_queue_guidance_prefers_cluster_focus_message(monkeypatch) -> None:
    monkeypatch.setattr(
        support_mod,
        "evaluate_loop_state",
        lambda **_kwargs: _summary(execution_count=2, kind="next"),
    )

    guidance = support_mod.build_empty_queue_guidance(
        state={},
        plan={"active_cluster": "auth"},
        target_strict=95.0,
        active_cluster="auth",
    )

    assert guidance is not None
    assert "cluster focus" in guidance.headline.lower()
    assert "plan focus --clear" in guidance.lines[0]


def test_build_empty_queue_guidance_suggests_promotion(monkeypatch) -> None:
    monkeypatch.setattr(
        support_mod,
        "evaluate_loop_state",
        lambda **_kwargs: _summary(
            kind="promote",
            primary="desloppify plan promote smells::src/a.py::dead-branch top",
        ),
    )

    guidance = support_mod.build_empty_queue_guidance(
        state={},
        plan={},
        target_strict=95.0,
    )

    assert guidance is not None
    assert "promotable backlog remains" in guidance.headline.lower()
    assert "plan promote" in guidance.lines[1]

