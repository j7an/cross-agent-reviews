#!/usr/bin/env bats
# Characterization tests for scripts/verify-prompt-contract.sh.
# Exercises the v0.1.x verifier against the v0.1.x skill layout.

setup() {
  REPO_ROOT="$(git rev-parse --show-toplevel)"
  # shellcheck disable=SC2164
  cd "$REPO_ROOT"
}

make_scratch_repo() {
  scratch=$(mktemp -d)
  cp -R "$REPO_ROOT/plugin" "$scratch/"
  cp -R "$REPO_ROOT/scripts" "$scratch/"
  cp -R "$REPO_ROOT/.claude-plugin" "$scratch/"
  cp -R "$REPO_ROOT/.codex-plugin" "$scratch/"
  cd "$scratch" || return
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
  make_scratch_repo
  rm plugin/.claude-plugin/plugin.json
  run bash scripts/verify-prompt-contract.sh
  [ "$status" -ne 0 ]
}

@test "verifier exits non-zero when plugin.json description is mutated" {
  make_scratch_repo
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
  make_scratch_repo
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
  make_scratch_repo
  rm .codex-plugin/marketplace.json
  run bash scripts/verify-prompt-contract.sh
  [ "$status" -ne 0 ]
  echo "$output" | grep -q "F0:.*\.codex-plugin/marketplace\.json"
}

@test "verifier exits non-zero when preflight claims fresh sessions are required per round" {
  make_scratch_repo
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
  make_scratch_repo
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
  make_scratch_repo
  sed -e 's/Do NOT halt/halt with BLOCKED:mode-conflict/g' \
      plugin/skills/cr/SKILL.md > plugin/skills/cr/SKILL.md.new
  mv plugin/skills/cr/SKILL.md.new plugin/skills/cr/SKILL.md
  run bash scripts/verify-prompt-contract.sh
  [ "$status" -ne 0 ]
  echo "$output" | grep -q "F7:"
}

@test "verifier exits non-zero when shared prompts use CLAUDE_PLUGIN_ROOT" {
  make_scratch_repo
  cat >> plugin/skills/cr/_shared/status-report.md <<'EOF'

"${CLAUDE_PLUGIN_ROOT}/skills/cr/_helpers/cr" state-status
EOF
  run bash scripts/verify-prompt-contract.sh
  [ "$status" -ne 0 ]
  echo "$output" | grep -q "F8: shared CR prompts do not use Claude-specific plugin root variables"
}

@test "verifier exits non-zero when shared prompts cite installed .claude cache paths" {
  make_scratch_repo
  cat >> plugin/skills/cr/_shared/attribution.md <<'EOF'

Installed path: ~/.claude/plugins/cache/example
EOF
  run bash scripts/verify-prompt-contract.sh
  [ "$status" -ne 0 ]
  echo "$output" | grep -q "F8: shared CR prompts do not cite Claude-specific installed cache paths"
}

@test "verifier exits non-zero when shared prompts cite HOME .claude cache paths" {
  make_scratch_repo
  cat >> plugin/skills/cr/_shared/attribution.md <<'EOF'

Installed path: $HOME/.claude/plugins/cache/example
EOF
  run bash scripts/verify-prompt-contract.sh
  [ "$status" -ne 0 ]
  echo "$output" | grep -q "F8: shared CR prompts do not cite Claude-specific HOME cache paths"
}

@test "verifier exits non-zero when shared prompts use Codex-specific plugin root variables" {
  make_scratch_repo
  cat >> plugin/skills/cr/_shared/status-report.md <<'EOF'

"${CODEX_PLUGIN_ROOT}/skills/cr/_helpers/cr" state-status
EOF
  run bash scripts/verify-prompt-contract.sh
  [ "$status" -ne 0 ]
  echo "$output" | grep -q "F8: shared CR prompts do not use Codex-specific plugin root variables"
}

@test "verifier exits non-zero when shared prompts treat global CLAUDE.md as generic policy" {
  make_scratch_repo
  cat >> plugin/skills/cr/_shared/status-report.md <<'EOF'

Follow the operator's global CLAUDE.md before reviewing.
EOF
  run bash scripts/verify-prompt-contract.sh
  [ "$status" -ne 0 ]
  echo "$output" | grep -q "F8: shared CR prompts do not treat CLAUDE.md as the generic policy source"
}

@test "verifier exits non-zero when CR_HELPER contract lacks same-shell assignment" {
  make_scratch_repo
  sed -e '/CR_HELPER=.*_helpers\/cr/d' \
      -e '/same shell tool call/d' \
      plugin/skills/cr/SKILL.md > plugin/skills/cr/SKILL.md.new
  mv plugin/skills/cr/SKILL.md.new plugin/skills/cr/SKILL.md
  run bash scripts/verify-prompt-contract.sh
  [ "$status" -ne 0 ]
  echo "$output" | grep -q "F5a: SKILL.md defines CR_HELPER in the same shell tool call"
}

@test "verifier exits non-zero when a round prompt lacks local CR_HELPER setup" {
  make_scratch_repo
  sed -e '/CR_HELPER=.*_helpers\/cr/d' \
      plugin/skills/cr/rounds/1a-audit.md > plugin/skills/cr/rounds/1a-audit.md.new
  mv plugin/skills/cr/rounds/1a-audit.md.new plugin/skills/cr/rounds/1a-audit.md
  run bash scripts/verify-prompt-contract.sh
  [ "$status" -ne 0 ]
  echo "$output" | grep -q "F5a: plugin/skills/cr/rounds/1a-audit.md defines CR_HELPER before helper calls"
}

@test "verifier permits non-helper python command prose in shared prompts" {
  make_scratch_repo
  cat >> plugin/skills/cr/_shared/status-report.md <<'EOF'

Diagnostic note: `python "local-script.py"` is not a CR helper invocation.
EOF
  run bash scripts/verify-prompt-contract.sh
  [ "$status" -eq 0 ]
}

@test "verifier exits non-zero when prompts invoke helper scripts via raw python" {
  make_scratch_repo
  cat >> plugin/skills/cr/_shared/status-report.md <<'EOF'

python "/tmp/plugin/skills/cr/_helpers/cr_state_status.py" --slug example
EOF
  run bash scripts/verify-prompt-contract.sh
  [ "$status" -ne 0 ]
  echo "$output" | grep -q "F5b: plugin/skills/cr/_shared/status-report.md does not invoke CR helper scripts via raw python"
}

@test "verifier exits non-zero when prompts invoke helper scripts via python3 unquoted" {
  make_scratch_repo
  cat >> plugin/skills/cr/_shared/status-report.md <<'EOF'

python3 /tmp/plugin/skills/cr/_helpers/cr_state_status.py --slug example
EOF
  run bash scripts/verify-prompt-contract.sh
  [ "$status" -ne 0 ]
  echo "$output" | grep -q "F5b: plugin/skills/cr/_shared/status-report.md does not invoke CR helper scripts via raw python"
}

@test "verifier exits non-zero when prompts invoke helper scripts via raw python single quoted" {
  make_scratch_repo
  cat >> plugin/skills/cr/_shared/status-report.md <<'EOF'

python '/tmp/plugin/skills/cr/_helpers/cr_state_status.py' --slug example
EOF
  run bash scripts/verify-prompt-contract.sh
  [ "$status" -ne 0 ]
  echo "$output" | grep -q "F5b: plugin/skills/cr/_shared/status-report.md does not invoke CR helper scripts via raw python"
}

@test "verifier treats regex errors as failures" {
  make_scratch_repo
  sed -e 's#python\[0-9\.\]\*#[#g' \
      scripts/verify-prompt-contract.sh > scripts/verify-prompt-contract.sh.new
  mv scripts/verify-prompt-contract.sh.new scripts/verify-prompt-contract.sh
  run bash scripts/verify-prompt-contract.sh
  [ "$status" -ne 0 ]
  echo "$output" | grep -q "F5b: SKILL.md does not invoke CR helper scripts via raw python scan errored"
}

@test "verifier treats rg errors in tree scans as failures" {
  make_scratch_repo
  sed -e 's/check_tree_not_contains plugin\/skills\/cr/check_tree_not_contains plugin\/skills\/cr-missing/g' \
      scripts/verify-prompt-contract.sh > scripts/verify-prompt-contract.sh.new
  mv scripts/verify-prompt-contract.sh.new scripts/verify-prompt-contract.sh
  run bash scripts/verify-prompt-contract.sh
  [ "$status" -ne 0 ]
  echo "$output" | grep -q "F8: shared CR prompts do not use Claude-specific plugin root variables scan errored"
}
