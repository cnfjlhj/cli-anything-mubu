# Mubu Live Bridge Prototype

This project is a practical bridge between the user's local Mubu desktop session and an agent-oriented CLI. Its purpose is not export or migration. Its purpose is to let Codex inspect, search, navigate, and perform small atomic edits on the same Mubu workspace the user is already using.

The current prototype already supports:

- local read/search/navigation from Mubu desktop backups, RxDB metadata, and sync logs
- live node inspection from the authenticated desktop session
- one verified live update primitive: update the `text` or `note` field of an existing node
- one verified live create primitive: append or insert a child under an existing node
- one verified live delete primitive: remove an existing node or subtree by `node_id`
- an installable `cli-anything-mubu` entrypoint with default REPL behavior
- a Click-based grouped command surface aligned to CLI-Anything harness conventions
- a generated packaged `SKILL.md` driven from the canonical harness source

The project is intentionally conservative. Reads are broad. Writes are narrow, explicit, and dry-run by default.

## Source Layout

The project now has one canonical CLI-Anything-aligned source root and one compatibility layer.

Canonical source root:

- `agent-harness/mubu_probe.py`
- `agent-harness/cli_anything/mubu/...`

Compatibility entrypoints kept for local development:

- `mubu_probe.py`
- `cli_anything/mubu/...`

ASCII view:

```text
repo root
├── agent-harness/
│   ├── mubu_probe.py                 <- canonical implementation
│   └── cli_anything/mubu/...         <- canonical packaged source
├── mubu_probe.py                     <- compatibility shim
└── cli_anything/mubu/...             <- compatibility shims
```

That means future CLI-Anything alignment work should land in `agent-harness/` first, not in the root shims.

## Why This Exists

The target workflow is:

- list recent Mubu documents
- move into a known folder such as `Workspace/Daily tasks`
- open the current daily note
- inspect links and nodes
- let Codex make small synchronized edits instead of bulk rewrites

That means the CLI has to be agent-usable, not just human-usable.

## Capability Matrix

| Area | Command | Data source | Mutates state | Status |
|---|---|---|---|---|
| latest local docs | `docs` | backup snapshots | no | working |
| local doc tree by id | `show` | backup snapshots | no | working |
| local full-text search | `search` | backup snapshots | no | working |
| sync event inspection | `changes` | client-sync logs | no | working |
| folder listing | `folders` | RxDB `.storage` | no | working |
| docs under folder id | `folder-docs` | RxDB `.storage` | no | working |
| docs under folder path | `path-docs` | RxDB `.storage` | no | working |
| recent activity | `recent` | backups + metadata + logs | no | working |
| outbound Mubu links | `links` | backup snapshots | no | working |
| daily-note discovery | `daily` | RxDB `.storage` | no | working |
| current daily resolver | `daily-current` | RxDB `.storage` | no | working |
| current daily live nodes | `daily-nodes` | RxDB `.storage` + live `/document/get` | no | working |
| open by path/title/id | `open-path` | backups + metadata | no | working |
| live node enumeration | `doc-nodes` | live `/document/get` | no | working |
| live child creation | `create-child` | live `/colla/events` | yes | working |
| live node deletion | `delete-node` | live `/colla/events` | yes | working |
| live node text update | `update-text` | live `/colla/events` | yes | working |

## Architecture

The bridge currently has two planes:

1. a broad local read plane
2. a narrow live write plane

ASCII flow:

```text
                          +----------------------+
                          |  Mubu Desktop App    |
                          |  (user is using it)  |
                          +----------+-----------+
                                     |
                     +---------------+----------------+
                     |                                |
                     v                                v
         +------------------------+        +------------------------+
         | Local desktop profile  |        | Live authenticated API |
         |                        |        | https://api2.mubu.com  |
         +-----------+------------+        +-----------+------------+
                     |                                 |
     +---------------+---------------+      +----------+----------------------+
     |               |               |      |                                 |
     v               v               v      v                                 v
 backups/        RxDB .storage   sync logs  /v3/api/document/get      /v3/api/colla/events
 latest trees    folders/meta    memberId   baseVersion + definition  atomic CHANGE events
     |               |               |      |                                 |
     +---------------+---------------+      +---------------+-----------------+
                     |                                      |
                     v                                      v
               read/navigation                         inspect + mutate
                     \                                      /
                      \                                    /
                       +----------------------------------+
                       |        mubu_probe.py CLI         |
                       +----------------+-----------------+
                                        |
                                        v
                                   Codex / user
```

Write-path detail:

```text
1. load active user token/userId from local users store
2. resolve doc path -> doc_id from local metadata
3. read sync logs -> latest memberId for that doc
4. fetch live document -> get current baseVersion + definition
5. inspect nodes -> choose node_id/path/parent
6. build CHANGE payload
7. dry-run by default
8. only POST when --execute is present
9. re-fetch live document to verify result
```

## Safety Model

Current write safety rules:

- `create-child`, `delete-node`, and `update-text` are dry-run by default
- only `--execute` sends the live `CHANGE` request
- document targeting goes through full path or doc id resolution
- node targeting should prefer `--node-id`
- `--match-text` is available, but only safe when the text is unique in that document
- child creation should prefer `--parent-node-id`
- the CLI re-fetches the document after execute and reports whether the requested change is visible

Important caveat:

- even a same-text update still mutates document state
- real verification already showed that the document `baseVersion` increases even if the visible text stays unchanged
- delete operates on the full targeted node payload, so deleting a parent removes the whole subtree under it
- that means history / modified timestamps can move even for "no-op" semantic edits

## Current Command Surface

Quick reference:

```text
Grouped Click surface:
  discover docs
  discover folders
  discover folder-docs
  discover path-docs
  discover recent
  discover daily
  discover daily-current

  inspect show
  inspect search
  inspect changes
  inspect links
  inspect open-path
  inspect doc-nodes
  inspect daily-nodes

  mutate create-child
  mutate delete-node
  mutate update-text

  session status
  session state-path
  session use-doc
  session use-node
  session use-daily
  session clear-doc
  session clear-node
  session history

Legacy flat compatibility:
  docs
  show
  search
  changes
  folders
  folder-docs
  path-docs
  recent
  links
  daily
  daily-current
  daily-nodes
  open-path
  doc-nodes
  create-child
  delete-node
  update-text
```

Global conventions:

- grouped probe commands support root-level `--json`
- probe commands still support command-level `--json`
- folder and document references support ids and path-oriented lookup where implemented
- live commands require an active Mubu desktop session on this machine

Packaged entrypoints:

```text
cli-anything-mubu
python -m cli_anything.mubu
```

If no subcommand is given, the packaged CLI enters the REPL by default.

ASCII mode view:

```text
cli-anything-mubu
├── discover ...
├── inspect ...
├── mutate ...
├── session ...
└── repl / no-arg default

legacy flat commands
└── still accepted for compatibility
```

Current REPL state support:

- official-style startup banner with app version, skill path, and history path
- persisted current document selection across REPL sessions
- persisted current node selection across REPL sessions
- local command history persisted in session state
- `use-doc <doc_ref>`
- `use-node <node_id>`
- `use-daily`
- `current-doc`
- `current-node`
- `clear-doc`
- `clear-node`
- `status`
- `history [limit]`
- `@node` placeholder expansion inside subsequent commands
- `@doc` / `@current` placeholder expansion inside subsequent commands
- `state-path`

Session state storage:

- default: `~/.config/cli-anything-mubu/session.json`
- override with `CLI_ANYTHING_MUBU_STATE_DIR`
- REPL history file: `~/.config/cli-anything-mubu/history.txt`

## Recommended Codex Workflow

This is the workflow Codex should follow unless the user explicitly asks for something else.

```text
recent / daily-current / daily-nodes / folders / path-docs
        |
        v
     open-path
        |
        v
     doc-nodes
        |
        v
 create-child --json         (dry-run first)
        |
        v
 create-child --execute --json
        |
        v
 delete-node --json         (dry-run first when cleanup/removal is intended)
        |
        v
 delete-node --execute --json
        |
        v
 update-text --json          (dry-run first)
        |
        v
 update-text --execute --json
        |
        v
 verify returned baseVersion/node_text_after
```

Operational rules for Codex:

1. Prefer path-based document references such as `Workspace/Daily tasks/26.03.16`.
2. Prefer `daily-current` when the task is "go to today's daily note".
3. Prefer `daily-nodes` when the task is "find something inside today's daily note".
4. Prefer `doc-nodes` before any live edit outside the current daily shortcut.
5. Prefer `--node-id` over `--match-text`.
6. Prefer `--parent-node-id` over `--parent-match-text`.
7. Treat dry-run output as the source of truth for the exact outgoing payload.
8. Avoid repeated no-op writes, because they still advance version/history.
9. Do not casually execute `create-child` on a real personal note unless the new child is intentionally wanted.
10. Do not casually execute `delete-node` on a parent node unless removing the full subtree is intentional.
11. Keep mutations atomic. Do not simulate bulk refactors through many blind live calls.

## Real Examples

### 1. Find recent documents

```bash
python3 mubu_probe.py recent --limit 5 --json
```

Real result already showed documents such as:

- `doc-link-003` -> `Workspace`
- `doc-link-001` -> `Workspace`
- `doc-demo-01` -> `Workspace/Daily tasks/26.03.16`

### 2. List documents under the daily folder

```bash
python3 mubu_probe.py path-docs 'Workspace/Daily tasks' --limit 5 --json
```

Real result already resolved:

- folder id `folder-daily-01`
- current daily doc `doc-demo-01`
- path `Workspace/Daily tasks/26.03.16`

### 3. Resolve the current daily document in one step

```bash
python3 mubu_probe.py daily-current --json
```

Real result already resolved:

- folder path `Workspace/Daily tasks`
- current daily doc `doc-demo-01`
- current daily path `Workspace/Daily tasks/26.03.16`

The selection rule is:

- prefer date-like daily titles such as `26.03.16`
- exclude template-like titles such as `26.2.22模板更新`
- choose the most recently updated candidate

### 4. Enumerate live nodes before editing

```bash
python3 mubu_probe.py doc-nodes 'Workspace/Daily tasks/26.03.16' --query '日志流' --json
```

Real result:

- doc id `doc-demo-01`
- a current live `baseVersion`
- matched node id `node-demo1`
- target path `["nodes", 3, 0]`
- canonical API path `["nodes", 3, "children", 0]`

Note on path semantics:

- paths are index chains rooted at `nodes`
- child hops are represented by indices only
- example: `["nodes", 3, 0]` means the first child under the fourth top-level node
- `api_path` expands those child hops explicitly for event payloads
- example: `["nodes", 3, "children", 0]` is the same node in API form

### 4.5 Enumerate live nodes from the current daily note in one step

```bash
python3 mubu_probe.py daily-nodes --query '日志流' --json
```

Real result already resolved:

- current daily path `Workspace/Daily tasks/26.03.16`
- live node id `node-demo1`
- api path `["nodes", 3, "children", 0]`

### 5. Build a dry-run text update

```bash
python3 mubu_probe.py update-text \
  'Workspace/Daily tasks/26.03.16' \
  --node-id node-demo1 \
  --text '日志流' \
  --json
```

This does not mutate Mubu. It returns:

- resolved document info
- member context from sync logs
- target node info
- exact `/v3/api/colla/events` request payload

### 6. Execute a live update

```bash
python3 mubu_probe.py update-text \
  'Workspace/Daily tasks/26.03.16' \
  --match-text '日志流' \
  --text '日志流' \
  --execute \
  --json
```

This exact same-text update was already executed once to validate the end-to-end chain. The server returned success and the document version advanced from `256` to `257`, while the visible text remained `日志流`.

### 7. Build a dry-run child creation

```bash
python3 mubu_probe.py create-child \
  'Workspace/Daily tasks/26.03.16' \
  --parent-node-id node-demo1 \
  --text 'CLI bridge dry run child' \
  --note 'not executed' \
  --json
```

Real dry-run result already showed:

- parent node `node-demo1`
- existing child count `4`
- planned insert index `4`
- generated child path `["nodes", 3, "children", 0, "children", 4]`

This command is safe to inspect first and only execute on an intentionally chosen target.

### 8. Build a dry-run node deletion

```bash
python3 mubu_probe.py delete-node \
  'Workspace/Daily tasks/26.03.16' \
  --node-id node-demo1 \
  --json
```

This does not mutate Mubu. It returns:

- resolved document info
- member context from sync logs
- target node info including `parent_node_id`, `index`, and `api_path`
- the exact `delete` event payload that would be sent on execute

### 9. Real reversible E2E verification

The bridge has now been live-verified with a reversible scratch cycle:

```text
1. create-child --execute on a unique scratch child under 日志流
2. verify the scratch child is present
3. delete-node --execute on that exact new child id
4. verify the scratch child is gone
```

Observed real result:

- create advanced `baseVersion` from `261` to `262`
- delete advanced `baseVersion` from `262` to `263`
- the scratch node id `hUVCZEUf3R` was confirmed present after create
- the same scratch node was confirmed absent after delete

## Environment Assumptions

Default paths are auto-discovered from the current machine:

- preferred sources:
  `APPDATA`, `USERPROFILE`, or common WSL paths under `/mnt/c/Users/*/AppData/Roaming`
- default data root:
  `<appdata>/Mubu/mubu_app_data/mubu_data`
- derived backup root:
  `<appdata>/Mubu/mubu_app_data/mubu_data/backup`
- derived log root:
  `<appdata>/Mubu/mubu_app_data/mubu_data/log`
- derived storage root:
  `<appdata>/Mubu/mubu_app_data/mubu_data/.storage`
- API host:
  `https://api2.mubu.com`

Override variables if needed:

- `MUBU_BACKUP_ROOT`
- `MUBU_LOG_ROOT`
- `MUBU_STORAGE_ROOT`
- `MUBU_API_HOST`
- `MUBU_PLATFORM`
- `MUBU_PLATFORM_VERSION`

## Packaging And Install

This project now has a minimal installable package surface:

- `setup.py`
- namespace package `cli_anything.mubu`
- console script `cli-anything-mubu`
- packaged skill at `cli_anything/mubu/skills/SKILL.md`
- canonical harness install root at `agent-harness/`

Isolated install verified in:

- `.venv`

Project-root install command:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

CLI-Anything-style harness install command:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ./agent-harness
```

Verified packaged entrypoints:

```bash
.venv/bin/cli-anything-mubu --help
.venv/bin/cli-anything-mubu --json discover daily-current
.venv/bin/cli-anything-mubu session status --json
.venv/bin/cli-anything-mubu repl --help
printf 'exit\n' | .venv/bin/cli-anything-mubu
.venv/bin/cli-anything-mubu
  # then inside REPL:
  # use-doc 'Workspace/Daily tasks/26.03.16'
  # use-node node-demo1
  # status
  # history 5
.venv/bin/cli-anything-mubu
  # in a later invocation, current-doc and current-node are still available
.venv/bin/cli-anything-mubu daily-current --json
```

## CLI-Anything Alignment

This prototype now follows the major current CLI-Anything harness norms:

- canonical source now lives under `agent-harness/cli_anything/mubu/...`
- root and harness installs both target the same canonical source tree
- the main CLI is now Click-based with grouped command domains
- no-arg invocation enters the REPL through the main Click group
- grouped `discover` / `inspect` / `mutate` / `session` domains now exist
- legacy flat commands still work for compatibility
- root-level `--json` now works across grouped probe commands
- packaged `SKILL.md` is now generated from the canonical harness via `skill_generator.py`
- packaged `SKILL.md` is installed inside the Python package and exposed in the REPL banner
- session state is now a formal command group, not just REPL-only builtins
- test-plan and verification artifacts exist in-project
- installed command, editable installs, and wheel contents are all verified

Current remaining gaps versus a literal full HARNESS checklist:

- no safe semantic `undo` / `redo` primitive yet for live Mubu mutations
- no automated always-on live backend E2E suite yet; current real-session verification is still targeted and manual because it mutates personal notes

So the right framing is:

- this is already a useful agent-native Mubu bridge
- it is not yet a finished CLI-Anything productized plugin

## Known Risks

- local backups may lag behind the live document
- `doc-nodes`, `create-child`, `delete-node`, and `update-text` depend on valid local auth in the Mubu desktop profile
- `memberId` currently comes from recent sync logs for the same document
- all live mutation primitives still depend on the current `baseVersion` and a fresh member context from logs
- delete removes the full targeted subtree, not only visible plain text
- concurrent edits from the user can invalidate a stale target if too much time passes between inspect and execute

## Next Steps

Highest-value next additions:

1. add richer node selection helpers beyond exact `--match-text`
2. enrich the persisted REPL context beyond `current-doc` and `current-node`
3. move toward a stricter `agent-harness/cli_anything/mubu/...` layout
4. expand installed-entrypoint subprocess and live e2e verification
5. add move semantics only after the delete targeting model is hardened

## Short Operator Manual For Codex

If the user says "go into today's daily note and edit something", Codex should usually do this:

```text
Step A: path-docs 'Workspace/Daily tasks'
Step A0: or just use daily-current --json
Step A1: or use daily-nodes --query '<anchor text>' --json
Step B: open-path '<resolved doc path>'
Step C: doc-nodes '<resolved doc path>' --query '<anchor text>'
Step D1: create-child '<resolved doc path>' --parent-node-id <node_id> --text '<new child>' --json
Step D2: delete-node '<resolved doc path>' --node-id <node_id> --json
Step D3: update-text '<resolved doc path>' --node-id <node_id> --text '<new text>' --json
Step E: if the dry-run looks correct, repeat the chosen command with --execute
```

If the user is vague, Codex should prefer:

- `recent` for recency discovery
- `daily-current` for "today's daily note"
- `daily-nodes` for "find this anchor in today's daily note"
- `path-docs` for folder-scoped disambiguation
- `doc-nodes` for precise mutation targeting
- dry-run `create-child` for additive structure changes
- dry-run `delete-node` only when the exact node id is already known

If the user asks for large-scale edits, Codex should slow down and keep operations atomic instead of trying to fake a batch editor through repeated live updates.
