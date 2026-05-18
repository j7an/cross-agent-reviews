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

@test "verifier exits non-zero when SKILL.md is missing the outbound cross-host bootstrap branch" {
  # F4: the outbound cross-host bootstrap branch (Host A side of the paste
  # handshake) is the only thing that lets an operator who combines an
  # artifact path with a cross-host cue actually export the state.json.
  # Strip both the section heading and the operator copy-instruction phrase
  # the verifier asserts on; the verifier must reject the result.
  scratch=$(mktemp -d)
  cp -R "$REPO_ROOT/." "$scratch/"
  cd "$scratch"
  # Replace both required phrases with placeholders so the check_contains
  # assertions fail. Keep the rest of SKILL.md byte-for-byte identical so the
  # mutation isolates the F4 signal from any other contract assertion.
  sed -e 's/Outbound cross-host bootstrap/REMOVED-OUTBOUND-HEADING/g' \
      -e 's/Bootstrap state.json for Host B/REMOVED-COPY-INSTRUCTIONS/g' \
      plugin/skills/cr/SKILL.md > plugin/skills/cr/SKILL.md.new
  mv plugin/skills/cr/SKILL.md.new plugin/skills/cr/SKILL.md
  run bash scripts/verify-prompt-contract.sh
  [ "$status" -ne 0 ]
  echo "$output" | grep -q "F4:"
}

@test "verifier exits non-zero when .codex-plugin/marketplace.json is missing" {
  # Removes .codex-plugin/marketplace.json — the 4th manifest file that Task 5
  # extends the F0/F1 checks to cover. The verifier must explicitly fail the
  # F0 existence check and reject the result.
  scratch=$(mktemp -d)
  cp -R "$REPO_ROOT/." "$scratch/"
  cd "$scratch"
  rm .codex-plugin/marketplace.json
  run bash scripts/verify-prompt-contract.sh
  [ "$status" -ne 0 ]
  echo "$output" | grep -q "F0:.*\.codex-plugin/marketplace\.json"
}

@test "verifier exits non-zero when preflight claims fresh sessions are required per round" {
  scratch=$(mktemp -d)
  cp -R "$REPO_ROOT/." "$scratch/"
  cd "$scratch"
  sed -e 's/Fresh-session preflight applies before audit rounds (1a, 2a, 3a) and the/This skill requires a fresh session per round to preserve cross-agent diversity. The/g' \
      plugin/skills/cr/_shared/preflight.md > plugin/skills/cr/_shared/preflight.md.new
  mv plugin/skills/cr/_shared/preflight.md.new plugin/skills/cr/_shared/preflight.md
  grep -q "per round" plugin/skills/cr/_shared/preflight.md
  run bash scripts/verify-prompt-contract.sh
  [ "$status" -ne 0 ]
  echo "$output" | grep -q "F6b:"
}

@test "verifier exits non-zero when SKILL.md is missing the non-mutating-path mode/profile rule" {
  # F7: the "Mode/profile tokens on non-mutating paths" paragraph is the only
  # thing that documents warn-and-continue behavior for conflicting mode/profile
  # tokens on terminal and pending-import reruns (issue #26). Strip both stable
  # anchors the verifier asserts on; the verifier must reject the result.
  scratch=$(mktemp -d)
  cp -R "$REPO_ROOT/." "$scratch/"
  cd "$scratch"
  sed -e 's#Mode/profile tokens on non-mutating paths#REMOVED-F7-HEADING#g' \
      -e 's/non-mutating continuations/REMOVED-F7-PHRASE/g' \
      plugin/skills/cr/SKILL.md > plugin/skills/cr/SKILL.md.new
  mv plugin/skills/cr/SKILL.md.new plugin/skills/cr/SKILL.md
  run bash scripts/verify-prompt-contract.sh
  [ "$status" -ne 0 ]
  echo "$output" | grep -q "F7:"
}

@test "verifier exits non-zero when SKILL.md weakens the non-mutating-path behavior text" {
  # F7 behavioral anchors: the section heading can survive while the
  # warn-and-continue behavior is weakened back to a halt. Strip only a
  # behavior phrase ("Do NOT halt"), leaving the structural anchors intact,
  # and confirm F7 still catches it — guards the false negative a reviewer
  # reproduced (issue #26).
  scratch=$(mktemp -d)
  cp -R "$REPO_ROOT/." "$scratch/"
  cd "$scratch"
  sed -e 's/Do NOT halt/halt with BLOCKED:mode-conflict/g' \
      plugin/skills/cr/SKILL.md > plugin/skills/cr/SKILL.md.new
  mv plugin/skills/cr/SKILL.md.new plugin/skills/cr/SKILL.md
  run bash scripts/verify-prompt-contract.sh
  [ "$status" -ne 0 ]
  echo "$output" | grep -q "F7:"
}
