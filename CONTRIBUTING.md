# Contributing to cross-agent-reviews

## One-time setup

```bash
uv sync                                           # install runtime + dev deps
uv run pre-commit install \
    --hook-type pre-commit --hook-type pre-push   # install hooks (pre-commit + pre-push)
```

## Dev task list

```bash
uv run pytest tests/                              # run Python tests
uv run pytest --cov=scripts tests/                # with coverage
uv run ruff check .                               # lint
uv run ruff format .                              # format
bats tests/bats/                                  # bash tests
bash scripts/verify-prompt-contract.sh            # static prompt-content verifier
```

## TDD discipline

Every new or modified `scripts/cr_*.py` (or `scripts/verify-prompt-contract.sh`) follows red-green-refactor:

1. Write `tests/test_<script>.py` with happy-path, error-path, and edge cases. Tests fail (red).
2. Run `uv run pytest tests/test_<script>.py` — confirm tests fail.
3. Implement `scripts/<script>.py` with the minimum code to pass.
4. Run `uv run pytest tests/test_<script>.py` — confirm tests pass (green).
5. Refactor for clarity, keeping tests green.

The first commit MUST introduce the test file; the second commit MUST introduce the implementation file. The auditable-evidence rule (per `docs/superpowers/specs/2026-05-07-issue-1-state-file-redesign-design.md` §8.3) is enforced by `tests/auditing/check_test_first_order.py`.

## Coverage floor

Python coverage is enforced at `>= 85%` via `--cov-fail-under=85` in the pre-push hook.

## Conventional commits

Commits follow the pattern `<type>(<scope>): <subject>`. Types we use:

- `feat` — feature work (the dominant prefix during v0.1.x state-file redesign)
- `fix` — bug fix
- `test` — test-only changes (e.g., retrofit characterization tests)
- `docs` — documentation
- `refactor` — internal restructuring with no behavior change
- `chore` — tooling and housekeeping

Per the project's CLAUDE.md, every commit's subject should match the **PR-level user-visible intent**, not the per-commit diff shape.
