"""Smoke test: pytest + jsonschema work in this venv."""

from pathlib import Path

import jsonschema


def test_jsonschema_importable():
    assert hasattr(jsonschema, "validate")


def test_jsonschema_validate_minimal():
    jsonschema.validate(instance={"x": 1}, schema={"type": "object"})


def test_3c_verify_round_file_exists():
    """Assert that 3c-verify.md round procedure file exists and has key content."""
    p = Path(__file__).resolve().parent.parent / "plugin/skills/cr/rounds/3c-verify.md"
    assert p.is_file()
    text = p.read_text()
    assert "round_3c_pending" in text
    assert "fresh-session preflight" in text.lower()
