# Author-Round Status Report Format

Referenced by author rounds 1b / 2b / 3b. Adopted from `superpowers:subagent-driven-development` v5.0.7. Author rounds retain the original Superpowers uppercase status labels — this preserves the case-distinguishable JSON contract from reviewer rounds (which use lowercase per `status-protocol.md`).

## Status Categories

| Status | Meaning | Controller action |
|---|---|---|
| `DONE` | Author completed adjudication and applied edits to the artifact | Emit output JSON |
| `DONE_WITH_CONCERNS` | Author completed but flagged doubts (e.g., a corrected wording the author isn't confident reads cleanly) | Read concerns; address if correctness-relevant; emit output JSON otherwise |
| `BLOCKED` | Author cannot complete adjudication or edits (e.g., `artifact_path` references a missing file, irreconcilable findings) | Re-dispatch at a higher model tier; if `artifact_path` is wrong, follow §7.1 path/type correction exception |
| `NEEDS_CONTEXT` | Required input missing (e.g., malformed paste, missing JSON field) | Provide the missing context and re-dispatch |

## Path/Type Correction Exception

If an author round detects `artifact_path` references a missing/wrong file or `artifact_type` is clearly inconsistent with the artifact's content, the round halts with `BLOCKED` status BEFORE applying any edits. The operator confirms or supplies a corrected value; the round re-emits its output JSON with the corrected field, which subsequent rounds propagate unchanged. This is the only sanctioned exception to the unchanged-propagation rule in §7.1.

Author rounds MUST validate `artifact_path` resolves to an existing file before applying any edits, so the halt occurs pre-mutation and re-dispatch with the corrected path is safe.

## Reporting Discipline

- `DONE` is the goal. Do not emit `DONE_WITH_CONCERNS` to express minor preferences — only genuine correctness doubts.
- `BLOCKED` and `NEEDS_CONTEXT` MUST include a one-sentence reason in the round-level output (so the operator and the next round can act on it).
- Never silently emit `DONE` with a partial implementation — surface concerns explicitly.
