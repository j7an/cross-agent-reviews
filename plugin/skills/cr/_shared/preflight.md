# Pre-flight: confirm fresh session

This skill requires a fresh session to preserve cross-agent diversity.
Before doing any work, scan THIS conversation for evidence of prior
cross-review pipeline activity:

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
> per round to maintain cross-agent diversity.
>
> Please open a new session and invoke this skill there. The JSON you've
> already pasted will work identically in a new session.
>
> If you cannot start a fresh session (single-host fallback mode), reply
> with "override fresh-session check" to proceed in degraded mode.

Wait for operator's response. Do not proceed until either (a) you are
confident the session is fresh, or (b) the operator has explicitly
overridden the check.
