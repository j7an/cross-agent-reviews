#!/usr/bin/env python3
"""Validate a single Finding JSON snippet against finding.schema.json.

Reads from stdin or `--file PATH`. Exits 0 on valid, 1 on invalid.
Diagnostic to stderr.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import jsonschema
from _cr_lib import build_registry, find_repo_root, load_schema
from jsonschema import Draft202012Validator


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a Finding JSON snippet.")
    parser.add_argument("--file", type=Path, help="Path to JSON file (else stdin).")
    args = parser.parse_args()

    raw = args.file.read_text() if args.file else sys.stdin.read()
    try:
        instance = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"ERROR: invalid JSON ({e})", file=sys.stderr)
        return 1

    repo_root = find_repo_root(Path.cwd())
    schema = load_schema(repo_root, "finding.schema.json")
    registry = build_registry(repo_root)
    try:
        Draft202012Validator(schema, registry=registry).validate(instance)
    except jsonschema.ValidationError as e:
        print(f"ERROR: schema violation: {e.message} at {list(e.absolute_path)}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
