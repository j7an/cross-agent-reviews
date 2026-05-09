#!/usr/bin/env bash
# shellcheck disable=SC2010,SC2015,SC2016
# Dev-time prompt-content static check. Supports v0.1.0 and v0.1.x layouts.
#
# During the Phase 10 dual-layout window both the v0.1.0 (`plugin/skills/cr-*/`)
# and the v0.1.x (`plugin/skills/cr/`) layouts may be present on disk. The
# verifier runs WHATEVER set of checks the on-disk state warrants. Phase 11.2
# deletes the v0.1.0 layout and tightens the verifier (drops the `has_old`
# branch).
#
# Requires: bash, rg (ripgrep), jq, diff (POSIX).

set -euo pipefail

# Resolve repo root (the directory containing this script's parent dir).
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
cd "$ROOT"

failures=0

# --- Helpers ---

check_contains() {
  local file="$1"; local pattern="$2"; local description="$3"
  if ! rg -q --fixed-strings "$pattern" "$file" 2>/dev/null; then
    printf 'FAIL: %s (%s)\n' "$description" "$file"
    failures=$((failures + 1))
  fi
}

check_not_contains() {
  local file="$1"; local pattern="$2"; local description="$3"
  if rg -q --fixed-strings "$pattern" "$file" 2>/dev/null; then
    printf 'FAIL: %s (%s)\n' "$description" "$file"
    failures=$((failures + 1))
  fi
}

check_file_exists() {
  local path="$1"; local description="$2"
  if [[ ! -e "$path" ]]; then
    printf 'FAIL: %s (%s)\n' "$description" "$path"
    failures=$((failures + 1))
  fi
}

check_jq_eq() {
  local file_a="$1"; local jq_a="$2"; local file_b="$3"; local jq_b="$4"; local description="$5"
  local val_a val_b
  val_a="$(jq -r "$jq_a" "$file_a" 2>/dev/null || echo '<jq-error>')"
  val_b="$(jq -r "$jq_b" "$file_b" 2>/dev/null || echo '<jq-error>')"
  if [[ "$val_a" != "$val_b" ]]; then
    printf 'FAIL: %s (%s ~ %s : %s != %s)\n' "$description" "$file_a" "$file_b" "$val_a" "$val_b"
    failures=$((failures + 1))
  fi
}

check_dir_contents() {
  local dir="$1"; shift
  local expected=("$@")
  local actual
  # Use $ROOT/$dir absolute paths so the fallback cd works regardless of the
  # outer subshell's CWD (the first cd succeeds and stays in $dir; if BSD find
  # then fails because -printf is GNU-only, the relative-path fallback would
  # cd from $dir into $dir/$dir and error).
  actual="$(cd "$ROOT/$dir" && find . -maxdepth 1 -type f -printf '%f\n' 2>/dev/null \
    || (cd "$ROOT/$dir" && ls -1 -p | grep -v '/$'))"
  local missing=() extra=()
  for f in "${expected[@]}"; do
    grep -qx "$f" <<< "$actual" || missing+=("$f")
  done
  while IFS= read -r f; do
    [[ -z "$f" ]] && continue
    local found=0
    for e in "${expected[@]}"; do [[ "$f" == "$e" ]] && found=1 && break; done
    [[ $found -eq 0 ]] && extra+=("$f")
  done <<< "$actual"
  if [[ ${#missing[@]} -gt 0 || ${#extra[@]} -gt 0 ]]; then
    printf 'FAIL: %s contents (missing=%s extra=%s)\n' "$dir" "${missing[*]:-none}" "${extra[*]:-none}"
    failures=$((failures + 1))
  fi
}

check_files_match_modulo_pattern() {
  local file_a="$1"; local file_b="$2"; local pattern="$3"; local description="$4"
  local diff_out
  diff_out="$(diff "$file_a" "$file_b" || true)"
  # All differing lines (those starting < or >) must match the pattern.
  local bad
  bad="$(printf '%s\n' "$diff_out" | rg -e '^[<>] ' || true)"
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    if ! printf '%s\n' "$line" | rg -q "$pattern"; then
      printf 'FAIL: %s (unexpected diff line: %s)\n' "$description" "$line"
      failures=$((failures + 1))
      return
    fi
  done <<< "$bad"
}

# --- Layout detection (transitional: both layouts may co-exist) ---
# The verifier runs WHATEVER set of checks the on-disk state warrants.
# During Phase 10 both layouts are present (new files added, old not yet
# deleted) — both check sets fire so the dual-layout completion gate
# (Task 10.11) is a real proof, not a single-layout subset. Phase 11
# deletes the old layout and tightens the verifier (drops `has_old`
# branch).
has_old=0
has_new=0
[[ -f plugin/skills/cr-1a-audit/SKILL.md ]] && has_old=1
[[ -f plugin/skills/cr/SKILL.md ]] && has_new=1
if [[ "$has_old" -eq 0 && "$has_new" -eq 0 ]]; then
  printf 'FAIL: neither v0.1.0 nor v0.1.x skill layout detected\n' >&2
  exit 1
fi
echo "Verifying layouts: v0.1.0=$has_old v0.1.x=$has_new"

# --- Common assertions (always run) ---

CC_PLUGIN="plugin/.claude-plugin/plugin.json"
CC_MARKET=".claude-plugin/marketplace.json"
CODEX_PLUGIN="plugin/.codex-plugin/plugin.json"

# Existence guard for the three manifests. Without this, F1/F2/F3 would
# pass spuriously when manifests are missing — `check_jq_eq` degrades to
# `<jq-error>` on both sides (compares equal), and the bare F3 jq lets `find`
# succeed on `$ROOT/` and discover SKILL.md anyway. Explicit FAIL here keeps
# the manifest smoke test actionable.
check_file_exists "$CC_PLUGIN" "F0: $CC_PLUGIN exists"
check_file_exists "$CC_MARKET" "F0: $CC_MARKET exists"
check_file_exists "$CODEX_PLUGIN" "F0: $CODEX_PLUGIN exists"

# F1: name and version match across all 3 manifests
check_jq_eq "$CC_PLUGIN" '.name' "$CODEX_PLUGIN" '.name' "F1: CC plugin.json and Codex plugin.json name match"
check_jq_eq "$CC_PLUGIN" '.version' "$CODEX_PLUGIN" '.version' "F1: CC plugin.json and Codex plugin.json version match"
check_jq_eq "$CC_PLUGIN" '.name' "$CC_MARKET" '.plugins[0].name' "F1: CC plugin.json and marketplace.json name match"
check_jq_eq "$CC_PLUGIN" '.version' "$CC_MARKET" '.plugins[0].version' "F1: CC plugin.json and marketplace.json version match"

# F2: top-level description identical between CC and Codex
check_jq_eq "$CC_PLUGIN" '.description' "$CODEX_PLUGIN" '.description' "F2: CC and Codex top-level description identical"

# F3: Codex skills path resolves to a directory with the expected SKILL.md
# count. v0.1.0 ships 6 SKILL.md (one per cr-*/ skill); v0.1.x ships 1
# SKILL.md (the router under cr/). During the dual-layout window the find
# discovers BOTH sets, so the expected value is parameterized as
# `has_old*6 + has_new*1`. Phase 11.2 collapses this back to a constant.
if [[ -e "$CODEX_PLUGIN" ]]; then
  codex_skills_path="$(jq -r '.skills' "$CODEX_PLUGIN" 2>/dev/null || echo '')"
  if [[ -z "$codex_skills_path" || "$codex_skills_path" == "null" ]]; then
    printf 'FAIL: F3: %s has no .skills key (expected a path)\n' "$CODEX_PLUGIN"
    failures=$((failures+1))
  else
    # Resolve .skills relative to plugin root (./plugin/), not repo root,
    # because Codex resolves manifest-internal paths relative to the plugin's
    # source path declared in marketplace.json (which is "./plugin").
    codex_skills_abs="$ROOT/plugin/${codex_skills_path#./}"
    skill_count="$(find "$codex_skills_abs" -mindepth 2 -maxdepth 2 -name SKILL.md -type f 2>/dev/null | wc -l | tr -d ' ')"
    expected_count=$((has_old * 6 + has_new))
    if [[ "$skill_count" != "$expected_count" ]]; then
      printf 'FAIL: F3: Codex skills path resolves to %s SKILL.md files (expected %s)\n' "$skill_count" "$expected_count"
      failures=$((failures+1))
    fi
  fi
else
  printf 'FAIL: F3: skipped because %s does not exist\n' "$CODEX_PLUGIN"
  failures=$((failures+1))
fi

# --- v0.1.0 checks (run while old layout is still on disk) ---

if [[ "$has_old" -eq 1 ]]; then
  # --- Category A: Existing prompt-content checks (retargeted) ---

  A1="plugin/skills/cr-1a-audit/SKILL.md"
  check_contains "$A1" '"slice_plan": [' "A1: Round 1a must emit slice_plan"
  check_contains "$A1" '"slice_definition": "sections/lines reviewed"' "A2: Round 1a must emit per-agent slice_definition"
  check_contains "$A1" 'Always include every array shown in the schema. Use `[]` when empty.' "A3: Round 1a must define empty-array behavior"

  A4="plugin/skills/cr-1b-settle/SKILL.md"
  check_contains "$A4" '"rejected_findings": [' "A4: Round 1b must emit rejected_findings"
  check_contains "$A4" 'verdict = accept|reject' "A5: Round 1b must remove defer verdict"
  check_not_contains "$A4" 'verdict = accept|reject|defer' "A6: Round 1b must not allow defer verdict"
  check_contains "$A4" 'Paste the full Round 1 review JSON below.' "A7: Round 1b standalone about input"

  A8="plugin/skills/cr-2a-audit/SKILL.md"
  check_contains "$A8" 'Use the provided `slice_plan` exactly as given.' "A8: Round 2a must freeze slice plan"
  check_contains "$A8" 'Do not reopen or restate anything in `rejected_findings`.' "A9: Round 2a must preserve rejected findings"
  check_contains "$A8" 'Round 1 adjudication JSON (use `accepted_findings`, `rejected_findings`, and `slice_plan`):' "A10: Round 2a must consume Round 1 adjudication JSON"

  A11="plugin/skills/cr-2b-settle/SKILL.md"
  check_contains "$A11" 'Adjudicate each verification issue: accept | reject.' "A11: Round 2b standalone about verdicts"
  check_contains "$A11" '"rejected_findings": [' "A12: Round 2b must emit rejected_findings"
  check_not_contains "$A11" 'verdict = accept|reject|defer' "A13: Round 2b must not allow defer verdict"

  A14="plugin/skills/cr-3a-final-audit/SKILL.md"
  check_contains "$A14" 'Use the provided `slice_plan` exactly as given.' "A14: Round 3a must freeze slice plan"
  check_contains "$A14" 'Round 2 adjudication JSON (use `accepted_findings`, `rejected_findings`, and `slice_plan`):' "A15: Round 3a must consume Round 2 adjudication JSON"

  # A16 retargeted to _shared/self-review.md per spec §10.2 amendment
  check_contains "plugin/skills/_shared/self-review.md" 'resolves the finding' "A16: self-review rules inlined in _shared/self-review.md"

  A17="plugin/skills/cr-3b-final-settle/SKILL.md"
  check_contains "$A17" 'Always include every array shown in the schema. Use `[]` when empty.' "A17: Round 3b must define empty-array behavior"

  # --- Category B: Skill structural checks ---

  ALL_SKILLS=(
    plugin/skills/cr-1a-audit/SKILL.md
    plugin/skills/cr-1b-settle/SKILL.md
    plugin/skills/cr-2a-audit/SKILL.md
    plugin/skills/cr-2b-settle/SKILL.md
    plugin/skills/cr-3a-final-audit/SKILL.md
    plugin/skills/cr-3b-final-settle/SKILL.md
  )

  for f in "${ALL_SKILLS[@]}"; do
    # B1: frontmatter with name and description
    head -10 "$f" | rg -q --fixed-strings 'name:' || { printf 'FAIL: B1: %s missing name in frontmatter\n' "$f"; failures=$((failures+1)); }
    head -10 "$f" | rg -q --fixed-strings 'description:' || { printf 'FAIL: B1: %s missing description in frontmatter\n' "$f"; failures=$((failures+1)); }
    # B2: name matches directory
    dir_name="$(basename "$(dirname "$f")")"
    rg -q --fixed-strings "name: $dir_name" "$f" || { printf 'FAIL: B2: %s name does not match dir %s\n' "$f" "$dir_name"; failures=$((failures+1)); }
    # B3: short attribution comment + markdown link to ../_shared/attribution.md
    rg -q --fixed-strings 'superpowers:dispatching-parallel-agents' "$f" || { printf 'FAIL: B3: %s missing dispatching-parallel-agents in attribution comment\n' "$f"; failures=$((failures+1)); }
    rg -q --fixed-strings 'superpowers:subagent-driven-development' "$f" || { printf 'FAIL: B3: %s missing subagent-driven-development in attribution comment\n' "$f"; failures=$((failures+1)); }
    rg -q --fixed-strings '../_shared/attribution.md' "$f" || { printf 'FAIL: B3: %s missing link to ../_shared/attribution.md\n' "$f"; failures=$((failures+1)); }
  done

  # --- Category C: JSON contract additions (artifact_path) ---

  # C1: 1a explicitly emits artifact_path
  check_contains "$A1" '"artifact_path"' "C1: Round 1a output schema includes artifact_path"
  # C2: 1b/2a/2b/3a/3b each include artifact_path in copy-unchanged language
  for f in "$A4" "$A8" "$A11" "$A14" "$A17"; do
    check_contains "$f" 'artifact_path' "C2: $f mentions artifact_path"
  done
  # C3: all 6 SKILL.md output schemas contain "artifact_path"
  for f in "${ALL_SKILLS[@]}"; do
    check_contains "$f" '"artifact_path"' "C3: $f schema example contains artifact_path field"
  done

  # --- Category D: Architecture pattern checks (in _shared/) ---

  check_contains "plugin/skills/_shared/model-tier-rubric.md" 'most capable' "D1: model-tier-rubric.md most-capable tier"
  check_contains "plugin/skills/_shared/model-tier-rubric.md" 'standard' "D1: model-tier-rubric.md standard tier"
  check_contains "plugin/skills/_shared/model-tier-rubric.md" 'fast' "D1: model-tier-rubric.md fast tier"

  for label in findings_found clean blocked needs_context; do
    check_contains "plugin/skills/_shared/status-protocol.md" "$label" "D2: status-protocol.md $label"
  done

  for phrase in 'resolves the finding' 'does not introduce new ambiguity' 'does not over-specify' 'does not create contradictions'; do
    check_contains "plugin/skills/_shared/self-review.md" "$phrase" "D3: self-review.md '$phrase'"
  done

  # --- Category E: Runtime model checks ---

  # E1: 1b/2a/2b/3a/3b mention paste-instruction language
  for f in "$A4" "$A8" "$A11" "$A14" "$A17"; do
    rg -q --fixed-strings 'operator will paste' "$f" \
      || rg -q --fixed-strings 'Paste the full' "$f" \
      || { printf 'FAIL: E1: %s missing paste-instruction language\n' "$f"; failures=$((failures+1)); }
  done

  # E2: 1b/2a/2b/3a/3b include round-mismatch / discriminator instruction
  for f in "$A4" "$A8" "$A11" "$A14" "$A17"; do
    rg -q --fixed-strings 'discriminator' "$f" \
      || rg -q --fixed-strings 'mismatch' "$f" \
      || { printf 'FAIL: E2: %s missing round-mismatch detection language\n' "$f"; failures=$((failures+1)); }
  done

  # E3: 3b sets final_status enum and does not propagate to round 4
  check_contains "$A17" 'READY_FOR_IMPLEMENTATION' "E3: 3b sets READY_FOR_IMPLEMENTATION"
  check_contains "$A17" 'CORRECTED_AND_READY' "E3: 3b sets CORRECTED_AND_READY"
  check_not_contains "$A17" '"round": 4' "E3: 3b does not propagate to round 4"

  # --- Category G: Pre-flight check checks ---

  # G1: _shared/preflight.md vocabulary + each SKILL.md links to it
  check_contains "plugin/skills/_shared/preflight.md" 'fresh session' "G1: preflight.md 'fresh session'"
  check_contains "plugin/skills/_shared/preflight.md" 'cross-review pipeline activity' "G1: preflight.md 'pipeline activity'"
  check_contains "plugin/skills/_shared/preflight.md" 'override fresh-session check' "G1: preflight.md 'override clause'"
  for f in "${ALL_SKILLS[@]}"; do
    check_contains "$f" '../_shared/preflight.md' "G1: $f links to preflight.md"
  done

  # G2: each SKILL.md tooltip first-line contains 'Fresh session'
  for f in "${ALL_SKILLS[@]}"; do
    check_contains "$f" 'Fresh session' "G2: $f tooltip contains 'Fresh session'"
  done

  # --- Category H: Shared-file integrity checks ---

  # H1: _shared/ contains exactly the 9 expected files
  check_dir_contents "plugin/skills/_shared" \
    preflight.md attribution.md model-tier-rubric.md \
    dispatch-template-1a.md dispatch-template-2a.md dispatch-template-3a.md \
    status-protocol.md self-review.md status-report.md

  # H2: every _shared/*.md file is non-empty
  for f in plugin/skills/_shared/*.md; do
    if [[ ! -s "$f" ]]; then
      printf 'FAIL: H2: %s is empty\n' "$f"
      failures=$((failures+1))
    fi
  done

  # H3: dispatch-template-{1a,2a,3a}.md differ only on role-name lines
  ROLE_PATTERN='(slice reviewer|slice verifier|slice final-checker|Review slice N|Verify slice N|Final-check slice N)'
  check_files_match_modulo_pattern \
    plugin/skills/_shared/dispatch-template-1a.md \
    plugin/skills/_shared/dispatch-template-2a.md \
    "$ROLE_PATTERN" \
    "H3: dispatch-template-1a vs -2a differ only on role-name line"
  check_files_match_modulo_pattern \
    plugin/skills/_shared/dispatch-template-1a.md \
    plugin/skills/_shared/dispatch-template-3a.md \
    "$ROLE_PATTERN" \
    "H3: dispatch-template-1a vs -3a differ only on role-name line"

  # H4: each SKILL.md links to its required _shared/*.md files per archetype
  A1_LINKS=(preflight.md attribution.md model-tier-rubric.md dispatch-template-1a.md status-protocol.md)
  A2_LINKS=(preflight.md attribution.md model-tier-rubric.md dispatch-template-2a.md status-protocol.md)
  A3_LINKS=(preflight.md attribution.md model-tier-rubric.md dispatch-template-3a.md status-protocol.md)
  B_LINKS=(preflight.md attribution.md self-review.md status-report.md)
  for ref in "${A1_LINKS[@]}"; do check_contains "$A1" "../_shared/$ref" "H4: 1a links $ref"; done
  for ref in "${A2_LINKS[@]}"; do check_contains "$A8" "../_shared/$ref" "H4: 2a links $ref"; done
  for ref in "${A3_LINKS[@]}"; do check_contains "$A14" "../_shared/$ref" "H4: 3a links $ref"; done
  for ref in "${B_LINKS[@]}"; do
    check_contains "$A4" "../_shared/$ref" "H4: 1b links $ref"
    check_contains "$A11" "../_shared/$ref" "H4: 2b links $ref"
    check_contains "$A17" "../_shared/$ref" "H4: 3b links $ref"
  done

  # H5: attribution.md begins with the canonical HTML comment block
  head -1 "plugin/skills/_shared/attribution.md" | rg -q '^<!--' \
    || { printf 'FAIL: H5: attribution.md does not begin with <!--\n'; failures=$((failures+1)); }
  check_contains "plugin/skills/_shared/attribution.md" 'superpowers:dispatching-parallel-agents' "H5: attribution.md names dispatching-parallel-agents"
  check_contains "plugin/skills/_shared/attribution.md" 'superpowers:subagent-driven-development' "H5: attribution.md names subagent-driven-development"
  check_contains "plugin/skills/_shared/attribution.md" '5.0.7' "H5: attribution.md references 5.0.7"
fi

# --- v0.1.x checks (run when the new router skill is on disk) ---

if [[ "$has_new" -eq 1 ]]; then
  check_file_exists plugin/skills/cr/SKILL.md "Router SKILL.md"
  for stage in 1a-audit 1b-settle 2a-audit 2b-settle 3a-audit 3b-settle; do
    check_file_exists "plugin/skills/cr/rounds/${stage}.md" "Round file: $stage"
  done

  # Use parallel positional arrays (NOT `declare -A`) so the verifier runs
  # under Bash 3.2 — the default /bin/bash on macOS. `declare -A` requires
  # Bash 4+; the bats characterization tests invoke `bash scripts/...`
  # directly (not via the shebang), so a Homebrew Bash 5 on PATH is not
  # guaranteed to be picked up. Positional arrays exist in Bash 3.2.
  seen_schema_ids=()
  seen_schema_files=()
  for schema in finding verification adjudication changelog-entry self-review-entry state round-audit round-settle; do
    f="plugin/skills/cr/_shared/schema/${schema}.schema.json"
    check_file_exists "$f" "Schema: ${schema}"
    if [[ -f "$f" ]]; then
      schema_uri="$(jq -r '."$schema" // ""' "$f")"
      if [[ "$schema_uri" != "https://json-schema.org/draft/2020-12/schema" ]]; then
        printf 'FAIL: %s does not declare Draft 2020-12 ($schema=%s)\n' "$f" "$schema_uri"
        failures=$((failures + 1))
      fi
      # `$id` must be present (the registry in `_cr_lib.build_registry` keys
      # off it) and unique across the suite (duplicate ids would silently
      # shadow each other in the registry, breaking $ref resolution at
      # runtime). Empty-or-missing is treated the same as duplicate-empty.
      schema_id="$(jq -r '."$id" // ""' "$f")"
      if [[ -z "$schema_id" ]]; then
        printf 'FAIL: %s is missing $id\n' "$f"
        failures=$((failures + 1))
      else
        duplicate_of=""
        i=0
        while [[ $i -lt ${#seen_schema_ids[@]} ]]; do
          if [[ "${seen_schema_ids[$i]}" == "$schema_id" ]]; then
            duplicate_of="${seen_schema_files[$i]}"
            break
          fi
          i=$((i + 1))
        done
        if [[ -n "$duplicate_of" ]]; then
          printf 'FAIL: duplicate $id %s in %s (also declared by %s)\n' "$schema_id" "$f" "$duplicate_of"
          failures=$((failures + 1))
        else
          seen_schema_ids+=("$schema_id")
          seen_schema_files+=("$f")
        fi
      fi
    fi
  done
  for shared in preflight dispatch-template status-protocol self-review status-report attribution model-tier-rubric cross-artifact-slice; do
    check_file_exists "plugin/skills/cr/_shared/${shared}.md" "Shared content: $shared"
  done
fi

# --- Manifest description content (post-migration only) ---
# This check requires the v0.1.x manifest description shipped in Task 11.1.
# During the Phase 10 dual-layout window the manifest still has the v0.1.0
# wording, so the assertion is gated on v0.1.0 having been deleted (i.e.,
# only the new layout remains). After Task 11.2 deletes the old layout,
# `has_old=0` and `has_new=1` together signal the post-migration state.
if [[ "$has_old" -eq 0 && "$has_new" -eq 1 ]]; then
  check_contains plugin/.claude-plugin/plugin.json "state-driven" "manifest mentions state-driven"
fi

# --- Summary ---

if [[ "$failures" -gt 0 ]]; then
  printf '\n%s check(s) failed.\n' "$failures"
  exit 1
fi

printf 'Prompt contract checks passed.\n'
