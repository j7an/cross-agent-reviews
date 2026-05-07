# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[0.1.0]: https://github.com/j7an/cross-agent-reviews/releases/tag/v0.1.0
