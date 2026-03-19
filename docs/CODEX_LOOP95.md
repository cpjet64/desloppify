---
name: desloppify-loop95
description: >
  Codebase health scanner and technical debt tracker. Use when you want Codex
  to keep looping through the desloppify workflow until the strict score is at
  least 95, while still following scan, review, plan, and next guidance.
---

## Codex Loop95 Overlay

This optional Codex overlay is for one job: keep running the desloppify workflow until the strict score is at least 95.

Install it with `desloppify update-skill codex_loop95`. The native Codex target is `~/.codex/skills/desloppify-loop95/SKILL.md`, and the install also writes `~/.codex/skills/desloppify-loop95/agents/openai.yaml`, `~/.codex/hooks.json`, `~/.codex/hooks/desloppify_loop95_hook.py`, and `~/.codex/config.toml` with `[features].codex_hooks = true`. Use `--scope project` only if you intentionally need the legacy repo-local compatibility install plus project-local `.codex/` hooks.

1. Your stop condition is `strict >= 95.0`, checked with `desloppify status`, and review must also be fresh.
2. Start with `desloppify scan --path <scope>` and keep using that same scan scope for the whole run.
3. After each scan, check `desloppify status`. If strict is already at target and review is fresh, you may stop.
4. If the repo is still below target for the current scan cycle, run subjective review first: `desloppify review --prepare --path <scope>` and then `desloppify review --run-batches --runner codex --parallel --scan-after-import --path <scope>`.
5. Once review for the current scan is complete, drive work from the living plan with `desloppify next`. Fix the current item and run its resolve command, but do not rescan after every single item.
6. When `desloppify next` empties before the score target is met, run `desloppify plan queue` first. Follow its exact empty-state guidance, and if promotable backlog remains use the suggested `desloppify plan promote ...` command before continuing.
7. When the current work chunk is exhausted, rescan, check `desloppify status`, and repeat the cycle.
8. The Ralph loop hook only activates for sessions where the user explicitly invokes `$desloppify-loop95`. Once activated, the stop hook keeps the session alive until the target is met or there is no actionable work left.
9. If you are blocked below target, stop only with `LOOP95_BLOCKED:` followed by the exact failing command, the exact error output, and the current strict score.
10. If Codex does not show the new loop behavior immediately after reinstall, restart Codex so it reloads the skill metadata and the hook/config files.

<!-- desloppify-overlay: codex_loop95 -->
<!-- desloppify-end -->
