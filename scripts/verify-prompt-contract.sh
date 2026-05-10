#!/usr/bin/env bash
# shellcheck disable=SC2010,SC2015,SC2016
# Dev-time prompt-content static check for the v0.1.x state-driven layout.
#
# Phase 11.2 deleted the v0.1.0 six-skill layout and tightened this verifier
# to v0.1.x only (`plugin/skills/cr/` router + rounds + _shared schema/content).
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

# --- Layout guard: v0.1.x only ---
if [[ ! -f plugin/skills/cr/SKILL.md ]]; then
  printf 'FAIL: v0.1.x skill layout not detected (missing plugin/skills/cr/SKILL.md)\n' >&2
  exit 1
fi

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

# F3: Codex skills path resolves to a directory with exactly 1 SKILL.md
# (the v0.1.x router skill at `plugin/skills/cr/SKILL.md`).
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
    if [[ "$skill_count" != "1" ]]; then
      printf 'FAIL: F3: Codex skills path resolves to %s SKILL.md files (expected 1)\n' "$skill_count"
      failures=$((failures+1))
    fi
  fi
else
  printf 'FAIL: F3: skipped because %s does not exist\n' "$CODEX_PLUGIN"
  failures=$((failures+1))
fi

# --- v0.1.x checks (router + rounds + schemas + shared content) ---

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

# --- Manifest description content ---
check_contains plugin/.claude-plugin/plugin.json "State-driven" "manifest mentions state-driven"

# --- Router branch coverage ---
# F4: SKILL.md must document the outbound cross-host bootstrap branch (Host A
# side of the paste handshake). Without it, an operator who supplies an
# artifact path together with a cross-host cue dead-ends — the inbound
# paste-import branch (§3) only covers the receiving host. See README.md
# cross-host workflow.
check_contains plugin/skills/cr/SKILL.md "Outbound cross-host bootstrap" \
  "F4: SKILL.md documents outbound cross-host bootstrap branch"
check_contains plugin/skills/cr/SKILL.md "Bootstrap state.json for Host B" \
  "F4: SKILL.md includes operator copy instructions for bootstrap payload"

# --- Summary ---

if [[ "$failures" -gt 0 ]]; then
  printf '\n%s check(s) failed.\n' "$failures"
  exit 1
fi

printf 'Prompt contract checks passed.\n'
