# Model Tier Guidance for Sub-Agent Dispatch

Adopted from `superpowers:subagent-driven-development` v5.0.7. Tiers are abstract — no model names — so the rubric survives lineup changes across hosts (Claude Code, Codex, future hosts).

Use the least powerful model that can handle each role. This conserves cost and increases throughput.

**Mechanical review tasks** (focused slice, well-bounded concern, deterministic check): use a fast, cheap model. Most slice reviews against a clean spec are mechanical when the slice is well-defined.

**Integration and judgment tasks** (cross-section consistency, global coherence, nuanced gap detection): use a standard model.

**Hardest review tasks** (architectural critique, "does it solve the stated problem", final ship-gate strictness): use the most capable available model.

**Slice complexity signals:**
- Single tightly-scoped concern with explicit acceptance criteria → cheap model
- Cross-section dependencies or subtle gap detection → standard model
- Requires design judgment, broad architectural understanding, or final-ship rigour → most capable model

**Per-round defaults:**

| Round | Reviewer dispatch | Author session |
|---|---|---|
| 1a / 2a | Standard model per slice (escalate by signal above) | n/a |
| 3a | Most capable per slice (final ship gate; bar is high) | n/a |
| 1b / 2b / 3b | n/a | Most capable available — adjudication is judgment work |
