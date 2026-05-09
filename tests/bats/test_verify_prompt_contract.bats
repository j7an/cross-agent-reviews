#!/usr/bin/env bats
# Characterization tests for scripts/verify-prompt-contract.sh.
# Locks the v0.1.0 verifier behavior before any v0.1.x modification.

setup() {
  REPO_ROOT="$(git rev-parse --show-toplevel)"
  # shellcheck disable=SC2164
  cd "$REPO_ROOT"
}

@test "verifier exits 0 against the current repo" {
  run bash scripts/verify-prompt-contract.sh
  [ "$status" -eq 0 ]
}

@test "verifier prints no FAIL lines on the current repo" {
  run bash scripts/verify-prompt-contract.sh
  [ "$status" -eq 0 ]
  # shellcheck disable=SC2314
  ! echo "$output" | grep -q "^FAIL:"
}

@test "verifier exits non-zero when a required manifest file is missing" {
  # Removes a file the verifier checks in BOTH the v0.1.0 and v0.1.x
  # layouts (the common assertion in scripts/verify-prompt-contract.sh
  # checks plugin/.claude-plugin/plugin.json regardless of layout). This
  # keeps the characterization test meaningful through the Phase 10 →
  # Phase 11 transition; targeting an old-layout-only file (e.g.,
  # plugin/skills/cr-1a-audit/SKILL.md) would silently pass after Phase 10
  # because the verifier flips to v0.1.x mode and skips v0.1.0 checks.
  scratch=$(mktemp -d)
  cp -R "$REPO_ROOT/." "$scratch/"
  cd "$scratch"
  rm plugin/.claude-plugin/plugin.json
  run bash scripts/verify-prompt-contract.sh
  [ "$status" -ne 0 ]
}

@test "verifier exits non-zero when plugin.json description is mutated" {
  scratch=$(mktemp -d)
  cp -R "$REPO_ROOT/." "$scratch/"
  cd "$scratch"
  jq '.description = "junk"' plugin/.claude-plugin/plugin.json > plugin/.claude-plugin/plugin.json.new
  mv plugin/.claude-plugin/plugin.json.new plugin/.claude-plugin/plugin.json
  run bash scripts/verify-prompt-contract.sh
  [ "$status" -ne 0 ]
}

@test "verifier exits non-zero when a v0.1.0 skill manifest is missing" {
  # Characterization of the v0.1.0-specific 39-check set: removing one of
  # the v0.1.0 cr-* skill manifests must trip the verifier. Without this
  # case, a retrofit could silently drop the entire v0.1.0 branch and the
  # other three bats tests would still pass — leaving acceptance #5 with
  # no enforcement that v0.1.0 behavior was preserved through the
  # transition. Phase 11 Task 11.2 step 3 removes this test together with
  # the v0.1.0 fallback in the verifier itself.
  scratch=$(mktemp -d)
  cp -R "$REPO_ROOT/." "$scratch/"
  cd "$scratch"
  rm plugin/skills/cr-1a-audit/SKILL.md
  run bash scripts/verify-prompt-contract.sh
  [ "$status" -ne 0 ]
}
