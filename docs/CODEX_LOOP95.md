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

1. Your stop condition is `strict >= 95.0`, checked with `desloppify status`.
2. If scan or status says subjective review is stale, missing, or required, refresh it with `desloppify review --run-batches --runner codex --parallel --scan-after-import` before deciding you are done.
3. Keep using the same scan scope for the whole run. If you started with `desloppify scan --path .`, rescan with `desloppify scan --path .`; if you started on `src`, keep `src`.
4. Main loop: `desloppify next`, fix the current item, run its resolve command, rescan, run `desloppify status`, and repeat.
5. Do not stop just because the queue is lighter or one rescan looks better. Stop only when strict score is at least 95 and no immediate review refresh is required.
6. The Ralph loop hook only activates for sessions where the user explicitly invokes `$desloppify-loop95`. Once activated, the stop hook keeps the session alive until the target is met.
7. If you are blocked, stop only with `LOOP95_BLOCKED:` followed by the exact failing command, the exact error output, and the current strict score.
8. If Codex does not show the new loop behavior immediately after reinstall, restart Codex so it reloads the skill metadata and the hook/config files.

<!-- desloppify-overlay: codex_loop95 -->
<!-- desloppify-end -->
