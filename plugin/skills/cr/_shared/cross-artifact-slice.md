# Cross-artifact slice — sub-agent prompt

This addendum applies only when the round is on a plan AND
`state.spec.path` is non-null. The cross-artifact slice is `agent_id: 6`
and is fixed (`is_fixed: true`) across all three rounds.

## What you receive

The round procedure has already invoked
`python "${CLAUDE_PLUGIN_ROOT}/skills/cr/_helpers/cr_extract_placeholders.py" --spec-path <S> --plan-path <P>` and
captured its JSON output. That output is the **extractor report** — the
mechanical part of the slice. It enumerates:

1. `spec_placeholders[]` — every placeholder pattern detected in the
   spec, with its plan correspondence (single, multiple, or zero
   candidates). For each candidate, the report tells you the plan
   `literal`, whether it appears `is_substituted`, whether it
   `is_flagged_unverified`, and whether the surrounding text
   `has_inline_citation`.
2. `plan_only_concrete_values[]` — **backticked** concrete values (file
   paths, version pins, hashes, IDs, ports) present in the plan but
   absent from the spec. Detection is intentionally limited to
   inline-code spans (text between backticks) because that is the
   author's explicit "this is a literal value" signal; un-backticked
   numbers in surrounding prose would produce too many false positives
   (a "5-step phase" or a "v0.1.x release" mention is not a deliberate
   substituted value). The LLM sub-agent may still cite un-backticked
   prose mentions in its finding text, but the deterministic enumeration
   is backtick-scoped.

You do **not** grep, do **not** compute locations, do **not** compare
strings. The script did all of that.

## What you must classify

For each `spec_placeholders[]` entry, classify the plan correspondence:

| Classification | Condition | Verdict |
|---|---|---|
| Preserved | Plan keeps the placeholder verbatim | PASS |
| Verified substitution | Plan substitutes a concrete value AND has an inline citation | PASS |
| Flagged unverified | Plan substitutes but explicitly marks `<unverified — needs lookup: ...>` | PASS |
| Hallucinated literal | Plan has a concrete value with no citation, no flag | **BLOCKER** |

For each `plan_only_concrete_values[]` entry, classify:

| Classification | Condition | Verdict |
|---|---|---|
| Cited | Inline citation present | PASS |
| Flagged | Marked `<unverified ...>` | PASS |
| Derivable from context | The value is a derivative of something explicit in the plan or spec | PASS |
| Unprovenanced | No citation, no flag, no obvious derivation | **BLOCKER** |

## Severity rule

All findings emerge as `severity: blocker`. No gaps, no nits, no
false_positive_check. `cr_validate.py` rejects findings from this slice
that have any other severity.

## What to return

Per-finding `Finding` records following the canonical shape:

```json
{
  "location": "plan §X line Y (corresponds to spec §A line B)",
  "severity": "blocker",
  "finding": "Plan substitutes hallucinated literal '12345678' for spec placeholder '<numeric-id>'",
  "why_it_matters": "An implementer would commit a fabricated UID to production; CLAUDE.md rule and prior misattribution incident attest to the risk",
  "suggested_direction": "Restore the placeholder OR cite a primary source for the substituted value OR flag as <unverified — needs lookup: ...>"
}
```

The script assigns `id` (per §6.1.1). You only supply the four content
fields plus `location` and `severity`.

## Why this matters

The cross-artifact slice mechanically enforces the placeholder-substitution
rule already documented in the operator's global CLAUDE.md ("Evidence and
Verification" → "Placeholder substitution"). The rule's prior failure
(GitHub UID hallucination causing commit-attribution misattribution) is
the canonical bug this slice prevents.
