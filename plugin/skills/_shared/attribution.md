<!--
Architecture adapted from:
  - superpowers:dispatching-parallel-agents (parallel dispatch decision pattern)
  - superpowers:subagent-driven-development (model-tier rubric, status protocol)
Source: https://github.com/obra/superpowers (referenced version: 5.0.7)
v0.2+ may transition to direct skill invocation if cross-plugin Skill API
stabilizes across hosts.
-->

# Attribution

This plugin's pipeline architecture is an adaptation of two skills from the
[Superpowers](https://github.com/obra/superpowers) plugin family:

- **superpowers:dispatching-parallel-agents** — the parallel-dispatch decision pattern (when to parallelize, focused-scope rules, common mistakes) informs the slice-plan design used by reviewer rounds 1a/2a/3a.
- **superpowers:subagent-driven-development** — the model-tier rubric (most capable / standard / fast), status protocol (`DONE` / `DONE_WITH_CONCERNS` / `BLOCKED` / `NEEDS_CONTEXT`), and implementer-prompt template shape are adopted verbatim with role-name adaptation.

Reference version: **5.0.7** (as installed in `~/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.7/`).

The reviewer-round status labels (`findings_found` / `clean` / `blocked` / `needs_context`) are review-specific adaptations; author rounds (1b/2b/3b) retain the original Superpowers uppercase labels.

v0.2+ may transition to direct cross-plugin skill invocation if a stable cross-host Skill invocation API emerges across Claude Code, Codex, and other hosts.
