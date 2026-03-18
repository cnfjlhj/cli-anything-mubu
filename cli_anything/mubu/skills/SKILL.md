---
name: cli-anything-mubu
description: Use when Codex needs an installable `cli-anything-mubu` entrypoint for inspecting and operating the user's Mubu desktop workspace. Supports default REPL plus one-shot subcommands with `--json`.
---

# cli-anything-mubu

Use this packaged skill when the Mubu bridge has been installed and the preferred entrypoint is `cli-anything-mubu` rather than `python3 mubu_probe.py`.

This root path is now a compatibility wrapper. The canonical packaged source lives under:

- `agent-harness/mubu_probe.py`
- `agent-harness/cli_anything/mubu/...`

## Entry Points

- `cli-anything-mubu`
- `python -m cli_anything.mubu`

If no subcommand is given, the packaged CLI enters a simple REPL.

## Recommended Flow

```text
cli-anything-mubu
  ->
daily-current --json
  ->
daily-nodes --query '<anchor>' --json
  ->
update-text / create-child / delete-node --json
  ->
--execute
```

## Notes

- The canonical packaged CLI now lives under `agent-harness/cli_anything/mubu/...`
- The packaged REPL banner exposes the packaged skill path directly
- The packaged REPL persists `current-doc` and `current-node`
- `update-text` is live-verified
- `create-child` is live-verified through a reversible scratch cycle
- `delete-node` is live-verified through the same reversible scratch cycle
