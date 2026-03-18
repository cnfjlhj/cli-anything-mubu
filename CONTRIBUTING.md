# Contributing to cli-anything-mubu

## Project Structure

```
mubu-live-bridge/
├── agent-harness/                 # Canonical source root
│   ├── cli_anything/mubu/         # Packaged CLI source
│   │   ├── mubu_cli.py            # Click CLI + REPL
│   │   ├── utils/repl_skin.py     # CLI-Anything official REPL skin
│   │   ├── skills/SKILL.md        # Generated skill descriptor
│   │   └── tests/                 # Canonical test modules
│   ├── mubu_probe.py              # Core probe library
│   ├── skill_generator.py         # SKILL.md regeneration tool
│   ├── templates/                 # Skill template assets
│   ├── setup.py                   # Harness-scoped setuptools config
│   └── pyproject.toml             # Build system declaration
├── mubu_probe.py                  # Compatibility shim (delegates to agent-harness/)
├── cli_anything/mubu/             # Compatibility shim tree
├── tests/                         # Project-root test runners (delegate to canonical)
├── setup.py                       # Root-level setuptools config
├── registry.json                  # CLI-Anything harness registry entry
├── CONTRIBUTING.md                # This file
└── README.md                      # Project overview
```

## Development Setup

```bash
# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install in editable mode from the harness root
pip install -e agent-harness/

# Verify the installation
cli-anything-mubu --help
```

## Running Tests

```bash
# Run all canonical tests via the project-root runners
python3 -m unittest discover -s tests -p 'test_*.py' -v

# Run a specific test module
python3 -m unittest tests/test_mubu_probe.py -v

# Run canonical tests directly
python3 -m unittest discover -s agent-harness/cli_anything/mubu/tests -p 'test_*.py' -v
```

## Test Organization

| File | Scope |
|------|-------|
| `test_mubu_probe.py` | Core library: parsing, normalization, path resolution, request building |
| `test_cli_entrypoint.py` | CLI surface: help rendering, REPL builtins, session persistence |
| `test_agent_harness.py` | Packaging: harness structure, setup metadata, contribution file checks |
| `test_core.py` | Core function contracts: pure logic, no I/O, no live API |
| `test_full_e2e.py` | End-to-end: CLI invocations against real local Mubu data |

Tests live in `agent-harness/cli_anything/mubu/tests/` (canonical) and are re-exported
via `tests/` at the project root through `_canonical_loader.py`.

## Adding a New Command

1. Add the probe function in `agent-harness/mubu_probe.py`
2. Register it in the appropriate Click group in `agent-harness/cli_anything/mubu/mubu_cli.py`
3. Add unit tests in the relevant `test_*.py` module
4. Regenerate the skill descriptor: `python3 agent-harness/skill_generator.py agent-harness`
5. Update the compatibility shim if needed

## Safety Model

- All live mutations default to **dry-run**. Pass `--execute` to apply.
- Inspect before mutate: verify the target node exists and matches expectations.
- The project does not store or transmit credentials beyond the local Mubu desktop session.

## Code Style

- Type hints on all function signatures
- `click>=8.0` for the CLI surface
- No global mutable state; session state is file-backed JSON
- Keep files under 400 lines where practical
