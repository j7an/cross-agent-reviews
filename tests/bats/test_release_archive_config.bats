#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  ARCHIVE_JSON="$REPO_ROOT/.release-archive.json"
}

@test "release-archive.json exists" {
  [ -f "$ARCHIVE_JSON" ]
}

@test "release-archive.json parses as JSON" {
  jq empty "$ARCHIVE_JSON"
}

@test "release-archive.json has .paths array with at least 1 entry" {
  count="$(jq '.paths | length' "$ARCHIVE_JSON")"
  [ "$count" -ge 1 ]
}

@test ".paths[] contains the required install-surface entries" {
  # The curated artifact MUST include code (plugin/), both marketplace
  # roots, README, and LICENSE. Extras (e.g., future docs) are allowed
  # — this is a superset check, not exact equality.
  required="plugin
.claude-plugin
.codex-plugin
README.md
LICENSE"
  actual="$(jq -r '.paths[]' "$ARCHIVE_JSON")"
  while IFS= read -r need; do
    case $'\n'"$actual"$'\n' in
      *$'\n'"$need"$'\n'*) ;;
      *) echo "Missing required install-surface entry: $need"; false ;;
    esac
  done <<< "$required"
}

@test "every .paths[] entry resolves to existing file or directory" {
  while IFS= read -r path; do
    [ -e "$REPO_ROOT/$path" ] || { echo "Missing: $path"; false; }
  done < <(jq -r '.paths[]' "$ARCHIVE_JSON")
}

@test "every version-bump path is covered by a release-archive path" {
  # Drift safeguard from spec §4.3: .version-bump.json paths must be a
  # subset of .release-archive.json paths (or prefixed by one).
  BUMP_JSON="$REPO_ROOT/.version-bump.json"
  if [ ! -f "$BUMP_JSON" ]; then
    skip "version-bump.json not yet present (Task 3 not landed)"
  fi
  while IFS= read -r bump_path; do
    covered=false
    while IFS= read -r archive_path; do
      case "$bump_path" in
        "$archive_path"|"$archive_path"/*) covered=true; break ;;
      esac
    done < <(jq -r '.paths[]' "$ARCHIVE_JSON")
    [ "$covered" = true ] || { echo "Uncovered: $bump_path"; false; }
  done < <(jq -r '.files[].path' "$BUMP_JSON")
}
