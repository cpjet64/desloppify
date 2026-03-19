"""Direct tests for plan queue empty-state guidance."""

from __future__ import annotations

import argparse

import desloppify.app.commands.plan.queue_render as queue_render_mod
from desloppify.app.commands.helpers.command_runtime import CommandRuntime
from desloppify.app.commands.next.render_support import EmptyQueueGuidance


def _args(**overrides) -> argparse.Namespace:
    values = {
        "top": 30,
        "cluster": None,
        "include_skipped": False,
        "sort": "priority",
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_cmd_plan_queue_empty_prints_actionable_guidance(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        queue_render_mod,
        "command_runtime",
        lambda _args: CommandRuntime(config={}, state={"issues": {}}, state_path=None),
    )
    monkeypatch.setattr(queue_render_mod, "require_issue_inventory", lambda _state: True)
    monkeypatch.setattr(queue_render_mod, "load_plan", lambda: {})
    monkeypatch.setattr(queue_render_mod, "print_triage_guardrail_info", lambda **_kw: None)
    monkeypatch.setattr(
        queue_render_mod,
        "_build_queue_items",
        lambda **_kwargs: ([], {"items": [], "new_ids": set()}),
    )
    monkeypatch.setattr(
        queue_render_mod,
        "build_empty_queue_guidance",
        lambda **_kwargs: EmptyQueueGuidance(
            headline="Execution queue is empty, but promotable backlog remains.",
            lines=(
                "Top backlog item: Remove dead branch.",
                "Promote the next item with `desloppify plan promote smells::x top`.",
            ),
        ),
    )

    queue_render_mod.cmd_plan_queue(_args())

    out = capsys.readouterr().out
    assert "Queue is empty." in out
    assert "promotable backlog remains" in out
    assert "plan promote smells::x top" in out


def test_cmd_plan_queue_non_empty_does_not_render_empty_guidance(monkeypatch, capsys) -> None:
    calls: list[dict] = []

    monkeypatch.setattr(
        queue_render_mod,
        "command_runtime",
        lambda _args: CommandRuntime(config={}, state={"issues": {}}, state_path=None),
    )
    monkeypatch.setattr(queue_render_mod, "require_issue_inventory", lambda _state: True)
    monkeypatch.setattr(queue_render_mod, "load_plan", lambda: {})
    monkeypatch.setattr(queue_render_mod, "print_triage_guardrail_info", lambda **_kw: None)
    monkeypatch.setattr(
        queue_render_mod,
        "_build_queue_items",
        lambda **_kwargs: (
            [
                {
                    "id": "issue-1",
                    "kind": "issue",
                    "confidence": "medium",
                    "detector": "review",
                    "summary": "Fix test gap",
                }
            ],
            {"items": [{"id": "issue-1"}], "new_ids": set()},
        ),
    )
    monkeypatch.setattr(
        queue_render_mod,
        "build_empty_queue_guidance",
        lambda **kwargs: calls.append(kwargs) or None,
    )

    queue_render_mod.cmd_plan_queue(_args())

    out = capsys.readouterr().out
    assert "Fix test gap" in out
    assert "Queue is empty." not in out
    assert calls == []


def test_cmd_plan_queue_explicit_cluster_filter_does_not_fake_focus_clear(monkeypatch, capsys) -> None:
    seen: dict[str, object] = {}

    monkeypatch.setattr(
        queue_render_mod,
        "command_runtime",
        lambda _args: CommandRuntime(config={}, state={"issues": {}}, state_path=None),
    )
    monkeypatch.setattr(queue_render_mod, "require_issue_inventory", lambda _state: True)
    monkeypatch.setattr(queue_render_mod, "load_plan", lambda: {"active_cluster": "auth"})
    monkeypatch.setattr(queue_render_mod, "print_triage_guardrail_info", lambda **_kw: None)
    monkeypatch.setattr(
        queue_render_mod,
        "_build_queue_items",
        lambda **_kwargs: ([], {"items": [], "new_ids": set()}),
    )

    def _capture_guidance(**kwargs):
        seen.update(kwargs)
        return None

    monkeypatch.setattr(queue_render_mod, "build_empty_queue_guidance", _capture_guidance)

    queue_render_mod.cmd_plan_queue(_args(cluster="manual"))

    capsys.readouterr()
    assert seen["active_cluster"] is None
