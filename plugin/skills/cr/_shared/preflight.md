# Pre-flight: confirm fresh session

Fresh-session preflight applies only before audit rounds (1a, 2a, 3a).
Settle rounds (1b, 2b, 3b) do not run this preflight and may continue in
the same session or a fresh one. Before an audit round, scan THIS
conversation for evidence of prior cross-review pipeline activity:

**Evidence of prior skill activation in this session:**
- Another `cr-*` skill was activated earlier
- Tool calls related to a previous round (e.g., 1a sub-agent dispatches,
  1b artifact edits)
- Agent reasoning, summaries, or generated content from a different round

**NOT evidence (these are expected and normal):**
- The user's current prompt invoking THIS skill
- JSON the operator pasted as input for THIS round
- The skill's own instructions you are currently reading

**If you find evidence of prior skill activation:** STOP. Reply:

> I detected prior cross-review pipeline activity in this conversation
> ([describe what you found]). The pipeline requires a fresh session
> before audit rounds to maintain cross-agent diversity.
>
> Please open a new session and invoke this skill there. The JSON you've
> already pasted will work identically in a new session.
>
> If you cannot start a fresh session before this audit round
> (single-host fallback mode), reply "override fresh-session check" to
> proceed in degraded mode.

Wait for operator's response. Do not proceed until either (a) you are
confident the session is fresh, or (b) the operator has explicitly
overridden the check.
