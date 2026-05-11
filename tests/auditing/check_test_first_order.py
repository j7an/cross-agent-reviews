#!/usr/bin/env python3
"""Audit: every (test, script) pair has its test commit before its implementation commit.

Ordering is decided by Git commit ancestry, not by `%cI` timestamp strings.
Two commits made within the same wall-clock second produce identical
`%cI` values (Git records committer date with second-level precision), so
a timestamp-based audit can flake on rapid back-to-back commits. Ancestry
(`git merge-base --is-ancestor`) is monotonic on a single branch and
unambiguous across branches: if the test commit is an ancestor of the
implementation commit, the test was committed earlier.

For the retrofit case, the `--retrofit` flag takes `<test_path>:<script_path>:<baseline_tag>`
triples and verifies the characterization-test commit is an ancestor of every
script-modifying commit since the baseline tag.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def _first_introducing_commit(path: Path) -> str | None:
    result = subprocess.run(
        ["git", "log", "--diff-filter=A", "--format=%H", "--", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    if not lines:
        return None
    return lines[-1]


def _modifying_commits_since_tag(path: Path, baseline_tag: str) -> list[str]:
    rev_range = f"{baseline_tag}..HEAD"
    result = subprocess.run(
        ["git", "log", rev_range, "--format=%H", "--", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return [ln for ln in result.stdout.splitlines() if ln.strip()]


def _is_strict_ancestor(ancestor_sha: str, descendant_sha: str) -> bool:
    """True iff `ancestor_sha` is reachable from `descendant_sha` AND distinct.

    `git merge-base --is-ancestor X X` returns 0 (same-commit counts as
    ancestor of itself). For TDD evidence, same-commit is NOT acceptable —
    it does not prove the test predates the implementation, only that they
    were committed together. The audit explicitly requires strict-before:
    the test must be a *proper* ancestor of the implementation.
    """
    if ancestor_sha == descendant_sha:
        return False
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor_sha, descendant_sha],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--pair",
        action="append",
        default=[],
        help="<test_path>:<script_path> for new-script TDD pairs.",
    )
    p.add_argument(
        "--retrofit",
        action="append",
        default=[],
        help="<test_path>:<script_path>:<baseline_tag> for retrofit pairs.",
    )
    args = p.parse_args()

    failures = 0

    for pair in args.pair:
        test_path, script_path = pair.split(":")
        test_sha = _first_introducing_commit(Path(test_path))
        script_sha = _first_introducing_commit(Path(script_path))
        if test_sha is None or script_sha is None:
            print(f"FAIL: missing commit data for pair {pair}", file=sys.stderr)
            failures += 1
            continue
        if not _is_strict_ancestor(test_sha, script_sha):
            same_commit_note = " (committed together)" if test_sha == script_sha else ""
            print(
                f"FAIL: {test_path} commit {test_sha[:7]} is not strictly earlier than "
                f"{script_path} commit {script_sha[:7]}{same_commit_note} (test commit is not "
                f"a strict ancestor of script commit; same-commit does not count as TDD evidence)",
                file=sys.stderr,
            )
            failures += 1

    for triple in args.retrofit:
        test_path, script_path, baseline_tag = triple.split(":")
        test_sha = _first_introducing_commit(Path(test_path))
        if test_sha is None:
            print(
                f"FAIL: retrofit characterization test {test_path} has no introducing commit",
                file=sys.stderr,
            )
            failures += 1
            continue
        script_mods = _modifying_commits_since_tag(Path(script_path), baseline_tag)
        for sha in script_mods:
            if not _is_strict_ancestor(test_sha, sha):
                same_commit_note = " (committed together)" if test_sha == sha else ""
                print(
                    f"FAIL: retrofit script {script_path} modified at commit {sha[:7]}{same_commit_note} "
                    f"is not strictly after characterization test {test_path} commit {test_sha[:7]} "
                    f"(characterization test is not a strict ancestor of script modification)",
                    file=sys.stderr,
                )
                failures += 1

    if failures > 0:
        return 1
    print("All test-first orderings hold.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
