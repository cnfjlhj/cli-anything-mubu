# cli-anything-mubu

Compatibility package path for the Mubu live bridge.

This path is kept so local development flows like `python -m cli_anything.mubu` continue to work from the repo root. The canonical packaged source now lives under `agent-harness/cli_anything/mubu/...`.

The entrypoints remain:

- `cli-anything-mubu` console script
- `python -m cli_anything.mubu`
- default REPL when no subcommand is supplied
- REPL banner with app version, packaged skill path, and history path
- persisted `current-doc` and `current-node` REPL context

Primary operator documentation remains at the project root:

- `README.md`
- `SKILL.md`
