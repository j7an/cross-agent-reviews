"""Smoke test: pytest + jsonschema work in this venv."""

import jsonschema


def test_jsonschema_importable():
    assert hasattr(jsonschema, "validate")


def test_jsonschema_validate_minimal():
    jsonschema.validate(instance={"x": 1}, schema={"type": "object"})
