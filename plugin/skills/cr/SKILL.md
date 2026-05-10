---
name: cr
description: State-driven 3-round / 6-step cross-agent spec/plan review pipeline. Use `/cr` to advance the active pipeline. Reads `.cross-agent-reviews/<slug>/state.json`, dispatches the next round (1a → 1b → 2a → 2b → 3a → 3b), validates output via JSON Schema, and persists state. Audit rounds (1a, 2a, 3a) require fresh sessions; settle rounds (1b, 2b, 3b) do not. Supports cross-host paste-import for distributed reviews.
---

[Full attribution](_shared/attribution.md)

## 0. Determine intent and target slug

Operator's input is one of:

- **No input** — advance the active pipeline. Run `python "${CLAUDE_PLUGIN_ROOT}/skills/cr/_helpers/cr_state_pick_slug.py"` to pick the slug.
- **Artifact path** (e.g., `docs/specs/foo-design.md`) — start a new review or augment an existing slug. Run `python "${CLAUDE_PLUGIN_ROOT}/skills/cr/_helpers/cr_state_pick_slug.py" --input <path>`.
- **Outbound cross-host cue + artifact path** (an artifact path combined with "review on a different host", "this is for host B" / "for the other host", "init only" / "bootstrap only" / "export bootstrap", or "I'll continue on another host") — Host A side of the paste handshake. Initialize state locally and stop after emitting the bootstrap payload for the operator to carry to Host B. See §1.5 below; do NOT proceed to §2 or §4.
- **Slug name** — explicit slug. Run `python "${CLAUDE_PLUGIN_ROOT}/skills/cr/_helpers/cr_state_pick_slug.py" --input <slug>`.
- **Inbound cross-host paste cue** (a cross-host cue with NO artifact path, OR "I just ran round Na on host A", "import this round", "here is the paste") — Host B side: enter paste-import mode. See §3 below. (The disambiguator vs. the outbound branch is the presence of an artifact path: with a path the operator is starting a review and exporting it; without a path the operator is receiving someone else's paste.)
- **Status query** ("show status", `/cr status`) — run `python "${CLAUDE_PLUGIN_ROOT}/skills/cr/_helpers/cr_state_status.py" [--slug <slug>]` and present its output.

If `cr_state_pick_slug.py` returns `{"action": "ask_for_artifact_path"}`, ask the operator for the artifact path or a `state.json` paste, then re-run.

If `cr_state_pick_slug.py` returns `{"default": <slug>, "alternatives": [<slug>, ...]}` (two or more active slugs), surface the disambiguation to the operator: list `<default>` first (most recent activity, with any `pending_import` slug surfaced ahead of recency per Phase 7) and the alternatives below it, then ask which slug to advance. After the operator answers, re-invoke `python "${CLAUDE_PLUGIN_ROOT}/skills/cr/_helpers/cr_state_pick_slug.py" --input <chosen-slug>` to obtain `{"slug": <chosen-slug>, "artifact_type": <spec|plan>}` (the picker derives `artifact_type` from the latest block in `state.json` for slug-name input — see Phase 7). Use the result for §1 / §2; never proceed without `artifact_type` because §1's `cr_state_init.py` and §2's `cr_state_read.py` both require it.

## 1. Initialize state if needed

Run `cr_state_init.py` when **either** of these holds:

- `.cross-agent-reviews/<slug>/state.json` does not exist (first invocation for this slug), **or**
- the state file exists but its `state.<artifact_type>` block is absent (e.g., a completed spec review is being augmented with a plan, or a `restart` resolution from §2's spec-drift table is replacing the prior plan block under the same slug).

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/cr/_helpers/cr_state_init.py" --artifact-path <ARTIFACT_PATH> --artifact-type <spec|plan>
```

`cr_state_init.py` already handles both cases (a fresh state file and adding a missing block to an existing one — see Phase 4). It writes/updates `state.json`, derives the slug, hashes the artifact, prompts to add `.cross-agent-reviews/` to `.gitignore` (operator confirms `[y/N]`), and (for plan-only init) prints the warning per §11.3 of the spec.

`<ARTIFACT_TYPE>` is the `artifact_type` returned by `cr_state_pick_slug.py`. The picker derives it from the path's `docs/specs/` vs. `docs/plans/` directory (falling back to suffix `-design`/`-spec`/`-plan` per §5.5) when the input is an artifact path; for slug-name input and no-input single-active advance, it derives type from the latest block in `state.json` (most-recent `last_updated_at`, with ties going to `spec`). When the operator gave only a slug name and the relevant block is missing, the picker omits `artifact_type` and the router asks the operator for the artifact path before invoking the script.

The script's stdout is the `state.json` payload — capture it for cross-host scenarios.

## 1.5. Outbound cross-host bootstrap (Host A side)

Take this branch only when §0 classified the input as **outbound cross-host cue + artifact path** (artifact path supplied alongside one of the outbound trigger phrases). This is the matching half of §3's inbound paste-import: §1.5 emits the bootstrap payload on Host A; §3 receives it on Host B. Do NOT take this branch for cues alone (those route to §3) or for artifact paths alone (those continue through §1 → §2 → §4 normally).

Run init with the gitignore prompt suppressed — the operator only wants the bootstrap JSON, not an interactive `[y/N]` confirmation:

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/cr/_helpers/cr_state_init.py" --artifact-path <ARTIFACT_PATH> --artifact-type <spec|plan> --no-gitignore-prompt
```

Capture the script's stdout — that IS the canonical `state.json` payload (§1 already notes this). Present it to the operator with explicit copy instructions, then halt:

> Bootstrap state.json for Host B (copy below). On Host B, run `/cr` and paste this JSON when prompted; that host will validate the paste and run round 1a.
>
> ```json
> { …captured stdout… }
> ```

After emitting the message, **stop**. Do NOT proceed to §2 (read state) or §4 (dispatch round 1a). Round 1a runs on Host B once the paste is validated there — running it on Host A would defeat the cross-host handoff. The operator's next `/cr` on Host A will be either a status query or an inbound paste cue (§3) when round 1a returns from Host B.

## 2. Determine the next round and apply fresh-session policy

Read state:

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/cr/_helpers/cr_state_read.py" --slug <slug> --artifact-type <spec|plan>
```

Parse the JSON output. The next stage is `state.<artifact_type>.current_stage` minus the `round_` prefix and `_pending` suffix.

If `integrity == "STATE_INTEGRITY_ERROR"`, halt with `BLOCKED:state-integrity` and surface to the operator. (Check this before any other branch — an integrity error invalidates every subsequent decision.)

If `pending_import: true` in the read output, the operator switched hosts; route to §3 paste-import. **This check runs before the `ready_for_implementation` check below**: a terminal cross-host handoff can leave `state.<artifact_type>.current_stage == "ready_for_implementation"` with `completed_rounds` including `3b` while `round-3b.json` has not yet been pasted on this host (see Phase 6's `_classify`: `pending_import` flips true whenever any completed stage's round file is missing). Reading `final_status` from `round-3b.json` in that case would fail — the paste-import branch is what supplies the missing round file.

If `state.<artifact_type>.current_stage == "ready_for_implementation"`, the pipeline has already terminated for this artifact. Do NOT proceed to §3 or §4. Emit the third bullet of §5's round-completion message ("Pipeline complete. final_status: ...") by reading `final_status` from `<state-dir>/<slug>/<artifact_type>/round-3b.json` directly (the `cr_state_read.py` payload only carries state and integrity fields; `final_status` lives in the round-3b envelope per Phase 5), and stop. A rerun of `/cr` after completion is a status query, not a new dispatch.

For **plan rounds only**, run a spec-drift check before dispatch:

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/cr/_helpers/cr_state_read.py" --slug <slug> --check-spec-drift
```

Exit code 2 with `SPEC_DRIFT_DETECTED` on stderr means the spec file changed on disk vs. `state.plan.spec_hash_at_start`. Surface the three options from §7.8 of the design and translate the operator's choice into a scripted action; do not dispatch any sub-agent until drift is resolved.

| Operator choice | Router action |
|---|---|
| `restart` (re-init the plan against the current spec) | `python "${CLAUDE_PLUGIN_ROOT}/skills/cr/_helpers/cr_state_read.py" --slug <slug> --resolve-drift restart`. Then prompt the operator for the plan path and re-enter §1 to re-init the plan block under the same slug. |
| `accept-drift` (assert the plan still matches the new spec) | `python "${CLAUDE_PLUGIN_ROOT}/skills/cr/_helpers/cr_state_read.py" --slug <slug> --resolve-drift accept`. The script atomically refreshes `state.plan.spec_hash_at_start` to the current hash. Re-enter §2 with the new state. |
| `abort` (resolve out of band) | Halt with `BLOCKED:spec-drift` and surface the diagnostic. The operator decides what to do; rerunning `/cr` after manual edits resumes the pipeline. |

If next stage is an audit round (`1a`, `2a`, `3a`), execute the **fresh-session preflight** from [_shared/preflight.md](_shared/preflight.md) BEFORE doing anything else. If next stage is a settle round (`1b`, `2b`, `3b`), skip the preflight (per §5.4 of the spec).

## 3. Cross-host paste-import branch

If the operator's cue indicates a cross-host transition or local-only signal #2 (a `completed_rounds` entry whose round file is missing locally), enter paste-import:

1. Ask the operator to paste the JSON.
2. Determine the slug:
   - **Continuing host** (local state for this slug already exists, e.g., signal #2): use the slug already in scope from §0.
   - **Fresh host** (no local `.cross-agent-reviews/<slug>/` for any candidate slug): parse the pasted JSON's top-level `slug` field and use it. Bootstrap (`state.json`) and round payloads both carry `slug` per their schemas, so this is deterministic. If the parse fails or `slug` is missing, halt with a diagnostic and ask the operator to repaste.
3. Run `python "${CLAUDE_PLUGIN_ROOT}/skills/cr/_helpers/cr_state_read.py" --paste --slug <slug>`, with the pasted JSON on stdin.
4. The script auto-detects bootstrap (`state.json`) vs round (`round-<stage>.json`) shape. Bootstrap: refuses to clobber an existing local `state.json` for the slug (§10.3). Round: enforces schema, identity (`slug`, `artifact_type`, `artifact_path`), and round-order (pasted `stage` matches the next-expected stage per local state, with the pending-import override).
5. Exit code 0: paste accepted. Inform the operator and re-enter §2 to determine the new next round.
6. Exit code 1 with a diagnostic: surface to the operator (e.g., `stage mismatch`, `slug mismatch`, `clobber refused`).

## 4. Dispatch the round procedure

Map the derived stage token to its round file by suffix — audit rounds (`1a`, `2a`, `3a`) live in `rounds/<stage>-audit.md`; settle rounds (`1b`, `2b`, `3b`) live in `rounds/<stage>-settle.md`. Read that file and execute the procedure there. Each round file:

- Defines or carries the slice plan.
- Dispatches per-slice sub-agents using the parameterized
  [`_shared/dispatch-template.md`](_shared/dispatch-template.md).
- Aggregates sub-agent reports into a structured payload.
- Calls `python "${CLAUDE_PLUGIN_ROOT}/skills/cr/_helpers/cr_state_write.py" --slug <slug> --artifact-type <type> --artifact-path <path> --input <payload-file>` to persist.

The script validates schema + cross-round invariants, atomically writes
`round-<stage>.json` + updates `state.json`, and emits byte-identical JSON
to stdout. If validation fails, the script exits 1 with a specific
diagnostic; you may auto-retry **once** with the LLM error context, then
halt with `BLOCKED:validation` for operator intervention (§6.5 of spec).

## 5. Round-completion message

After `cr_state_write.py` succeeds, emit one of these messages to the
operator (per §9.2 of the spec):

- After audit round (1a, 2a, 3a) — next is settle:
  > Round Na complete (M findings). Run /cr to continue with round Nb.
  > A fresh session is not required for settle rounds; you may continue
  > in this session or open a new one.
- After settle round (1b, 2b) — next is audit, fresh session mandatory:
  > Round Nb complete (P accepted, Q rejected). Open a fresh session and
  > run /cr to continue with round (N+1)a (a fresh session is required
  > before audit rounds).
- After 3b (terminal):
  > Pipeline complete. final_status: <READY_FOR_IMPLEMENTATION |
  > CORRECTED_AND_READY>. <Description per status>.

## 6. Status query

If the operator asks for a status view (`/cr status`, "show status", "what round are we on?"), run:

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/cr/_helpers/cr_state_status.py" [--slug <slug>]
```

Present its output verbatim.
