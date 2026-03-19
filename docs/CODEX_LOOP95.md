---
name: desloppify-loop95
description: >
  Codebase health scanner and technical debt tracker. Use when you want Codex
  to keep looping through the desloppify workflow until the strict score is at
  least 95, while still following scan, review, plan, and next guidance.
---

## Codex Loop95 Overlay

This optional Codex overlay is for one job: keep running the desloppify workflow until the strict score is at least 95.

Install it with `desloppify update-skill codex_loop95`. The native Codex target is `~/.codex/skills/desloppify-loop95/SKILL.md`. Use `--scope project` only if you intentionally need the legacy repo-local compatibility install.

1. Your stop condition is `strict >= 95.0`, checked with `desloppify status`.
2. If scan or status says subjective review is stale, missing, or required, refresh it with `desloppify review --run-batches --runner codex --parallel --scan-after-import` before deciding you are done.
3. Keep using the same scan scope for the whole run. If you started with `desloppify scan --path .`, rescan with `desloppify scan --path .`; if you started on `src`, keep `src`.
4. Main loop: `desloppify next`, fix the current item, run its resolve command, rescan, run `desloppify status`, and repeat.
5. Do not stop just because the queue is lighter or one rescan looks better. Stop only when strict score is at least 95 and no immediate review refresh is required.
6. Do not rely on experimental Codex hooks as the loop controller yet. Use the explicit command loop above.
7. If you are blocked, report the exact failing command, the exact error output, and the current strict score before stopping.

<!-- desloppify-overlay: codex_loop95 -->
<!-- desloppify-end -->
