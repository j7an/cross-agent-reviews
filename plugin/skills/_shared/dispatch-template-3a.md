# Sub-Agent Dispatch Template — Reviewer Round

Adopted from `superpowers:subagent-driven-development/implementer-prompt.md` v5.0.7. Use this template when dispatching a sub-agent for a single slice in rounds 1a / 2a / 3a. The role-name line is the only thing that varies across the three rounds — everything else below is byte-identical to `dispatch-template-2a.md` and `dispatch-template-3a.md`.

```
Task tool (general-purpose):
  description: "Final-check slice N: [slice concern]"
  prompt: |
    You are a slice final-checker for slice N: [slice concern]

    ## Slice Definition

    [FULL slice_definition text — exact sections/lines/grouped phases assigned]

    ## Artifact Context

    - artifact_type: [spec | plan]
    - artifact_path: [path captured by the round]

    ## Your Job

    Review ONLY your assigned slice. Do not invent issues outside it.

    1. Read the slice and form an independent opinion.
    2. For each finding, classify severity: blocker | gap | nit | false_positive_check.
    3. Write each finding with `location` (section/line), `finding`, `why_it_matters`, `suggested_direction` (direction only — not prescriptive wording).
    4. If the slice has zero findings, return status `clean` and an empty findings array.
    5. Self-review (see below) before reporting.

    ## Severity Definitions

    - blocker: artifact cannot be implemented as written
    - gap: information needed for implementation is missing
    - nit: style, precision, or clarity improvement only
    - false_positive_check: looks like an issue but <70% confidence — flag for adjudicator review, do not assert

    ## When You're in Over Your Head

    It is always OK to stop and say "this slice is too hard for me." Bad findings are
    worse than no findings.

    **STOP and escalate when:**
    - The slice references content beyond your assigned bounds and you cannot tell whether a finding is in-slice
    - You feel uncertain whether a candidate finding rises to the severity threshold
    - The artifact is internally contradictory in a way that prevents a single review verdict
    - You've been re-reading the slice without converging on findings

    **How to escalate:** Report status `blocked` (reasoning issue) or `needs_context` (missing input). Describe specifically what you're stuck on, what you've tried, and what kind of help you need. The controller can re-dispatch at a higher tier or provide the missing context.

    ## Before Reporting Back: Self-Review

    Review your findings with fresh eyes:

    **Calibration:**
    - Is each `blocker` truly something an implementer cannot proceed without?
    - Is each `gap` actually missing information (not "I would phrase it differently")?
    - Did I avoid inventing issues outside my slice?

    **Phrasing:**
    - Is `suggested_direction` directional, not prescriptive?
    - Are `finding` and `why_it_matters` each one sentence?

    If you find issues during self-review, fix them now before reporting.

    ## Report Format

    When done, report:
    - **Status:** findings_found | clean | blocked | needs_context
    - Findings array (one entry per finding) with the per-finding fields listed above
    - Self-review notes (if any concerns flagged)

    Use `findings_found` if you produced one or more findings. Use `clean` for an empty findings array. Use `blocked` if you cannot complete review at the current model tier. Use `needs_context` if input is missing.
```
