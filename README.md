# cross-agent-reviews

A multi-host plugin (Claude Code + Codex) that packages a 3-round / 6-step cross-agent spec/plan review pipeline as discoverable skills. Reviewer rounds *audit* the artifact and author rounds *settle* findings across fresh sessions, with a strict final round, preserving cross-agent diversity by construction. v0.1.0 ships local-only; install via the host's `/plugin` slash-commands (see [Install](#install) below).

## How it works

| Round | Skill | Role | Input | Output |
|---|---|---|---|---|
| 1a | `cr-1a-audit` | Reviewer (5-agent parallel review) | spec/plan path | Round 1 JSON |
| 1b | `cr-1b-settle` | Author (settle + edit) | Round 1 JSON | Round 1 adjudication JSON |
| 2a | `cr-2a-audit` | Reviewer (verify corrections) | Round 1 adjudication JSON | Round 2 JSON |
| 2b | `cr-2b-settle` | Author (settle + edit) | Round 2 JSON | Round 2 adjudication JSON |
| 3a | `cr-3a-final-audit` | Reviewer (strict final check) | Round 2 adjudication JSON | Round 3 JSON |
| 3b | `cr-3b-final-settle` | Author (final adjudication) | Round 3 JSON | `final_status` |

**Fresh session per round.** Each skill's Step 0 detects prior pipeline activity in the current conversation and asks the operator to start fresh. This preserves cross-agent diversity — reviewer and author should not share session context.

**Terminal status.** Round 3b emits one of two statuses:
- `READY_FOR_IMPLEMENTATION` — Round 3a found no blockers; artifact ships unchanged.
- `CORRECTED_AND_READY` — Round 3a found blockers; minimum corrections applied; artifact ships.

## Install

### Claude Code

In any Claude Code session:

```
/plugin marketplace add /path/to/cross-agent-reviews
/plugin install cross-agent-reviews@cross-agent-reviews
```

Skills appear as `/cr-1a-audit`, `/cr-1b-settle`, `/cr-2a-audit`, `/cr-2b-settle`, `/cr-3a-final-audit`, `/cr-3b-final-settle` in autocomplete. Restart the session if they don't surface immediately.

To uninstall: `/plugin uninstall cross-agent-reviews@cross-agent-reviews`. The marketplace registration stays; remove separately with `/plugin marketplace remove cross-agent-reviews` if desired.

### Codex

In Codex (CLI v0.128+):

```
codex plugin marketplace add /path/to/cross-agent-reviews
```

Then in the Codex TUI, open `/plugin`, navigate to the `cross-agent-reviews` marketplace, and install the `cross-agent-reviews` plugin. Skills appear as `$cr-1a-audit`, `$cr-1b-settle`, `$cr-2a-audit`, `$cr-2b-settle`, `$cr-3a-final-audit`, `$cr-3b-final-settle` in autocomplete. Restart the TUI once after install to refresh the skill index.

To uninstall, use `/plugin` in the TUI to uninstall the plugin, or run `codex plugin marketplace remove cross-agent-reviews` to drop the marketplace registration.

### From GitHub (forward-looking; v0.2+)

Once the repo is published at `https://github.com/j7an/cross-agent-reviews`, the same slash-command flow is expected to accept a GitHub URL as the marketplace source:

```
/plugin marketplace add https://github.com/j7an/cross-agent-reviews
/plugin install cross-agent-reviews@cross-agent-reviews
```

v0.1 is local-only — the URL is reserved but not yet published.

## Operating the pipeline

**Fresh session rule.** Open a new session for every round. The skill's Step 0 will detect and refuse stale sessions; if you're stuck on a single host, reply with `override fresh-session check` to proceed in degraded mode.

**Recommended host distribution:**

| Phase | Recommended host |
|---|---|
| Authoring spec/plan | Operator's primary host |
| Reviewer rounds (1a, 2a, 3a) | A *different* host than authoring |
| Author rounds (1b, 2b, 3b) | Same host as authoring |

**Single-host fallback.** If you only have one host, use a fresh session every round and override the freshness check when prompted. Cross-agent property is reduced; sub-agent model-tier diversity in the reviewer rounds provides some independence.

**Common mistakes:**

- *Forgetting the artifact path in 1a* — the skill will ask; supply absolute or relative path.
- *Pasting the wrong round's JSON* — the skill detects field-signature mismatch and asks you to repaste.
- *Running 1b on a stale 1a output after editing the artifact mid-pipeline* — the artifact and the round JSON have drifted; rerun 1a from a fresh session.

**Artifact updates between rounds.** Don't edit the artifact between an author round (1b/2b) emitting JSON and the next reviewer round (2a/3a) consuming it. The reviewer round verifies the same artifact the previous author edited — manual edits in between break the contract.

## Architecture

This plugin's pipeline architecture is an adaptation of two skills from the [Superpowers](https://github.com/obra/superpowers) plugin family (reference version 5.0.7):

- `superpowers:dispatching-parallel-agents` — parallel-dispatch decision pattern for slice planning.
- `superpowers:subagent-driven-development` — model-tier rubric, status protocol, and dispatch-template structure.

**Architectural choices:**

- **Path A (inline)** rather than cross-plugin Skill invocation — MVP velocity, cross-host portability, no plugin dependency.
- **Paste-into-prompt** runtime rather than file-based — cross-host portable, compaction-resilient.
- **`_shared/` directory** for DRY content across the 6 SKILL.md files — each SKILL.md is ~60-70 lines of table-of-contents + round-specific content; shared sections (preflight, model tier, dispatch template, etc.) live in `plugin/skills/_shared/*.md` and are read on demand.

Full attribution at [`plugin/skills/_shared/attribution.md`](plugin/skills/_shared/attribution.md).

## Contributing

Run the verifier before opening any PR that touches SKILL.md, `_shared/*.md`, or manifest files:

```bash
bash scripts/verify-prompt-contract.sh
```

Requirements: `bash`, `rg` (ripgrep), `jq`, `diff`. The verifier runs 39 prompt-content checks across 8 categories (A-H per spec §10.2).

## Acknowledgments

This plugin's pipeline shape was iterated locally in a sibling repo (`superpowers-cross-agent-reviews`) over three commits before being extracted as a publishable plugin. The design directly adopts patterns from the [Superpowers](https://github.com/obra/superpowers) skill collection by Jesse Vincent and contributors. See [`plugin/skills/_shared/attribution.md`](plugin/skills/_shared/attribution.md) for the full attribution.

## License

MIT. See [`LICENSE`](LICENSE).
