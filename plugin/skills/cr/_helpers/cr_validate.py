#!/usr/bin/env python3
"""Validate a round envelope or state.json against its JSON Schema.

`--kind` selects the schema:
    audit  → round-audit.schema.json
    settle → round-settle.schema.json
    state  → state.schema.json

Reads from stdin or `--file PATH`. Exits 0 on valid, 1 on invalid.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import jsonschema
from _cr_lib import build_registry, find_repo_root, load_schema
from jsonschema import Draft202012Validator

KIND_TO_SCHEMA = {
    "audit": "round-audit.schema.json",
    "settle": "round-settle.schema.json",
    "state": "state.schema.json",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a cross-agent-reviews JSON envelope.")
    parser.add_argument("--kind", choices=list(KIND_TO_SCHEMA), required=True)
    parser.add_argument("--file", type=Path)
    args = parser.parse_args()

    raw = args.file.read_text() if args.file else sys.stdin.read()
    try:
        instance = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"ERROR: invalid JSON ({e})", file=sys.stderr)
        return 1

    repo_root = find_repo_root(Path.cwd())
    schema = load_schema(repo_root, KIND_TO_SCHEMA[args.kind])
    registry = build_registry(repo_root)
    try:
        Draft202012Validator(schema, registry=registry).validate(instance)
    except jsonschema.ValidationError as e:
        path = "/".join(str(p) for p in e.absolute_path) or "<root>"
        print(f"ERROR: schema violation at {path}: {e.message}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
