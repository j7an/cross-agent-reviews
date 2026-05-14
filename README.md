# cross-agent-reviews

A multi-host plugin (Claude Code + Codex) that packages a 3-round / 6-step cross-agent spec/plan review pipeline as a single state-driven skill. One slash command — `/cr` — advances the pipeline based on a project-local state file (`.cross-agent-reviews/<slug>/`), so operators no longer paste round JSON between rounds on a single host. Reviewer rounds *audit* the artifact in fresh sessions; author rounds *settle* findings without requiring a fresh session, with a strict final round preserving cross-agent diversity by construction. v0.1.x ships local-only; install via the host's `/plugin` slash-commands (see [Install](#install) below).

## How it works

| Round | Procedure | Role | Input | Output |
|---|---|---|---|---|
| 1a | `rounds/1a-audit.md` | Reviewer (5-agent parallel review) | spec/plan path | `round-1a.json` |
| 1b | `rounds/1b-settle.md` | Author (settle + edit) | `round-1a.json` | `round-1b.json` |
| 2a | `rounds/2a-audit.md` | Reviewer (verify corrections) | `round-1b.json` | `round-2a.json` |
| 2b | `rounds/2b-settle.md` | Author (settle + edit) | `round-2a.json` | `round-2b.json` |
| 3a | `rounds/3a-audit.md` | Reviewer (strict final check) | `round-2b.json` | `round-3a.json` |
| 3b | `rounds/3b-settle.md` | Author (final adjudication) | `round-3a.json` | `final_status` |

**Fresh session per audit round.** The router applies a fresh-session preflight only before audit rounds (1a, 2a, 3a) — cross-agent diversity demands the reviewer come to the artifact without prior interpretive frame. Settle rounds (1b, 2b, 3b) may continue in the same session or a fresh one (operator choice).

**Terminal status.** Round 3b emits one of two statuses:
- `READY_FOR_IMPLEMENTATION` — Round 3a found no blockers; artifact ships unchanged.
- `CORRECTED_AND_READY` — Round 3a found blockers; minimum corrections applied; artifact ships.

## Architecture

The plugin is a single skill with a router and six round procedures, backed by a project-local state directory:

```
plugin/skills/cr/
├── SKILL.md                     # router: parse intent, read state, dispatch
├── rounds/
│   ├── 1a-audit.md
│   ├── 1b-settle.md
│   ├── 2a-audit.md
│   ├── 2b-settle.md
│   ├── 3a-audit.md
│   └── 3b-settle.md
└── _shared/
    ├── preflight.md
    ├── dispatch-template.md
    ├── status-protocol.md
    ├── self-review.md
    ├── status-report.md
    ├── attribution.md
    ├── model-tier-rubric.md
    ├── cross-artifact-slice.md
    └── schema/                  # JSON Schema (Draft 2020-12) files
```

State directory layout (resolved via `git rev-parse --show-toplevel` from the artifact's directory; falls back to `cwd` if no git root):

```
<project-root>/.cross-agent-reviews/
└── <slug>/
    ├── state.json
    ├── spec/
    │   ├── round-1a.json
    │   ├── round-1b.json
    │   └── …
    └── plan/
        ├── round-1a.json
        └── …
```

The router parses operator intent, reads state, disambiguates the active slug, determines the next round, applies the fresh-session check (audit rounds only), executes the round procedure, calls `cr_state_write.py` to persist the round JSON + update `state.json`, and prints the next-step message.

Design rationale lives in [`docs/superpowers/specs/2026-05-07-issue-1-state-file-redesign-design.md`](docs/superpowers/specs/2026-05-07-issue-1-state-file-redesign-design.md).

This plugin's pipeline shape adapts patterns from the [Superpowers](https://github.com/obra/superpowers) plugin family (reference version 5.0.7):

- `superpowers:dispatching-parallel-agents` — parallel-dispatch decision pattern for slice planning.
- `superpowers:subagent-driven-development` — model-tier rubric, status protocol, and dispatch-template structure.

Full attribution at [`plugin/skills/cr/_shared/attribution.md`](plugin/skills/cr/_shared/attribution.md).

## Install

### Ubuntu 24.04 LTS (native or in WSL2)

```bash
sudo apt install python3 python3-pip ripgrep jq diffutils bats
curl -LsSf https://astral.sh/uv/install.sh | sh    # or: pipx install uv
uv sync
```

### macOS

```bash
brew install python@3.11 ripgrep jq uv bats-core
uv sync
```

### Windows (10 21H1+ or 11)

```bash
wsl --install -d Ubuntu-24.04
# Then inside Ubuntu, follow the Linux path
```

`uv sync` reads pyproject.toml + uv.lock and creates `.venv/`. Operators preferring vanilla pip can use `pip install .` instead — pyproject.toml is the standard format.

After `uv sync`, run the one-time hook install:

```bash
uv sync && uv run pre-commit install --hook-type pre-commit --hook-type pre-push
```

### Plugin install — Claude Code

In any Claude Code session:

```
/plugin marketplace add /path/to/cross-agent-reviews
/plugin install cross-agent-reviews@cross-agent-reviews
```

`/cr` appears in autocomplete. Restart the session if it doesn't surface immediately.

To uninstall: `/plugin uninstall cross-agent-reviews@cross-agent-reviews`. The marketplace registration stays; remove separately with `/plugin marketplace remove cross-agent-reviews` if desired.

### Plugin install — Codex

In Codex (CLI v0.128+):

```
codex plugin marketplace add /path/to/cross-agent-reviews
```

Then in the Codex TUI, open `/plugin`, navigate to the `cross-agent-reviews` marketplace, and install the `cross-agent-reviews` plugin. `$cr` appears in autocomplete. Restart the TUI once after install to refresh the skill index.

To uninstall, use `/plugin` in the TUI to uninstall the plugin, or run `codex plugin marketplace remove cross-agent-reviews` to drop the marketplace registration.

### From GitHub (forward-looking; v0.2+)

Once the repo is published at `https://github.com/j7an/cross-agent-reviews`, the same slash-command flow is expected to accept a GitHub URL as the marketplace source:

```
/plugin marketplace add https://github.com/j7an/cross-agent-reviews
/plugin install cross-agent-reviews@cross-agent-reviews
```

v0.1.x is local-only — the URL is reserved but not yet published.

## Platform support

- **Linux**: Ubuntu 24.04 LTS native.
- **macOS**: any modern release with current Homebrew.
- **Windows**: Ubuntu 24.04 LTS inside WSL2.
- **Native Windows** (cmd/PowerShell with Git Bash, MSYS2, Cygwin): best-effort, not in v0.1.x test matrix.

## Operating the pipeline

### Single-host workflow (no paste)

State file does all handoff. Per the §5.4 fresh-session policy, fresh sessions are mandatory only before audit rounds (1a, 2a, 3a); settle rounds (1b, 2b, 3b) may continue in the same session or a fresh one — operator's choice (design §9.1, §10.1).

```
[fresh session 1]    /cr <spec-path> → cr_state_init creates state, runs round 1a
[same or fresh]      /cr             → state says next is 1b; runs round 1b
[fresh session]      /cr             → state says next is 2a (audit); fresh required
[same or fresh]      /cr             → state says next is 2b; runs round 2b
[fresh session]      /cr             → state says next is 3a (audit); fresh required
[same or fresh]      /cr             → state says next is 3b; runs round 3b
[fresh session]      /cr <plan-path> → state has spec finished; plan starts at round 1a (audit, fresh required)
… [plan rounds with the same audit/settle alternation] …
```

Operator never pastes JSON.

### Cross-host workflow (paste at host transitions)

The state directory is gitignored, so it does not sync across hosts. At every host transition the operator gives an explicit natural-language cue ("review on a different host", "I just ran round 1a on the other host; here is its output"). The router routes such cues into paste-import mode instead of running the next round locally (design §10.2).

On the **initiating** host, the cue must be combined with the artifact path on the same `/cr` invocation — the router uses the presence of a path to disambiguate the **outbound** bootstrap branch (Host A: init locally and emit `state.json` for paste) from the **inbound** paste-import branch (Host B: receive the paste). A bare cue with no artifact path always routes to inbound paste-import.

```
[Host A, fresh] /cr <spec-path> review on a different host
                                    → outbound bootstrap branch: cr_state_init writes state on A
                                    → skill prints state.json (bootstrap payload) and STOPS
                                      (round 1a does NOT run on A)
[Host B, fresh] /cr                 → no local state; skill asks operator to paste state.json
                operator pastes     → cr_state_read.py --paste validates state.json (bootstrap path)
                                    → writes state.json locally
                                    → runs round 1a; emits round-1a.json (file + stdout)
[Host A, fresh] /cr                 → operator says "import round 1a from the other host"
                operator pastes     → cr_state_read.py --paste validates round-1a.json
                                    → writes round-1a.json locally; updates state.json
                                    → runs round 1b
… [continues] …
```

The operator pastes JSON twice per round-pair (one transit per host hop). Same UX as v0.1.0 paste-into-prompt; the state file makes single-host operation file-driven without regressing cross-host.

**Common mistakes:**

- *Forgetting the artifact path on first `/cr`* — the skill will ask; supply absolute or relative path.
- *Pasting the wrong round's JSON across hosts* — the skill detects round-order mismatch (pasted `stage` ≠ next expected) and asks you to repaste.
- *Editing the artifact between an author round (1b/2b) and the next reviewer round (2a/3a)* — manual edits in between break the contract; the reviewer round verifies the same artifact the previous author edited.

## Development

```bash
uv run pytest tests/                              # run Python tests
uv run pytest --cov=plugin/skills/cr/_helpers tests/  # with coverage
uv run ruff check .                               # lint
uv run ruff format .                              # format
bats tests/bats/                                  # bash tests
bash scripts/verify-prompt-contract.sh            # static prompt-content verifier
```

The verifier runs prompt-content checks across the v0.1.x layout. Required tools: `bash`, `rg` (ripgrep), `jq`, `diff`, `bats-core`.

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the TDD discipline, coverage floor, and conventional-commit conventions.

## Acknowledgments

This plugin's pipeline shape was iterated locally in a sibling repo (`superpowers-cross-agent-reviews`) over three commits before being extracted as a publishable plugin. The design directly adopts patterns from the [Superpowers](https://github.com/obra/superpowers) skill collection by Jesse Vincent and contributors. See [`plugin/skills/cr/_shared/attribution.md`](plugin/skills/cr/_shared/attribution.md) for the full attribution.

## License

MIT. See [`LICENSE`](LICENSE).
