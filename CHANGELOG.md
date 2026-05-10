# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Single state-driven `/cr` skill replacing the v0.1.0 six-skill paste-into-prompt architecture.
- `.cross-agent-reviews/<slug>/` state directory with `state.json`, per-artifact-type subdirs, and round-N-X.json files.
- Eight Python helper scripts under `scripts/` for state management, validation, and placeholder extraction.
- JSON Schema (Draft 2020-12) files under `plugin/skills/cr/_shared/schema/` for state, audit envelopes, settle envelopes, and per-entity shapes.
- Cross-artifact reviewer slice for plan reviews (mechanically detects hallucinated literal substitutions for spec placeholders).
- Modern Python toolchain: `pyproject.toml` + `uv` + `ruff` + `pytest` + `pytest-cov` + `pre-commit` + `bats-core`.
- TDD requirement on every script (audit script in `tests/auditing/check_test_first_order.py`).

### Changed

- Plugin description updated to reflect single-skill state-driven architecture.
- `verify-prompt-contract.sh` updated for the v0.1.x layout (with retrofit characterization tests in `tests/bats/`).
- README install paths and operator workflow.

### Removed

- Six top-level skills `cr-1a-audit`, `cr-1b-settle`, `cr-2a-audit`, `cr-2b-settle`, `cr-3a-final-audit`, `cr-3b-final-settle` — replaced by `plugin/skills/cr/`.
- `plugin/skills/_shared/` — content migrated to `plugin/skills/cr/_shared/`.

### Resolves

- Issue #1: settle-skill input contract conflict in `cr-2b-settle` (state file replaces multi-round JSON paste handoff).
- Real-world placeholder-hallucination failure on 2026-05-06 (cross-artifact slice catches it deterministically).

## [0.1.0] - 2026-05-04

### Added

- Initial release of `cross-agent-reviews` multi-host plugin (Claude Code + Codex).
- Six skills covering the 3-round / 6-step cross-agent spec/plan review pipeline:
  - `cr-1a-audit` (reviewer)
  - `cr-1b-settle` (author)
  - `cr-2a-audit` (reviewer)
  - `cr-2b-settle` (author)
  - `cr-3a-final-audit` (reviewer)
  - `cr-3b-final-settle` (author, terminal)
- `plugin/skills/_shared/` directory with 9 DRY content files (preflight, attribution, model-tier rubric, three dispatch templates, status protocol, self-review checklist, status report).
- Three plugin manifests: Claude Code `plugin.json` + `marketplace.json`, Codex `plugin.json` with `interface` block.
- Dev-time prompt-content static verifier (`scripts/verify-prompt-contract.sh`) with 39 checks across categories A-H per design spec §10.2.
- README with 8 sections per design spec §12.
- MIT license.

### Architecture notes

- **Path A (inline)** Superpowers integration — no plugin dependency; full attribution in `plugin/skills/_shared/attribution.md`.
- **Paste-into-prompt** runtime model — cross-host portable, compaction-resilient.
- **Parallel-build migration** — the source iteration repo `superpowers-cross-agent-reviews` is preserved unchanged as a reference; this plugin was built fresh.

[Unreleased]: https://github.com/j7an/cross-agent-reviews/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/j7an/cross-agent-reviews/releases/tag/v0.1.0
