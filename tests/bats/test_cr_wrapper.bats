#!/usr/bin/env bats
# Tests for plugin/skills/cr/_helpers/cr — the uv-backed wrapper that
# delegates Python environment management (interpreter version +
# dependencies) to `uv run`. The wrapper is the documented entry point
# for SKILL.md helper invocations; operators only need `uv` installed.
#
# Why these tests:
#   1. No-args → exit 2 with "Usage:" — proves the argparse-like
#      doorman behaviour for empty input.
#   2. Unknown subcommand → exit 2 with "unknown subcommand" — proves
#      the case statement rejects invalid input rather than failing
#      cryptically inside uv.
#   3. Valid subcommand --help → exit 0 with "usage:" — proves the
#      wrapper correctly forwards args to the underlying Python helper
#      AND uv resolves Python 3.11 + jsonschema/referencing without
#      ImportError. This is the operator-path reproduction the
#      reviewer asked for.
#   4. Missing uv → exit 2 with "uv not found" — proves the wrapper
#      degrades gracefully when its sole external dependency is absent.

setup() {
  REPO_ROOT="$(git rev-parse --show-toplevel)"
  WRAPPER="$REPO_ROOT/plugin/skills/cr/_helpers/cr"
}

@test "cr with no args exits 2 with Usage in stderr" {
  run "$WRAPPER"
  [ "$status" -eq 2 ]
  echo "$output" | grep -q "Usage:"
}

@test "cr with unknown subcommand exits 2 with unknown subcommand in stderr" {
  run "$WRAPPER" nonexistent-subcommand
  [ "$status" -eq 2 ]
  echo "$output" | grep -q "unknown subcommand"
}

@test "cr state-init --help exits 0 and prints argparse usage" {
  run "$WRAPPER" state-init --help
  [ "$status" -eq 0 ]
  echo "$output" | grep -q "usage:"
}

@test "cr exits 2 with uv not found when uv is absent from PATH" {
  # Construct a PATH that contains only an empty tmpdir, so `command -v uv`
  # cannot resolve uv. Keep /usr/bin in PATH so bash itself (and `command`)
  # still works on the test host; macOS keeps `command` as a shell builtin
  # so /usr/bin coverage is paranoia-belt-and-suspenders.
  empty_dir=$(mktemp -d)
  PATH="$empty_dir:/usr/bin:/bin" run "$WRAPPER"
  [ "$status" -eq 2 ]
  echo "$output" | grep -q "uv not found"
}
