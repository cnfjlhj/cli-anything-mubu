---
name: mubu-live-bridge
description: Use when Codex needs to inspect, search, navigate, or perform small atomic edits inside the user's local Mubu desktop workspace through `mubu_probe.py`. Prefer this for near-real-time Daily tasks workflows, folder/path navigation, node targeting, and dry-run-first live mutations.
---

# Mubu Live Bridge

Use this skill when the user wants Codex to operate Mubu more like a first-party assistant than a file exporter.

## When To Use

Use this skill for tasks like:

- find the user's recent Mubu documents
- navigate by folder path such as `Workspace/Daily tasks`
- open the current daily note
- inspect nodes and links
- perform small atomic edits with low delay
- add one child node, delete one existing node, or update one existing node

Do not use this skill for:

- bulk export or migration
- large blind refactors across many notes
- destructive cleanup without a clearly chosen target

## Source Of Truth

The CLI lives here:

- canonical: `agent-harness/mubu_probe.py`
- compatibility shim: `mubu_probe.py`

Packaged entrypoint:

- `cli-anything-mubu`
- `python -m cli_anything.mubu`
- grouped Click domains:
  - `discover ...`
  - `inspect ...`
  - `mutate ...`
  - `session ...`

Operator manual:

- `README.md`

Test plan and results:

- `tests/TEST.md`
- canonical harness copy: `agent-harness/cli_anything/mubu/tests/TEST.md`

## Command Model

Read / inspect:

- `docs`
- `show`
- `search`
- `changes`
- `folders`
- `folder-docs`
- `path-docs`
- `recent`
- `links`
- `daily`
- `daily-current`
- `daily-nodes`
- `open-path`
- `doc-nodes`

Mutate:

- `create-child`
- `delete-node`
- `update-text`

Session / state:

- `session status`
- `session state-path`
- `session use-doc`
- `session use-node`
- `session use-daily`
- `session clear-doc`
- `session clear-node`
- `session history`

All operational commands should prefer `--json`.

## Default Workflow

```text
discover daily-current / inspect daily-nodes / discover path-docs
        ->
     inspect open-path
        ->
     inspect doc-nodes
        ->
 session use-doc / session use-node when useful
        ->
 dry-run mutate create-child / delete-node / update-text
        ->
 execute only if the dry-run payload matches intent
```

## Safety Rules

1. Use path-based doc references when possible.
2. Always inspect with `doc-nodes` before a live mutation.
3. Prefer `--node-id` or `--parent-node-id` over text matching.
4. Treat dry-run output as the exact contract for what will be sent.
5. `create-child` leaves a visible artifact in the user's note; do not execute casually.
6. `delete-node` removes the full targeted subtree, not just visible plain text.
7. Even same-text `update-text` calls still change version/history.

## Recommended Commands

Find the current daily note:

```bash
python3 mubu_probe.py daily-current --json
```

Inspect candidate nodes:

```bash
python3 mubu_probe.py daily-nodes --query '日志流' --json
```

Dry-run a child creation:

```bash
python3 mubu_probe.py create-child 'Workspace/Daily tasks/26.03.16' --parent-node-id node-demo1 --text 'new child' --json
```

Dry-run a text update:

```bash
python3 mubu_probe.py update-text 'Workspace/Daily tasks/26.03.16' --node-id node-demo1 --text 'new text' --json
```

Dry-run a node deletion:

```bash
python3 mubu_probe.py delete-node 'Workspace/Daily tasks/26.03.16' --node-id node-demo1 --json
```

## Current Limits

- `update-text` is live-verified
- `create-child` is live-verified through a reversible scratch cycle
- `delete-node` is live-verified through the same reversible scratch cycle
- there is now a packaged default REPL with persisted `current-doc` and `current-node` context
- there is now a formal session/state command group with persisted command history
- the packaged REPL banner exposes the packaged skill path directly
- the packaged canonical source now lives under `agent-harness/cli_anything/mubu/...`
- the packaged `SKILL.md` is now generated from `agent-harness/skill_generator.py`
- there is still no live semantic `undo` / `redo` primitive yet
