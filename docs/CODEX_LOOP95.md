---
name: desloppify-loop95
description: >
  Use when you want Codex to keep running the desloppify workflow until the
  strict score is at least 95. This variant is review-first, plan-queue-driven,
  and only stops at target or an explicit blocker.
---

<!-- desloppify-begin -->
<!-- desloppify-skill-version: 13 -->

# Desloppify Loop95

Your only job is to keep the current repo moving until `desloppify status` shows
`strict >= 95.0` and review is fresh.

Install this skill with `desloppify update-skill codex_loop95`. The native
Codex target is `~/.codex/skills/desloppify-loop95/SKILL.md`. The install also
writes `~/.codex/skills/desloppify-loop95/agents/openai.yaml`,
`~/.codex/hooks.json`, `~/.codex/hooks/desloppify_loop95_hook.py`, and
`~/.codex/config.toml` with `[features].codex_hooks = true`.

## Required Loop

1. Start with `desloppify scan --path <scope>` and keep that same scope for the whole session.
2. Run `desloppify status`.
3. If the current scan needs subjective review, run:
   `desloppify review --prepare --path <scope>`
   then
   `desloppify review --run-batches --runner codex --parallel --scan-after-import --path <scope>`
4. If review findings are open, run `desloppify show review --status open` and work that queue first.
5. Only after review is current and open review work is clear, run `desloppify next`.
6. Fix the current item and run the exact resolve command the tool gives you.
7. When `desloppify next` empties, run `desloppify plan queue`.
8. If `desloppify plan queue` recommends `desloppify plan promote ...`, run that exact command and then return to `desloppify next`.
9. Rescan only when the current work chunk is exhausted.
10. Stop only when `strict >= 95.0` and review is fresh, or with `LOOP95_BLOCKED:` if genuinely blocked.

## Hard Rules

- Do not inspect `desloppify backlog` while subjective review is pending for the current scan.
- Do not inspect `desloppify backlog` while `desloppify show review --status open` still has work.
- Do not edit code or pick backlog work before clearing required review or open review work.
- Do not invent your own next step when `desloppify next`, `desloppify plan queue`, or `desloppify status` already tell you what to do.
- Do not stop below target without `LOOP95_BLOCKED:` followed by the exact command, exact error, and current strict score.

## Empty Queue Handling

- If `desloppify next` says review is pending, go run review immediately.
- If `desloppify next` or `desloppify plan queue` says review findings are open, run `desloppify show review --status open`.
- If `desloppify plan queue` points to `desloppify plan promote ...`, use that command instead of browsing backlog manually.
- If both `next` and `plan queue` are empty below target after a fresh scan and fresh review, stop only with `LOOP95_BLOCKED:`.

If Codex does not pick up the new loop behavior immediately after reinstall,
restart Codex so it reloads the updated skill metadata and hook configuration.

<!-- desloppify-overlay: codex_loop95 -->
<!-- desloppify-end -->
