#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  BUMP_JSON="$REPO_ROOT/.version-bump.json"
  # shared-workflows' inline regex validator for path_expr (verified
  # at j7an/shared-workflows tag-release.yml ~line 258).
  SHARED_REGEX='^\.[A-Za-z_][A-Za-z_0-9]*(\.[A-Za-z_][A-Za-z_0-9]*|\[[0-9]+\]|\["[A-Za-z0-9._@/-]+"\]|\[\])*$'
}

@test "version-bump.json exists" {
  [ -f "$BUMP_JSON" ]
}

@test "version-bump.json parses as JSON" {
  jq empty "$BUMP_JSON"
}

@test "version-bump.json has exactly 4 .files entries" {
  count="$(jq '.files | length' "$BUMP_JSON")"
  [ "$count" -eq 4 ]
}

@test ".files[].path set is exactly the 4 expected version-bearing manifests with no duplicates" {
  expected=".claude-plugin/marketplace.json
.codex-plugin/marketplace.json
plugin/.claude-plugin/plugin.json
plugin/.codex-plugin/plugin.json"
  # Sorted comparison guards against ordering changes; uniq guards
  # against duplicate-path configs that would still total 4 entries.
  actual="$(jq -r '.files[].path' "$BUMP_JSON" | sort)"
  unique="$(jq -r '.files[].path' "$BUMP_JSON" | sort -u)"
  expected_sorted="$(printf '%s\n' "$expected" | sort)"
  [ "$actual" = "$expected_sorted" ] || { echo "Path set differs."; diff <(echo "$expected_sorted") <(echo "$actual"); false; }
  [ "$actual" = "$unique" ] || { echo "Duplicate paths in .files[]"; false; }
}

@test "every entry uses path_expr (none use legacy 'field')" {
  has_field="$(jq '[.files[] | has("field")] | any' "$BUMP_JSON")"
  has_expr="$(jq '[.files[] | has("path_expr")] | all' "$BUMP_JSON")"
  [ "$has_field" = "false" ]
  [ "$has_expr" = "true" ]
}

@test "every path_expr matches shared-workflows regex" {
  while IFS= read -r expr; do
    [[ "$expr" =~ $SHARED_REGEX ]] || { echo "Bad path_expr: $expr"; false; }
  done < <(jq -r '.files[].path_expr' "$BUMP_JSON")
}

@test "every path resolves to existing file" {
  while IFS= read -r path; do
    [ -f "$REPO_ROOT/$path" ] || { echo "Missing: $path"; false; }
  done < <(jq -r '.files[].path' "$BUMP_JSON")
}

@test "every path_expr resolves under path to a non-empty string scalar" {
  # Catches regex-valid typos that point at the wrong key/index AND
  # rejects non-string targets (object, array, bool, number, null) that
  # `jq -er` alone would accept — the bumper expects a version string.
  while IFS=$'\t' read -r path expr; do
    jq -er "$expr | select(type == \"string\" and length > 0)" "$REPO_ROOT/$path" > /dev/null \
      || { echo "Resolve failed or wrong type: $path :: $expr"; false; }
  done < <(jq -r '.files[] | [.path, .path_expr] | @tsv' "$BUMP_JSON")
}
