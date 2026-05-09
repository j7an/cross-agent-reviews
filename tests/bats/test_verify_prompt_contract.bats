#!/usr/bin/env bats
# Characterization tests for scripts/verify-prompt-contract.sh.
# Exercises the v0.1.x verifier against the v0.1.x skill layout.

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
  # Removes plugin/.claude-plugin/plugin.json — a file the v0.1.x verifier
  # checks unconditionally as part of its common-assertion pass.
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
