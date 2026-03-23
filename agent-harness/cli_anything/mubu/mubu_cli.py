from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence

import click

import mubu_probe
from cli_anything.mubu import __version__
from cli_anything.mubu.utils import ReplSkin


CONTEXT_SETTINGS = {"ignore_unknown_options": True, "allow_extra_args": True}
COMMAND_HISTORY_LIMIT = 50
PUBLIC_PROGRAM_NAME = "mubu-cli"
COMPAT_PROGRAM_NAME = "cli-anything-mubu"
DISCOVER_COMMANDS = {
    "docs": "List latest known document snapshots from local backups.",
    "folders": "List folder metadata from local RxDB storage.",
    "folder-docs": "List document metadata for one folder.",
    "path-docs": "List documents for one folder path or folder id.",
    "recent": "List recently active documents using backups, metadata, and sync logs.",
    "daily": "Find Daily-style folders and list the documents inside them.",
    "daily-current": "Resolve the current daily document from one Daily-style folder.",
}
INSPECT_COMMANDS = {
    "show": "Show the latest backup tree for one document.",
    "search": "Search latest backups for matching node text or note content.",
    "changes": "Parse recent client-sync change events from local logs.",
    "links": "Extract outbound Mubu document links from one document backup.",
    "open-path": "Open one document by full path, suffix path, title, or doc id.",
    "doc-nodes": "List live document nodes with node ids and update-target paths.",
    "daily-nodes": "List live nodes from the current daily document in one step.",
}
MUTATE_COMMANDS = {
    "create-child": "Build or execute one child-node creation against the live Mubu API.",
    "delete-node": "Build or execute one node deletion against the live Mubu API.",
    "update-text": "Build or execute one text update against the live Mubu API.",
}
WORKFLOW_COMMANDS = {
    "daily-open": "Resolve the current daily document and persist it as the active workflow document.",
    "today-start": "Create or open today's daily document from the latest dated template panel.",
    "today-scan": "Scan the latest daily document and extract today's actionable sections.",
    "pick": "Select one live node in the active document and persist it as the current workflow node.",
    "ctx": "Show focused live context for the current node, including parent, siblings, and children.",
    "append": "Append one child under the current node using the dry-run-first live mutation flow.",
    "capture": "Capture one child into the current daily or current document in one step.",
}
LEGACY_COMMANDS = {}
LEGACY_COMMANDS.update(DISCOVER_COMMANDS)
LEGACY_COMMANDS.update(INSPECT_COMMANDS)
LEGACY_COMMANDS.update(MUTATE_COMMANDS)
REPL_WORKFLOW_SHORTCUTS = {"daily-open", "today-start", "today-scan", "pick", "ctx", "append", "capture"}

REPL_HELP_TEMPLATE = """Interactive REPL for {program_name}

Builtins:
  help              Show this REPL help
  exit, quit        Leave the REPL
  use-doc <ref>     Set the current document reference for this REPL session
  use-node <id>     Set the current node reference for this REPL session
  use-daily [ref]   Resolve and set the current daily document
  current-doc       Show the current document reference
  current-node      Show the current node reference
  clear-doc         Clear the current document reference
  clear-node        Clear the current node reference
  status            Show the current session status
  history [limit]   Show recent command history from session state
  state-path        Show the session state file path

Examples:
  recent --limit 5 --json
  discover daily-current '<daily-folder-ref>'
  discover daily-current --json '<daily-folder-ref>'
  inspect daily-nodes '<daily-folder-ref>' --query '<anchor>' --json
  workflow daily-open '<daily-folder-ref>' --json
  workflow today-start '<daily-folder-ref>' --json
  workflow today-scan '<daily-folder-ref>' --json
  workflow pick --query '日志流' --json
  workflow ctx --json
  workflow append --text '继续推进' --json
  workflow capture --daily --daily-folder '<daily-folder-ref>' --query 'Inbox' --text '记录一下' --json
  session use-doc '<doc-ref>'
  mutate create-child @doc --parent-node-id <node-id> --text 'scratch child' --json
  mutate delete-node @doc --node-id @node --json
  update-text '<doc-ref>' --node-id <node-id> --text 'new text' --json

If you prefer no-argument daily helpers, set MUBU_DAILY_FOLDER='<daily-folder-ref>'.
"""
REPL_COMMAND_HELP = REPL_HELP_TEMPLATE.format(program_name="the Mubu CLI")
REPL_HELP = REPL_COMMAND_HELP


def normalize_program_name(program_name: str | None) -> str:
    candidate = Path(program_name or "").name.strip()
    if candidate == PUBLIC_PROGRAM_NAME:
        return PUBLIC_PROGRAM_NAME
    return COMPAT_PROGRAM_NAME


def repl_help_text(program_name: str | None = None) -> str:
    return REPL_HELP_TEMPLATE.format(program_name=normalize_program_name(program_name))


def session_state_dir() -> Path:
    override = os.environ.get("CLI_ANYTHING_MUBU_STATE_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    config_root = Path.home() / ".config"
    public_dir = config_root / PUBLIC_PROGRAM_NAME
    legacy_dir = config_root / COMPAT_PROGRAM_NAME
    if public_dir.exists():
        return public_dir
    if legacy_dir.exists():
        return legacy_dir
    return public_dir


def session_state_path() -> Path:
    return session_state_dir() / "session.json"


def default_session_state() -> dict[str, object]:
    return {
        "current_doc": None,
        "current_node": None,
        "command_history": [],
    }


def load_session_state() -> dict[str, object]:
    path = session_state_path()
    try:
        data = json.loads(path.read_text(errors="replace"))
    except FileNotFoundError:
        return default_session_state()
    except json.JSONDecodeError:
        return default_session_state()

    history = data.get("command_history")
    normalized_history = [item for item in history if isinstance(item, str)] if isinstance(history, list) else []
    return {
        "current_doc": data.get("current_doc") if isinstance(data.get("current_doc"), str) else None,
        "current_node": data.get("current_node") if isinstance(data.get("current_node"), str) else None,
        "command_history": normalized_history[-COMMAND_HISTORY_LIMIT:],
    }


def locked_save_json(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = open(path, "r+")
    except FileNotFoundError:
        handle = open(path, "w")
    with handle:
        locked = False
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            locked = True
        except (ImportError, OSError):
            pass
        try:
            handle.seek(0)
            handle.truncate()
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.flush()
        finally:
            if locked:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def save_session_state(session: dict[str, object]) -> None:
    locked_save_json(
        session_state_path(),
        {
            "current_doc": session.get("current_doc"),
            "current_node": session.get("current_node"),
            "command_history": list(session.get("command_history", [])),
        },
    )


def joined_text(values: Sequence[str] | None) -> str | None:
    if not values:
        return None
    value = " ".join(values).strip()
    return value or None


def append_command_history(command_line: str) -> None:
    command_line = command_line.strip()
    if not command_line:
        return
    session = load_session_state()
    history = list(session.get("command_history", []))
    history.append(command_line)
    session["command_history"] = history[-COMMAND_HISTORY_LIMIT:]
    save_session_state(session)


def resolve_current_daily_doc_ref(folder_ref: str | None = None) -> str:
    resolved_folder_ref = mubu_probe.resolve_daily_folder_ref(folder_ref)
    metas = mubu_probe.load_document_metas(mubu_probe.DEFAULT_STORAGE_ROOT)
    folders = mubu_probe.load_folders(mubu_probe.DEFAULT_STORAGE_ROOT)
    docs, folder, ambiguous = mubu_probe.folder_documents(metas, folders, resolved_folder_ref)
    if folder is None:
        if ambiguous:
            raise RuntimeError(mubu_probe.ambiguous_error_message("folder", resolved_folder_ref, ambiguous, "path"))
        raise RuntimeError(f"folder not found: {resolved_folder_ref}")
    selected, _ = mubu_probe.choose_current_daily_document(docs)
    if selected is None or not selected.get("doc_path"):
        raise RuntimeError(f"no current daily document found in {folder['path']}")
    return str(selected["doc_path"])


def resolve_daily_folder_documents(
    folder_ref: str | None = None,
) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    resolved_folder_ref = mubu_probe.resolve_daily_folder_ref(folder_ref)
    metas = mubu_probe.load_document_metas(mubu_probe.DEFAULT_STORAGE_ROOT)
    folders = mubu_probe.load_folders(mubu_probe.DEFAULT_STORAGE_ROOT)
    docs, folder, ambiguous = mubu_probe.folder_documents(metas, folders, resolved_folder_ref)
    if folder is None:
        if ambiguous:
            raise RuntimeError(mubu_probe.ambiguous_error_message("folder", resolved_folder_ref, ambiguous, "path"))
        raise RuntimeError(f"folder not found: {resolved_folder_ref}")
    return resolved_folder_ref, docs, folder


def summarize_document_meta(doc: dict[str, Any]) -> dict[str, Any]:
    parsed_date = mubu_probe.parse_daily_title_date(doc.get("title"))
    return {
        "doc_id": doc.get("doc_id"),
        "title": doc.get("title"),
        "doc_path": doc.get("doc_path"),
        "folder_id": doc.get("folder_id"),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
        "parsed_date": parsed_date.isoformat() if parsed_date else None,
    }


def require_current_doc_ref(explicit_doc_ref: str | None = None) -> str:
    if explicit_doc_ref:
        return explicit_doc_ref
    session = load_session_state()
    current_doc = session.get("current_doc")
    if isinstance(current_doc, str) and current_doc.strip():
        return current_doc
    raise click.ClickException("no current document set; pass a document reference or run `workflow daily-open` first")


def require_current_node_ref(explicit_node_ref: str | None = None) -> str:
    if explicit_node_ref:
        return explicit_node_ref
    session = load_session_state()
    current_node = session.get("current_node")
    if isinstance(current_node, str) and current_node.strip():
        return current_node
    raise click.ClickException("no current node set; pass --node-id or run `workflow pick` first")


def resolve_live_document_context(
    doc_ref: str,
    api_host: str = mubu_probe.DEFAULT_API_HOST,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    user = mubu_probe.get_active_user(mubu_probe.DEFAULT_STORAGE_ROOT)
    if user is None:
        raise click.ClickException("no active user auth found in local storage")

    metas = mubu_probe.load_document_metas(mubu_probe.DEFAULT_STORAGE_ROOT)
    folders = mubu_probe.load_folders(mubu_probe.DEFAULT_STORAGE_ROOT)
    meta, ambiguous = mubu_probe.resolve_document_reference(metas, folders, doc_ref)
    remote_doc: dict[str, Any] | None = None
    if meta is None:
        if ambiguous:
            raise click.ClickException(mubu_probe.ambiguous_error_message("document", doc_ref, ambiguous, "doc_path"))
        raw_doc_id = doc_ref.strip()
        if "/" not in raw_doc_id and raw_doc_id:
            remote_doc = mubu_probe.fetch_document_remote(raw_doc_id, user, api_host=api_host)
            meta = {
                "doc_id": raw_doc_id,
                "title": None,
                "doc_path": raw_doc_id,
            }
        else:
            raise click.ClickException(f"document not found: {doc_ref}")

    if remote_doc is None:
        remote_doc = mubu_probe.fetch_document_remote(meta["doc_id"], user, api_host=api_host)
    definition_raw = remote_doc.get("definition")
    if not isinstance(definition_raw, str):
        raise click.ClickException(f"document definition missing for: {meta['doc_id']}")
    try:
        definition = json.loads(definition_raw)
    except json.JSONDecodeError as exc:
        raise click.ClickException(f"document definition is not valid JSON for: {meta['doc_id']}") from exc
    return meta, user, remote_doc, definition


def summarize_node(node: dict[str, Any], path: Iterable[Any]) -> dict[str, Any]:
    tuple_path = tuple(path)
    modified = node.get("modified") if isinstance(node.get("modified"), int) else None
    children = node.get("children") or []
    child_count = len(children) if isinstance(children, list) else 0
    return {
        "node_id": node.get("id"),
        "path": list(tuple_path),
        "api_path": mubu_probe.node_path_to_api_path(tuple_path),
        "text": mubu_probe.extract_plain_text(node.get("text")),
        "note": mubu_probe.extract_plain_text(node.get("note")),
        "child_count": child_count,
        "modified": modified,
        "modified_at_iso": mubu_probe.timestamp_ms_to_iso(modified),
    }


def resolve_node_or_fail(
    definition: dict[str, Any],
    node_id: str,
    field: str = "text",
) -> tuple[dict[str, Any], tuple[Any, ...]]:
    node, path, ambiguous = mubu_probe.resolve_node_reference_in_data(definition, node_id=node_id, field=field)
    if node is None or path is None:
        if ambiguous:
            labels = [mubu_probe.extract_plain_text(item["node"].get(field)) for item in ambiguous[:5]]
            raise click.ClickException(f"ambiguous node reference: {labels}")
        raise click.ClickException(f"node not found: {node_id}")
    return node, tuple(path)


def resolve_query_node_or_fail(
    definition: dict[str, Any],
    query_text: str,
    index: int | None = None,
) -> tuple[dict[str, Any], tuple[Any, ...], int]:
    matches = mubu_probe.list_document_nodes(definition, query=query_text)
    if not matches:
        raise click.ClickException(f"no nodes matched query: {query_text}")
    if len(matches) > 1 and index is None:
        labels = [f"{idx}. {item.get('node_id')} {item.get('text') or ''}".rstrip() for idx, item in enumerate(matches[:5], start=1)]
        raise click.ClickException(
            f"query matched {len(matches)} nodes; rerun with --index N. Candidates: {' | '.join(labels)}"
        )
    if index is not None:
        if index < 1 or index > len(matches):
            raise click.ClickException(f"pick index out of range: {index} (match_count={len(matches)})")
        selected = matches[index - 1]
    else:
        selected = matches[0]
    node, path = resolve_node_or_fail(definition, node_id=str(selected["node_id"]))
    return node, path, len(matches)


def build_context_payload(
    definition: dict[str, Any],
    target_node: dict[str, Any],
    target_path: tuple[Any, ...],
    siblings_limit: int,
    children_limit: int,
) -> dict[str, Any]:
    parent_node, parent_path, sibling_index = mubu_probe.parent_context_for_path(definition, target_path)
    ancestors: list[dict[str, Any]] = []
    for end in range(2, len(target_path)):
        ancestor_path = tuple(target_path[:end])
        ancestor_node = mubu_probe.resolve_node_at_path(definition, ancestor_path)
        if ancestor_node is not None:
            ancestors.append(summarize_node(ancestor_node, ancestor_path))

    if parent_node is None:
        siblings = definition.get("nodes") or []
        parent_payload = None
        sibling_path_prefix = ("nodes",)
    else:
        siblings = parent_node.get("children") or []
        parent_payload = summarize_node(parent_node, parent_path or ())
        sibling_path_prefix = tuple(parent_path or ())
    if not isinstance(siblings, list):
        siblings = []

    before_start = max(0, sibling_index - siblings_limit)
    previous_siblings = [
        summarize_node(node, (*sibling_path_prefix, idx))
        for idx, node in enumerate(siblings[before_start:sibling_index], start=before_start)
    ]
    after_end = sibling_index + 1 + siblings_limit
    next_siblings = [
        summarize_node(node, (*sibling_path_prefix, idx))
        for idx, node in enumerate(siblings[sibling_index + 1:after_end], start=sibling_index + 1)
    ]

    children = target_node.get("children") or []
    if not isinstance(children, list):
        children = []
    child_payload = [
        summarize_node(node, (*target_path, idx))
        for idx, node in enumerate(children[:children_limit])
    ]

    return {
        "target": summarize_node(target_node, target_path),
        "parent": parent_payload,
        "ancestors": ancestors,
        "siblings_before": previous_siblings,
        "siblings_after": next_siblings,
        "children": child_payload,
    }


TODAY_SCAN_ROOT_LABELS = (
    "记录-今天做了啥（计划做啥）",
    "记录-今天做了啥(计划做啥)",
)
TODAY_SCAN_TASK_ROOT_LABELS = ("日志流",)
TODAY_SCAN_SECTION_SPECS = (
    ("main", ("主线（最多三条）", "主线（最多3条）", "主线")),
    ("todo", ("todo", "to do", "待办")),
    ("ing", ("ing", "doing", "进行中")),
)
TODAY_SCAN_FALLBACK_SECTION_SPECS = (
    ("ddl", ("DDL表(To Do List)", "DDL表", "To Do List")),
)


def normalized_text(value: str | None) -> str:
    return mubu_probe.normalized_lookup_key(value or "")


def text_matches_any_label(text: str | None, labels: Sequence[str]) -> bool:
    normalized = normalized_text(text)
    return any(normalized == normalized_text(label) for label in labels)


def iter_child_nodes_with_paths(
    node: dict[str, Any],
    path: tuple[Any, ...],
) -> Iterable[tuple[dict[str, Any], tuple[Any, ...]]]:
    children = node.get("children") or []
    if not isinstance(children, list):
        return
    for index, child in enumerate(children):
        yield child, (*path, index)


def find_exact_child_node(
    parent_node: dict[str, Any],
    parent_path: tuple[Any, ...],
    labels: Sequence[str],
) -> tuple[dict[str, Any] | None, tuple[Any, ...] | None]:
    for child, child_path in iter_child_nodes_with_paths(parent_node, parent_path):
        if text_matches_any_label(mubu_probe.extract_plain_text(child.get("text")), labels):
            return child, child_path
    return None, None


def find_exact_global_node(
    definition: dict[str, Any],
    labels: Sequence[str],
) -> tuple[dict[str, Any] | None, tuple[Any, ...] | None]:
    matches: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    for path, node in mubu_probe.iter_nodes(definition.get("nodes", [])):
        if text_matches_any_label(mubu_probe.extract_plain_text(node.get("text")), labels):
            matches.append((("nodes", *path), node))
    if not matches:
        return None, None
    matches.sort(key=lambda item: (len(item[0]), list(item[0])))
    selected_path, selected_node = matches[0]
    return selected_node, selected_path


def build_today_scan_section(
    name: str,
    anchor_node: dict[str, Any],
    anchor_path: tuple[Any, ...],
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for child, child_path in iter_child_nodes_with_paths(anchor_node, anchor_path):
        item = summarize_node(child, child_path)
        if not (str(item.get("text") or "").strip() or str(item.get("note") or "").strip()):
            continue
        items.append(item)
    return {
        "name": name,
        "label": mubu_probe.extract_plain_text(anchor_node.get("text")),
        "anchor": summarize_node(anchor_node, anchor_path),
        "items": items,
    }


def build_today_scan_payload(
    meta: dict[str, Any],
    definition: dict[str, Any],
    resolved_folder_ref: str,
    session_state: dict[str, object],
) -> dict[str, Any]:
    today_root_node, today_root_path = find_exact_global_node(definition, TODAY_SCAN_ROOT_LABELS)
    task_root_node: dict[str, Any] | None = None
    task_root_path: tuple[Any, ...] | None = None
    if today_root_node is not None and today_root_path is not None:
        task_root_node, task_root_path = find_exact_child_node(
            today_root_node,
            today_root_path,
            TODAY_SCAN_TASK_ROOT_LABELS,
        )
    if task_root_node is None or task_root_path is None:
        task_root_node, task_root_path = find_exact_global_node(definition, TODAY_SCAN_TASK_ROOT_LABELS)

    sections: list[dict[str, Any]] = []
    global_fallback_used = False
    for name, labels in TODAY_SCAN_SECTION_SPECS:
        anchor_node: dict[str, Any] | None = None
        anchor_path: tuple[Any, ...] | None = None
        if task_root_node is not None and task_root_path is not None:
            anchor_node, anchor_path = find_exact_child_node(task_root_node, task_root_path, labels)
        if anchor_node is None and today_root_node is not None and today_root_path is not None:
            anchor_node, anchor_path = find_exact_child_node(today_root_node, today_root_path, labels)
        if anchor_node is None or anchor_path is None:
            anchor_node, anchor_path = find_exact_global_node(definition, labels)
            global_fallback_used = global_fallback_used or anchor_node is not None
        if anchor_node is None or anchor_path is None:
            continue
        sections.append(build_today_scan_section(name, anchor_node, anchor_path))

    if not sections:
        for name, labels in TODAY_SCAN_FALLBACK_SECTION_SPECS:
            anchor_node, anchor_path = find_exact_global_node(definition, labels)
            if anchor_node is None or anchor_path is None:
                continue
            sections.append(build_today_scan_section(name, anchor_node, anchor_path))
            global_fallback_used = True

    actionable_total = sum(len(section.get("items", [])) for section in sections)
    return {
        "resolved_folder_ref": resolved_folder_ref,
        "document": {
            "doc_id": meta["doc_id"],
            "title": meta.get("title"),
            "doc_path": meta.get("doc_path"),
        },
        "strategy": {
            "today_root": summarize_node(today_root_node, today_root_path) if today_root_node and today_root_path else None,
            "task_root": summarize_node(task_root_node, task_root_path) if task_root_node and task_root_path else None,
            "global_fallback_used": global_fallback_used,
            "actionable_total": actionable_total,
        },
        "sections": sections,
        "current_doc": session_state.get("current_doc"),
        "current_node": session_state.get("current_node"),
        "state_path": str(session_state_path()),
    }


def build_pick_candidates_payload(
    meta: dict[str, Any],
    query_text: str,
    matches: Sequence[dict[str, Any]],
    session_state: dict[str, object],
) -> dict[str, Any]:
    return {
        "document": {
            "doc_id": meta["doc_id"],
            "title": meta.get("title"),
            "doc_path": meta.get("doc_path"),
        },
        "query": query_text,
        "match_count": len(matches),
        "candidates": list(matches),
        "current_doc": session_state.get("current_doc"),
        "current_node": session_state.get("current_node"),
        "state_path": str(session_state_path()),
    }


def emit_workflow_result(payload: dict[str, Any], json_output: bool) -> None:
    if json_output:
        emit_json(payload)
        return

    sections = payload.get("sections")
    if isinstance(sections, list):
        document = payload.get("document") if isinstance(payload.get("document"), dict) else {}
        strategy = payload.get("strategy") if isinstance(payload.get("strategy"), dict) else {}
        click.echo(f"Doc: {document.get('doc_path') or document.get('doc_id')}")
        click.echo(f"Actionable total: {strategy.get('actionable_total') or 0}")
        if not sections:
            click.echo("No actionable task sections found.")
            return
        for section in sections:
            if not isinstance(section, dict):
                continue
            items = section.get("items") if isinstance(section.get("items"), list) else []
            click.echo(f"[{section.get('name')}] {section.get('label')} ({len(items)})")
            for index, item in enumerate(items, start=1):
                if not isinstance(item, dict):
                    continue
                line = f"  {index}. {item.get('text') or item.get('node_id')}"
                note = item.get("note")
                if isinstance(note, str) and note.strip():
                    line += f" :: {note.strip()}"
                click.echo(line)
        return

    candidates = payload.get("candidates")
    if isinstance(candidates, list):
        click.echo(f"Current doc: {payload.get('current_doc')}")
        click.echo(f"Current node: {payload.get('current_node') or '<unset>'}")
        click.echo(f"Match count: {payload.get('match_count')}")
        for index, item in enumerate(candidates, start=1):
            click.echo(f"{index}. {item.get('node_id')} {item.get('text') or ''}".rstrip())
        return

    target = payload.get("target")
    if isinstance(target, dict):
        click.echo(f"Target: {target.get('node_id')} {target.get('text') or ''}".rstrip())
        click.echo(
            f"Parent: {(payload.get('parent') or {}).get('node_id') if isinstance(payload.get('parent'), dict) else '<root>'}"
        )
        click.echo(f"Siblings before: {len(payload.get('siblings_before') or [])}")
        click.echo(f"Siblings after: {len(payload.get('siblings_after') or [])}")
        click.echo(f"Children shown: {len(payload.get('children') or [])}")
        return

    selected = payload.get("selected")
    if isinstance(selected, dict):
        click.echo(f"Current doc: {payload.get('current_doc')}")
        click.echo(f"Current node: {payload.get('current_node')}")
        click.echo(f"Picked: {selected.get('text') or selected.get('node_id')}")
        return

    if payload.get("resolved_folder_ref"):
        click.echo(f"Current doc: {payload.get('current_doc')}")
        click.echo(f"Resolved daily folder: {payload.get('resolved_folder_ref')}")
        return

    if payload.get("new_child"):
        click.echo(f"Parent node: {(payload.get('target_parent') or {}).get('node_id')}")
        click.echo(f"New child: {(payload.get('new_child') or {}).get('node_id')}")
        click.echo(f"Execute: {payload.get('execute')}")
        return

    click.echo(json.dumps(payload, ensure_ascii=False, indent=2))


def append_history_entry(prefix: str, *parts: str | None) -> None:
    tokens = [prefix, *[part for part in parts if part]]
    append_command_history(" ".join(tokens))


def expand_repl_aliases(argv: list[str], current_doc: str | None) -> list[str]:
    return expand_repl_aliases_with_state(argv, {"current_doc": current_doc, "current_node": None})


def expand_repl_aliases_with_state(argv: list[str], session: dict[str, object]) -> list[str]:
    current_doc = session.get("current_doc")
    current_node = session.get("current_node")
    expanded: list[str] = []
    for token in argv:
        if token in {"@doc", "@current"} and isinstance(current_doc, str):
            expanded.append(current_doc)
        elif token == "@node" and isinstance(current_node, str):
            expanded.append(current_node)
        else:
            expanded.append(token)
    return expanded


def build_session_payload(session: dict[str, object]) -> dict[str, object]:
    history = list(session.get("command_history", []))
    return {
        "current_doc": session.get("current_doc"),
        "current_node": session.get("current_node"),
        "state_path": str(session_state_path()),
        "history_count": len(history),
    }


def root_json_output(ctx: click.Context | None) -> bool:
    if ctx is None:
        return False
    root = ctx.find_root()
    if root is None or root.obj is None:
        return False
    return bool(root.obj.get("json_output"))


def emit_json(payload: object) -> None:
    click.echo(json.dumps(payload, ensure_ascii=False, indent=2))


def run_packaged_verify(argv: Sequence[str]) -> int:
    from cli_anything.mubu.verification import main as verify_main

    return int(verify_main(list(argv)))


def path_check_payload(path: Path) -> dict[str, object]:
    return {
        "ok": path.exists(),
        "path": str(path),
    }


def build_doctor_report(daily_folder_ref: str | None = None) -> dict[str, object]:
    backup_root = mubu_probe.DEFAULT_BACKUP_ROOT
    storage_root = mubu_probe.DEFAULT_STORAGE_ROOT
    log_root = mubu_probe.DEFAULT_LOG_ROOT
    session_dir = session_state_dir()
    session_parent = session_dir if session_dir.exists() else session_dir.parent
    active_user = mubu_probe.get_active_user(mubu_probe.DEFAULT_STORAGE_ROOT)
    session = load_session_state()

    checks: dict[str, dict[str, object]] = {
        "backup_root": path_check_payload(backup_root),
        "storage_root": path_check_payload(storage_root),
        "log_root": path_check_payload(log_root),
        "session_dir": {
            "ok": session_parent.exists(),
            "path": str(session_dir),
        },
        "active_user": {
            "ok": active_user is not None,
            "user_id": (active_user or {}).get("user_id"),
            "display_name": (active_user or {}).get("display_name"),
        },
    }

    try:
        resolved_folder_ref = mubu_probe.resolve_daily_folder_ref(daily_folder_ref)
        resolved_doc_ref = resolve_current_daily_doc_ref(resolved_folder_ref)
        checks["daily_folder"] = {
            "ok": True,
            "resolved_folder_ref": resolved_folder_ref,
            "resolved_doc_ref": resolved_doc_ref,
        }
    except RuntimeError as exc:
        checks["daily_folder"] = {
            "ok": False,
            "resolved_folder_ref": daily_folder_ref or mubu_probe.configured_daily_folder_ref(),
            "error": str(exc),
        }

    overall_ok = all(bool(item.get("ok")) for item in checks.values())
    return {
        "ok": overall_ok,
        "program": PUBLIC_PROGRAM_NAME,
        "checks": checks,
        "session": build_session_payload(session),
    }


def emit_doctor_report(payload: dict[str, object], json_output: bool) -> None:
    if json_output:
        emit_json(payload)
        return

    for name, details in payload.get("checks", {}).items():
        if not isinstance(details, dict):
            continue
        status = "PASS" if details.get("ok") else "FAIL"
        path = details.get("path")
        if path:
            click.echo(f"[{status}] {name}: {path}")
            continue
        if name == "active_user":
            user_id = details.get("user_id") or "<missing>"
            display_name = details.get("display_name") or ""
            click.echo(f"[{status}] {name}: {user_id} {display_name}".rstrip())
            continue
        if name == "daily_folder":
            if details.get("ok"):
                click.echo(
                    f"[PASS] {name}: {details.get('resolved_folder_ref')} -> {details.get('resolved_doc_ref')}"
                )
            else:
                click.echo(f"[FAIL] {name}: {details.get('error')}")
            continue
        click.echo(f"[{status}] {name}")
    click.echo(f"Current doc: {payload.get('session', {}).get('current_doc') or '<unset>'}")
    click.echo(f"Current node: {payload.get('session', {}).get('current_node') or '<unset>'}")
    click.echo(f"State path: {payload.get('session', {}).get('state_path')}")
    click.echo(f"Overall: {'PASS' if payload.get('ok') else 'FAIL'}")


def emit_session_status(session: dict[str, object], json_output: bool) -> None:
    payload = build_session_payload(session)
    if json_output:
        emit_json(payload)
        return
    current_doc = payload["current_doc"] or "<unset>"
    current_node = payload["current_node"] or "<unset>"
    click.echo(f"Current doc: {current_doc}")
    click.echo(f"Current node: {current_node}")
    click.echo(f"State path: {payload['state_path']}")
    click.echo(f"History count: {payload['history_count']}")


def emit_session_history(session: dict[str, object], limit: int, json_output: bool) -> None:
    history = list(session.get("command_history", []))[-limit:]
    if json_output:
        emit_json({"history": history})
        return
    if not history:
        click.echo("History: <empty>")
        return
    click.echo("History:")
    for index, entry in enumerate(history, start=max(1, len(history) - limit + 1)):
        click.echo(f"  {index}. {entry}")


def invoke_probe_command(ctx: click.Context | None, command_name: str, probe_args: Sequence[str]) -> int:
    argv = [command_name, *list(probe_args)]
    if root_json_output(ctx) and "--json" not in argv:
        argv.append("--json")
    try:
        result = mubu_probe.main(argv)
    except SystemExit as exc:
        result = exc.code if isinstance(exc.code, int) else 1
    if result in (0, None) and "--help" not in argv and "-h" not in argv:
        append_command_history(" ".join(argv))
    return int(result or 0)


def print_repl_banner(skin: ReplSkin, program_name: str | None = None) -> None:
    normalized_program_name = normalize_program_name(program_name)
    click.echo("Mubu REPL")
    if normalized_program_name == PUBLIC_PROGRAM_NAME:
        click.echo(f"Command: {PUBLIC_PROGRAM_NAME}")
        click.echo(f"Version: {__version__}")
        if skin.skill_path:
            click.echo(f"Skill: {skin.skill_path}")
        click.echo("Type help for commands, quit to exit")
        click.echo()
    else:
        skin.print_banner()
    click.echo(f"History: {skin.history_file}")


def print_repl_help(program_name: str | None = None) -> None:
    click.echo(repl_help_text(program_name).rstrip())


def parse_history_limit(argv: Sequence[str]) -> int:
    if len(argv) < 2:
        return 10
    try:
        return max(1, int(argv[1]))
    except ValueError as exc:
        raise RuntimeError(f"history limit must be an integer: {argv[1]}") from exc


def handle_repl_builtin(
    argv: list[str],
    session: dict[str, object],
    program_name: str | None = None,
) -> tuple[bool, int]:
    if not argv:
        return True, 0

    command = argv[0]
    if command in {"exit", "quit"}:
        return True, 1
    if command == "help":
        print_repl_help(program_name)
        return True, 0
    if command == "current-doc":
        current_doc = session.get("current_doc")
        click.echo(f"Current doc: {current_doc}" if current_doc else "Current doc: <unset>")
        return True, 0
    if command == "current-node":
        current_node = session.get("current_node")
        click.echo(f"Current node: {current_node}" if current_node else "Current node: <unset>")
        return True, 0
    if command == "status":
        emit_session_status(session, json_output=False)
        return True, 0
    if command == "history":
        try:
            limit = parse_history_limit(argv)
        except RuntimeError as exc:
            click.echo(str(exc), err=True)
            return True, 0
        emit_session_history(session, limit, json_output=False)
        return True, 0
    if command == "state-path":
        click.echo(f"State path: {session_state_path()}")
        return True, 0
    if command == "clear-doc":
        session["current_doc"] = None
        save_session_state(session)
        append_command_history("clear-doc")
        click.echo("Current doc cleared.")
        return True, 0
    if command == "clear-node":
        session["current_node"] = None
        save_session_state(session)
        append_command_history("clear-node")
        click.echo("Current node cleared.")
        return True, 0
    if command == "use-doc":
        if len(argv) < 2:
            click.echo("use-doc requires a document reference.", err=True)
            return True, 0
        doc_ref = " ".join(argv[1:])
        session["current_doc"] = doc_ref
        save_session_state(session)
        append_command_history(f"use-doc {doc_ref}")
        click.echo(f"Current doc: {doc_ref}")
        return True, 0
    if command == "use-node":
        if len(argv) < 2:
            click.echo("use-node requires a node reference.", err=True)
            return True, 0
        node_ref = " ".join(argv[1:])
        session["current_node"] = node_ref
        save_session_state(session)
        append_command_history(f"use-node {node_ref}")
        click.echo(f"Current node: {node_ref}")
        return True, 0
    if command == "use-daily":
        folder_ref = " ".join(argv[1:]).strip() if len(argv) > 1 else None
        try:
            resolved_folder_ref = mubu_probe.resolve_daily_folder_ref(folder_ref)
            doc_ref = resolve_current_daily_doc_ref(resolved_folder_ref)
        except RuntimeError as exc:
            click.echo(str(exc), err=True)
            return True, 0
        session["current_doc"] = doc_ref
        save_session_state(session)
        append_command_history(f"use-daily {resolved_folder_ref}")
        click.echo(f"Current doc: {doc_ref}")
        return True, 0

    return False, 0


def run_repl(program_name: str | None = None) -> int:
    session = load_session_state()
    skin = ReplSkin("mubu", version=__version__, history_file=str(session_state_dir() / "history.txt"))
    prompt_session = skin.create_prompt_session()
    print_repl_banner(skin, program_name)
    if session.get("current_doc"):
        click.echo(f"Current doc: {session['current_doc']}")
    if session.get("current_node"):
        click.echo(f"Current node: {session['current_node']}")
    while True:
        try:
            line = skin.get_input(prompt_session)
        except EOFError:
            click.echo()
            skin.print_goodbye()
            return 0
        except KeyboardInterrupt:
            click.echo()
            continue

        line = line.strip()
        if not line:
            continue

        try:
            argv = shlex.split(line)
        except ValueError as exc:
            click.echo(f"parse error: {exc}", err=True)
            continue

        handled, control = handle_repl_builtin(argv, session, program_name)
        if handled:
            if control == 1:
                skin.print_goodbye()
                return 0
            session = load_session_state()
            continue

        argv = expand_repl_aliases_with_state(argv, session)
        if argv and argv[0] in REPL_WORKFLOW_SHORTCUTS:
            argv = ["workflow", *argv]
        result = dispatch(argv)
        if result not in (0, None):
            click.echo(f"command exited with status {result}", err=True)
        session = load_session_state()


@click.group(context_settings=CONTEXT_SETTINGS, invoke_without_command=True)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output for wrapped probe commands when supported.")
@click.pass_context
def cli(ctx: click.Context, json_output: bool) -> int:
    """Agent-native CLI for the Mubu desktop app with REPL and grouped command domains."""
    ctx.ensure_object(dict)
    ctx.obj["json_output"] = json_output
    ctx.obj["prog_name"] = normalize_program_name(ctx.info_name)
    if ctx.invoked_subcommand is None:
        return run_repl(ctx.obj["prog_name"])
    return 0


@cli.group(context_settings=CONTEXT_SETTINGS)
def discover() -> None:
    """Discovery commands for folders, documents, recency, and daily-document resolution."""


@discover.command("docs", context_settings=CONTEXT_SETTINGS, add_help_option=False)
@click.argument("probe_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def discover_docs(ctx: click.Context, probe_args: tuple[str, ...]) -> int:
    """List latest known document snapshots from local backups."""
    return invoke_probe_command(ctx, "docs", probe_args)


@discover.command("folders", context_settings=CONTEXT_SETTINGS, add_help_option=False)
@click.argument("probe_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def folders(ctx: click.Context, probe_args: tuple[str, ...]) -> int:
    """List folder metadata from local RxDB storage."""
    return invoke_probe_command(ctx, "folders", probe_args)


@discover.command("folder-docs", context_settings=CONTEXT_SETTINGS, add_help_option=False)
@click.argument("probe_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def folder_docs(ctx: click.Context, probe_args: tuple[str, ...]) -> int:
    """List document metadata for one folder."""
    return invoke_probe_command(ctx, "folder-docs", probe_args)


@discover.command("path-docs", context_settings=CONTEXT_SETTINGS, add_help_option=False)
@click.argument("probe_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def path_docs(ctx: click.Context, probe_args: tuple[str, ...]) -> int:
    """List documents for one folder path or folder id."""
    return invoke_probe_command(ctx, "path-docs", probe_args)


@discover.command("recent", context_settings=CONTEXT_SETTINGS, add_help_option=False)
@click.argument("probe_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def recent(ctx: click.Context, probe_args: tuple[str, ...]) -> int:
    """List recently active documents using backups, metadata, and sync logs."""
    return invoke_probe_command(ctx, "recent", probe_args)


@discover.command("daily", context_settings=CONTEXT_SETTINGS, add_help_option=False)
@click.argument("probe_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def daily(ctx: click.Context, probe_args: tuple[str, ...]) -> int:
    """Find Daily-style folders and list the documents inside them."""
    return invoke_probe_command(ctx, "daily", probe_args)


@discover.command("daily-current", context_settings=CONTEXT_SETTINGS, add_help_option=False)
@click.argument("probe_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def daily_current(ctx: click.Context, probe_args: tuple[str, ...]) -> int:
    """Resolve the current daily document from one Daily-style folder."""
    return invoke_probe_command(ctx, "daily-current", probe_args)


@cli.group(context_settings=CONTEXT_SETTINGS)
def inspect() -> None:
    """Inspection commands for tree views, search, links, sync events, and live node targeting."""


@inspect.command("show", context_settings=CONTEXT_SETTINGS, add_help_option=False)
@click.argument("probe_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def show(ctx: click.Context, probe_args: tuple[str, ...]) -> int:
    """Show the latest backup tree for one document."""
    return invoke_probe_command(ctx, "show", probe_args)


@inspect.command("search", context_settings=CONTEXT_SETTINGS, add_help_option=False)
@click.argument("probe_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def search(ctx: click.Context, probe_args: tuple[str, ...]) -> int:
    """Search latest backups for matching node text or note content."""
    return invoke_probe_command(ctx, "search", probe_args)


@inspect.command("changes", context_settings=CONTEXT_SETTINGS, add_help_option=False)
@click.argument("probe_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def changes(ctx: click.Context, probe_args: tuple[str, ...]) -> int:
    """Parse recent client-sync change events from local logs."""
    return invoke_probe_command(ctx, "changes", probe_args)


@inspect.command("links", context_settings=CONTEXT_SETTINGS, add_help_option=False)
@click.argument("probe_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def links(ctx: click.Context, probe_args: tuple[str, ...]) -> int:
    """Extract outbound Mubu document links from one document backup."""
    return invoke_probe_command(ctx, "links", probe_args)


@inspect.command("open-path", context_settings=CONTEXT_SETTINGS, add_help_option=False)
@click.argument("probe_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def open_path(ctx: click.Context, probe_args: tuple[str, ...]) -> int:
    """Open one document by full path, suffix path, title, or doc id."""
    return invoke_probe_command(ctx, "open-path", probe_args)


@inspect.command("doc-nodes", context_settings=CONTEXT_SETTINGS, add_help_option=False)
@click.argument("probe_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def doc_nodes(ctx: click.Context, probe_args: tuple[str, ...]) -> int:
    """List live document nodes with node ids and update-target paths."""
    return invoke_probe_command(ctx, "doc-nodes", probe_args)


@inspect.command("daily-nodes", context_settings=CONTEXT_SETTINGS, add_help_option=False)
@click.argument("probe_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def daily_nodes(ctx: click.Context, probe_args: tuple[str, ...]) -> int:
    """List live nodes from the current daily document in one step."""
    return invoke_probe_command(ctx, "daily-nodes", probe_args)


@cli.group(context_settings=CONTEXT_SETTINGS)
def mutate() -> None:
    """Mutation commands for dry-run-first atomic live edits against the Mubu API."""


@mutate.command("create-child", context_settings=CONTEXT_SETTINGS, add_help_option=False)
@click.argument("probe_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def create_child(ctx: click.Context, probe_args: tuple[str, ...]) -> int:
    """Build or execute one child-node creation against the live Mubu API."""
    return invoke_probe_command(ctx, "create-child", probe_args)


@mutate.command("delete-node", context_settings=CONTEXT_SETTINGS, add_help_option=False)
@click.argument("probe_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def delete_node(ctx: click.Context, probe_args: tuple[str, ...]) -> int:
    """Build or execute one node deletion against the live Mubu API."""
    return invoke_probe_command(ctx, "delete-node", probe_args)


@mutate.command("update-text", context_settings=CONTEXT_SETTINGS, add_help_option=False)
@click.argument("probe_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def update_text(ctx: click.Context, probe_args: tuple[str, ...]) -> int:
    """Build or execute one text update against the live Mubu API."""
    return invoke_probe_command(ctx, "update-text", probe_args)


@cli.command("doctor")
@click.option("--daily-folder", default=None, help="Override the daily folder reference for health checks.")
@click.option("--json", "json_output", is_flag=True, help="Emit doctor output as JSON.")
@click.pass_context
def doctor_command(ctx: click.Context, daily_folder: str | None, json_output: bool) -> int:
    """Run a read-only health check for local Mubu data, session state, and daily resolution."""
    payload = build_doctor_report(daily_folder_ref=daily_folder)
    emit_doctor_report(payload, json_output=json_output or root_json_output(ctx))
    return 0 if payload.get("ok") else 1


@cli.command("verify", context_settings=CONTEXT_SETTINGS, add_help_option=False)
@click.argument("verify_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def verify_command(ctx: click.Context, verify_args: tuple[str, ...]) -> int:
    """Run repeatable verification for the packaged CLI plus optional live smoke."""
    argv = list(verify_args)
    if root_json_output(ctx) and "--json" not in argv:
        argv.append("--json")
    return run_packaged_verify(argv)


@cli.group()
def workflow() -> None:
    """Workflow commands for entering a document, focusing a node, inspecting context, and continuing writing."""


@workflow.command("daily-open")
@click.argument("folder_ref", nargs=-1)
@click.option("--json", "json_output", is_flag=True, help="Emit workflow state as JSON.")
@click.pass_context
def workflow_daily_open(ctx: click.Context, folder_ref: tuple[str, ...], json_output: bool) -> int:
    """Resolve the current daily document and persist it as the active workflow document."""
    raw_value = joined_text(folder_ref)
    try:
        resolved_folder_ref = mubu_probe.resolve_daily_folder_ref(raw_value)
        doc_ref = resolve_current_daily_doc_ref(resolved_folder_ref)
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc

    session_state = load_session_state()
    session_state["current_doc"] = doc_ref
    session_state["current_node"] = None
    save_session_state(session_state)
    append_history_entry("workflow daily-open", resolved_folder_ref)

    payload = {
        "resolved_folder_ref": resolved_folder_ref,
        "current_doc": doc_ref,
        "current_node": None,
        "state_path": str(session_state_path()),
    }
    emit_workflow_result(payload, json_output=json_output or root_json_output(ctx))
    return 0


@workflow.command("today-start")
@click.argument("folder_ref", nargs=-1)
@click.option("--dry-run", is_flag=True, help="Plan the copy and rename workflow without creating a document.")
@click.option("--api-host", default=mubu_probe.DEFAULT_API_HOST, show_default=True)
@click.option("--json", "json_output", is_flag=True, help="Emit the today-start workflow result as JSON.")
@click.pass_context
def workflow_today_start(
    ctx: click.Context,
    folder_ref: tuple[str, ...],
    dry_run: bool,
    api_host: str,
    json_output: bool,
) -> int:
    """Create or open today's daily document from the latest dated template panel."""
    raw_value = joined_text(folder_ref)
    try:
        resolved_folder_ref, docs, folder = resolve_daily_folder_documents(raw_value)
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc

    target_date = mubu_probe.current_local_date()
    today_doc, _today_candidates = mubu_probe.find_daily_document_for_date(docs, target_date)
    template_source, _template_candidates = mubu_probe.choose_daily_template_source(docs, target_date)
    session_state = load_session_state()
    current_doc_ref = session_state.get("current_doc")
    today_doc_session_ref: str | None = None

    if today_doc is None and isinstance(current_doc_ref, str) and current_doc_ref and "/" not in current_doc_ref:
        user = mubu_probe.get_active_user(mubu_probe.DEFAULT_STORAGE_ROOT)
        if user is not None:
            try:
                current_doc_title = mubu_probe.fetch_document_name(current_doc_ref, user, api_host=api_host)
            except RuntimeError:
                current_doc_title = None
            if (
                isinstance(current_doc_title, str)
                and not mubu_probe.title_has_template_keyword(current_doc_title)
                and mubu_probe.parse_daily_title_date(current_doc_title, default_year=target_date.year) == target_date
            ):
                today_doc_session_ref = current_doc_ref
                today_doc = {
                    "doc_id": current_doc_ref,
                    "title": current_doc_title,
                    "doc_path": f"{folder.get('path')}/{current_doc_title}" if folder.get("path") else current_doc_ref,
                    "folder_id": folder.get("folder_id"),
                }

    if today_doc is not None:
        session_state["current_doc"] = today_doc_session_ref or today_doc.get("doc_path") or today_doc.get("doc_id")
        session_state["current_node"] = None
        save_session_state(session_state)
        append_history_entry("workflow today-start", resolved_folder_ref)
        payload = {
            "resolved_folder_ref": resolved_folder_ref,
            "target_date": target_date.isoformat(),
            "today_title": today_doc.get("title"),
            "created": False,
            "dry_run": False,
            "folder": {
                "folder_id": folder.get("folder_id"),
                "path": folder.get("path"),
            },
            "document": summarize_document_meta(today_doc),
            "template_source": summarize_document_meta(template_source) if template_source else None,
            "current_doc": session_state["current_doc"],
            "current_node": session_state["current_node"],
            "state_path": str(session_state_path()),
        }
        emit_workflow_result(payload, json_output=json_output or root_json_output(ctx))
        return 0

    if template_source is None:
        raise click.ClickException(f"no dated template source found in {folder.get('path')}")

    today_title = mubu_probe.format_daily_title_for_date(template_source.get("title"), target_date)
    if dry_run:
        payload = {
            "resolved_folder_ref": resolved_folder_ref,
            "target_date": target_date.isoformat(),
            "today_title": today_title,
            "created": False,
            "dry_run": True,
            "folder": {
                "folder_id": folder.get("folder_id"),
                "path": folder.get("path"),
            },
            "template_source": summarize_document_meta(template_source),
            "copy": {
                "request": mubu_probe.build_copy_doc_request(str(template_source["doc_id"])),
            },
            "rename": {
                "planned_name": today_title,
            },
            "current_doc": session_state.get("current_doc"),
            "current_node": session_state.get("current_node"),
            "state_path": str(session_state_path()),
        }
        append_history_entry("workflow today-start --dry-run", resolved_folder_ref)
        emit_workflow_result(payload, json_output=json_output or root_json_output(ctx))
        return 0

    user = mubu_probe.get_active_user(mubu_probe.DEFAULT_STORAGE_ROOT)
    if user is None:
        raise click.ClickException("no active user auth found in local storage")

    copy_result = mubu_probe.perform_copy_document(
        user=user,
        source_doc_id=str(template_source["doc_id"]),
        execute=True,
        api_host=api_host,
    )
    copy_response = copy_result.get("response", {})
    if copy_response.get("code") != 0:
        raise click.ClickException(f"copy_doc failed: {copy_response}")

    copy_data = copy_response.get("data")
    if not isinstance(copy_data, dict) or not isinstance(copy_data.get("id"), str):
        raise click.ClickException(f"copy_doc response missing new document id: {copy_response}")
    new_doc_id = copy_data["id"]

    rename_result = mubu_probe.perform_rename_document(
        user=user,
        document_id=new_doc_id,
        name=today_title,
        execute=True,
        api_host=api_host,
    )
    rename_response = rename_result.get("response", {})
    if rename_response.get("code") != 0:
        rollback_result = mubu_probe.perform_batch_delete_documents(
            user=user,
            doc_ids=[new_doc_id],
            execute=True,
            api_host=api_host,
        )
        raise click.ClickException(
            f"rename_doc failed for {new_doc_id}: {rename_response} "
            f"(rollback={rollback_result.get('response')})"
        )

    session_state["current_doc"] = new_doc_id
    session_state["current_node"] = None
    save_session_state(session_state)
    append_history_entry("workflow today-start", resolved_folder_ref)

    payload = {
        "resolved_folder_ref": resolved_folder_ref,
        "target_date": target_date.isoformat(),
        "today_title": today_title,
        "created": True,
        "dry_run": False,
        "folder": {
            "folder_id": folder.get("folder_id"),
            "path": folder.get("path"),
        },
        "template_source": summarize_document_meta(template_source),
        "document": {
            "doc_id": new_doc_id,
            "title": today_title,
            "doc_path": f"{folder.get('path')}/{today_title}" if folder.get("path") else None,
            "source_name_before_rename": copy_data.get("name"),
        },
        "copy": copy_result,
        "rename": rename_result,
        "current_doc": session_state["current_doc"],
        "current_node": session_state["current_node"],
        "state_path": str(session_state_path()),
    }
    emit_workflow_result(payload, json_output=json_output or root_json_output(ctx))
    return 0


@workflow.command("today-scan")
@click.argument("folder_ref", nargs=-1)
@click.option("--json", "json_output", is_flag=True, help="Emit the scanned task sections as JSON.")
@click.pass_context
def workflow_today_scan(ctx: click.Context, folder_ref: tuple[str, ...], json_output: bool) -> int:
    """Scan the latest daily document and extract today's actionable sections."""
    raw_value = joined_text(folder_ref)
    try:
        resolved_folder_ref = mubu_probe.resolve_daily_folder_ref(raw_value)
        doc_ref = resolve_current_daily_doc_ref(resolved_folder_ref)
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc

    meta, _user, _remote_doc, definition = resolve_live_document_context(doc_ref)
    session_state = load_session_state()
    session_state["current_doc"] = meta.get("doc_path") or doc_ref
    session_state["current_node"] = None
    save_session_state(session_state)
    append_history_entry("workflow today-scan", resolved_folder_ref)

    payload = build_today_scan_payload(meta, definition, resolved_folder_ref, session_state)
    emit_workflow_result(payload, json_output=json_output or root_json_output(ctx))
    return 0


@workflow.command("pick")
@click.argument("query", nargs=-1)
@click.option("--doc-ref", default=None, help="Document reference. Defaults to the current session document.")
@click.option("--query", "query_option", default=None, help="Search text to pick a node by content.")
@click.option("--node-id", default=None, help="Pick one exact node id instead of searching by query.")
@click.option("--index", type=int, default=None, help="1-based candidate index to choose when the query matches multiple nodes.")
@click.option("--list", "list_candidates", is_flag=True, help="List all matching candidates without changing the current workflow target.")
@click.option("--api-host", default=mubu_probe.DEFAULT_API_HOST, show_default=True)
@click.option("--json", "json_output", is_flag=True, help="Emit workflow state as JSON.")
@click.pass_context
def workflow_pick(
    ctx: click.Context,
    query: tuple[str, ...],
    doc_ref: str | None,
    query_option: str | None,
    node_id: str | None,
    index: int | None,
    list_candidates: bool,
    api_host: str,
    json_output: bool,
) -> int:
    """Select one live node in the active document and persist it as the current workflow node."""
    positional_query_text = joined_text(query)
    option_query_text = (query_option or "").strip()
    if positional_query_text and option_query_text:
        raise click.UsageError("pick accepts either a positional query or --query, not both")
    query_text = option_query_text or positional_query_text
    if node_id and query_text:
        raise click.UsageError("pick accepts either a query or --node-id, not both")
    if not node_id and not query_text:
        raise click.UsageError("pick requires a query or --node-id")
    if list_candidates and node_id:
        raise click.UsageError("pick --list requires a query and cannot be combined with --node-id")
    if list_candidates and index is not None:
        raise click.UsageError("pick --list cannot be combined with --index")

    resolved_doc_ref = require_current_doc_ref(doc_ref)
    meta, _user, _remote_doc, definition = resolve_live_document_context(resolved_doc_ref, api_host=api_host)
    session_state = load_session_state()

    if node_id:
        target_node, target_path = resolve_node_or_fail(definition, node_id=node_id)
        selected = summarize_node(target_node, target_path)
        match_count = 1
    else:
        matches = mubu_probe.list_document_nodes(definition, query=query_text)
        if not matches:
            raise click.ClickException(f"no nodes matched query in {meta.get('doc_path') or meta['doc_id']}: {query_text}")
        if list_candidates:
            payload = build_pick_candidates_payload(meta, query_text or "", matches, session_state)
            append_history_entry("workflow pick --list", query_text)
            emit_workflow_result(payload, json_output=json_output or root_json_output(ctx))
            return 0
        if len(matches) > 1 and index is None:
            labels = [f"{idx}. {item.get('node_id')} {item.get('text') or ''}".rstrip() for idx, item in enumerate(matches[:5], start=1)]
            if json_output or root_json_output(ctx):
                payload = build_pick_candidates_payload(meta, query_text or "", matches, session_state)
                payload["error"] = {
                    "code": "ambiguous_query",
                    "message": f"pick matched {len(matches)} nodes",
                    "hint": "rerun with --index N or --list",
                    "preview": labels,
                }
                emit_json(payload)
                return 2
            raise click.ClickException(
                f"pick matched {len(matches)} nodes; rerun with --index N or --list. Candidates: {' | '.join(labels)}"
            )
        if index is not None:
            if index < 1 or index > len(matches):
                raise click.ClickException(f"pick index out of range: {index} (match_count={len(matches)})")
            selected = matches[index - 1]
        else:
            selected = matches[0]
        match_count = len(matches)

    session_state["current_doc"] = meta.get("doc_path") or resolved_doc_ref
    session_state["current_node"] = selected.get("node_id")
    save_session_state(session_state)
    append_history_entry("workflow pick", query_text or f"--node-id {selected.get('node_id')}")

    payload = {
        "document": {
            "doc_id": meta["doc_id"],
            "title": meta.get("title"),
            "doc_path": meta.get("doc_path"),
        },
        "query": query_text,
        "match_count": match_count,
        "selected": selected,
        "current_doc": session_state["current_doc"],
        "current_node": session_state["current_node"],
        "state_path": str(session_state_path()),
    }
    emit_workflow_result(payload, json_output=json_output or root_json_output(ctx))
    return 0


@workflow.command("ctx")
@click.argument("doc_ref", nargs=-1)
@click.option("--node-id", default=None, help="Node id to inspect. Defaults to the current workflow node.")
@click.option("--siblings", default=2, show_default=True, type=int, help="How many previous and next siblings to include.")
@click.option("--children", "children_limit", default=5, show_default=True, type=int, help="How many direct children to include.")
@click.option("--api-host", default=mubu_probe.DEFAULT_API_HOST, show_default=True)
@click.option("--json", "json_output", is_flag=True, help="Emit workflow context as JSON.")
@click.pass_context
def workflow_ctx(
    ctx: click.Context,
    doc_ref: tuple[str, ...],
    node_id: str | None,
    siblings: int,
    children_limit: int,
    api_host: str,
    json_output: bool,
) -> int:
    """Show focused live context for the current node, including parent, siblings, and children."""
    resolved_doc_ref = require_current_doc_ref(joined_text(doc_ref))
    resolved_node_id = require_current_node_ref(node_id)
    meta, _user, _remote_doc, definition = resolve_live_document_context(resolved_doc_ref, api_host=api_host)
    target_node, target_path = resolve_node_or_fail(definition, node_id=resolved_node_id)

    payload = {
        "document": {
            "doc_id": meta["doc_id"],
            "title": meta.get("title"),
            "doc_path": meta.get("doc_path"),
        },
        **build_context_payload(
            definition,
            target_node=target_node,
            target_path=target_path,
            siblings_limit=max(0, siblings),
            children_limit=max(0, children_limit),
        ),
        "current_doc": load_session_state().get("current_doc"),
        "current_node": load_session_state().get("current_node"),
    }
    append_history_entry("workflow ctx", meta.get("doc_path") or resolved_doc_ref)
    emit_workflow_result(payload, json_output=json_output or root_json_output(ctx))
    return 0


@workflow.command("append")
@click.argument("doc_ref", nargs=-1)
@click.option("--text", required=True, help="New child plain text.")
@click.option("--note", default=None, help="Optional plain-text note for the new child.")
@click.option("--parent-node-id", default=None, help="Parent node id. Defaults to the current workflow node.")
@click.option("--index", type=int, default=None, help="Insert position within the parent children list.")
@click.option("--api-host", default=mubu_probe.DEFAULT_API_HOST, show_default=True)
@click.option("--execute", is_flag=True, help="Actually POST the live create request.")
@click.option("--json", "json_output", is_flag=True, help="Emit the workflow mutation payload as JSON.")
@click.pass_context
def workflow_append(
    ctx: click.Context,
    doc_ref: tuple[str, ...],
    text: str,
    note: str | None,
    parent_node_id: str | None,
    index: int | None,
    api_host: str,
    execute: bool,
    json_output: bool,
) -> int:
    """Append one child under the current node using the dry-run-first live mutation flow."""
    resolved_doc_ref = require_current_doc_ref(joined_text(doc_ref))
    resolved_parent_node_id = require_current_node_ref(parent_node_id)
    meta, user, remote_doc, definition = resolve_live_document_context(resolved_doc_ref, api_host=api_host)

    events = mubu_probe.load_change_events(mubu_probe.DEFAULT_LOG_ROOT, doc_id=meta["doc_id"], limit=None)
    member_context = mubu_probe.resolve_mutation_member_context(events, meta["doc_id"], execute=execute)
    if member_context is None:
        raise click.ClickException(f"no member context found in sync logs for document: {meta['doc_id']}")

    parent_node, parent_path = resolve_node_or_fail(definition, node_id=resolved_parent_node_id)

    try:
        result = mubu_probe.perform_create_child(
            user=user,
            doc_id=meta["doc_id"],
            member_id=member_context.get("member_id"),
            version=remote_doc.get("baseVersion", 0),
            parent_node=parent_node,
            parent_path=parent_path,
            text=text,
            note=note,
            index=index,
            execute=execute,
            api_host=api_host,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    created = result["request"]["data"]["events"][0]["created"][0]
    created_node = created["node"]
    payload = {
        "execute": execute,
        "document": {
            "doc_id": meta["doc_id"],
            "title": meta.get("title"),
            "doc_path": meta.get("doc_path"),
            "base_version": remote_doc.get("baseVersion"),
        },
        "member_context": member_context,
        "target_parent": {
            "node_id": parent_node.get("id"),
            "path": list(parent_path),
            "api_path": mubu_probe.node_path_to_api_path(parent_path),
            "current_text": mubu_probe.extract_plain_text(parent_node.get("text")),
            "existing_child_count": len(parent_node.get("children") or []),
        },
        "new_child": {
            "node_id": created_node.get("id"),
            "index": created.get("index"),
            "path": created.get("path"),
            "text": text,
            "note": note,
        },
        "request": result["request"],
        "current_doc": load_session_state().get("current_doc"),
        "current_node": load_session_state().get("current_node"),
    }
    if member_context.get("member_id") is None:
        payload["warning"] = "dry-run request uses a placeholder member context because no recent sync log entry was found"

    if execute:
        payload["response"] = result["response"]
        refreshed = mubu_probe.fetch_document_remote(meta["doc_id"], user, api_host=api_host)
        refreshed_definition = json.loads(refreshed.get("definition") or "{}")
        refreshed_node, _, _ = mubu_probe.resolve_node_reference_in_data(refreshed_definition, node_id=created_node.get("id"))
        payload["verification"] = {
            "base_version_after": refreshed.get("baseVersion"),
            "created_node_present": refreshed_node is not None,
            "node_text_after": mubu_probe.extract_plain_text((refreshed_node or {}).get("text")),
            "node_note_after": mubu_probe.extract_plain_text((refreshed_node or {}).get("note")),
        }
        session_state = load_session_state()
        session_state["current_doc"] = meta.get("doc_path") or resolved_doc_ref
        session_state["current_node"] = created_node.get("id")
        save_session_state(session_state)
        payload["current_doc"] = session_state["current_doc"]
        payload["current_node"] = session_state["current_node"]

    append_history_entry("workflow append", meta.get("doc_path") or resolved_doc_ref)
    emit_workflow_result(payload, json_output=json_output or root_json_output(ctx))
    return 0


@workflow.command("capture")
@click.option("--daily", "use_daily", is_flag=True, help="Resolve the current daily document before capturing.")
@click.option("--daily-folder", default=None, help="Override the daily folder reference used with --daily.")
@click.option("--doc-ref", default=None, help="Document reference. Defaults to the current session document.")
@click.option("--parent-node-id", default=None, help="Parent node id. Defaults to the current workflow node.")
@click.option("--query", default=None, help="Pick the parent node by substring query inside the resolved document.")
@click.option("--index", type=int, default=None, help="1-based candidate index when --query matches multiple nodes.")
@click.option("--text", required=True, help="New child plain text.")
@click.option("--note", default=None, help="Optional plain-text note for the new child.")
@click.option("--api-host", default=mubu_probe.DEFAULT_API_HOST, show_default=True)
@click.option("--execute", is_flag=True, help="Actually POST the live create request.")
@click.option("--json", "json_output", is_flag=True, help="Emit the workflow mutation payload as JSON.")
@click.pass_context
def workflow_capture(
    ctx: click.Context,
    use_daily: bool,
    daily_folder: str | None,
    doc_ref: str | None,
    parent_node_id: str | None,
    query: str | None,
    index: int | None,
    text: str,
    note: str | None,
    api_host: str,
    execute: bool,
    json_output: bool,
) -> int:
    """Capture one child into the current daily or current document in one step."""
    if use_daily and doc_ref:
        raise click.UsageError("capture accepts either --daily or --doc-ref, not both")
    if parent_node_id and query:
        raise click.UsageError("capture accepts either --parent-node-id or --query, not both")

    resolved_folder_ref = None
    if use_daily:
        try:
            resolved_folder_ref = mubu_probe.resolve_daily_folder_ref(daily_folder)
            resolved_doc_ref = resolve_current_daily_doc_ref(resolved_folder_ref)
        except RuntimeError as exc:
            raise click.ClickException(str(exc)) from exc
    else:
        resolved_doc_ref = require_current_doc_ref(doc_ref)

    meta, user, remote_doc, definition = resolve_live_document_context(resolved_doc_ref, api_host=api_host)

    if parent_node_id:
        parent_node, parent_path = resolve_node_or_fail(definition, node_id=parent_node_id)
        match_count = 1
    elif query:
        parent_node, parent_path, match_count = resolve_query_node_or_fail(definition, query_text=query, index=index)
    else:
        current_parent_id = require_current_node_ref(None)
        parent_node, parent_path = resolve_node_or_fail(definition, node_id=current_parent_id)
        match_count = 1

    session_state = load_session_state()
    session_state["current_doc"] = meta.get("doc_path") or resolved_doc_ref
    session_state["current_node"] = parent_node.get("id")
    save_session_state(session_state)

    events = mubu_probe.load_change_events(mubu_probe.DEFAULT_LOG_ROOT, doc_id=meta["doc_id"], limit=None)
    member_context = mubu_probe.resolve_mutation_member_context(events, meta["doc_id"], execute=execute)
    if member_context is None:
        raise click.ClickException(f"no member context found in sync logs for document: {meta['doc_id']}")

    try:
        result = mubu_probe.perform_create_child(
            user=user,
            doc_id=meta["doc_id"],
            member_id=member_context.get("member_id"),
            version=remote_doc.get("baseVersion", 0),
            parent_node=parent_node,
            parent_path=parent_path,
            text=text,
            note=note,
            index=None,
            execute=execute,
            api_host=api_host,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    created = result["request"]["data"]["events"][0]["created"][0]
    created_node = created["node"]
    payload = {
        "execute": execute,
        "resolved_folder_ref": resolved_folder_ref,
        "query": query,
        "match_count": match_count,
        "document": {
            "doc_id": meta["doc_id"],
            "title": meta.get("title"),
            "doc_path": meta.get("doc_path"),
            "base_version": remote_doc.get("baseVersion"),
        },
        "member_context": member_context,
        "target_parent": {
            "node_id": parent_node.get("id"),
            "path": list(parent_path),
            "api_path": mubu_probe.node_path_to_api_path(parent_path),
            "current_text": mubu_probe.extract_plain_text(parent_node.get("text")),
            "existing_child_count": len(parent_node.get("children") or []),
        },
        "new_child": {
            "node_id": created_node.get("id"),
            "index": created.get("index"),
            "path": created.get("path"),
            "text": text,
            "note": note,
        },
        "request": result["request"],
        "current_doc": session_state.get("current_doc"),
        "current_node": session_state.get("current_node"),
    }
    if member_context.get("member_id") is None:
        payload["warning"] = "dry-run request uses a placeholder member context because no recent sync log entry was found"

    if execute:
        payload["response"] = result["response"]
        refreshed = mubu_probe.fetch_document_remote(meta["doc_id"], user, api_host=api_host)
        refreshed_definition = json.loads(refreshed.get("definition") or "{}")
        refreshed_node, _, _ = mubu_probe.resolve_node_reference_in_data(refreshed_definition, node_id=created_node.get("id"))
        payload["verification"] = {
            "base_version_after": refreshed.get("baseVersion"),
            "created_node_present": refreshed_node is not None,
            "node_text_after": mubu_probe.extract_plain_text((refreshed_node or {}).get("text")),
            "node_note_after": mubu_probe.extract_plain_text((refreshed_node or {}).get("note")),
        }
        session_state = load_session_state()
        session_state["current_doc"] = meta.get("doc_path") or resolved_doc_ref
        session_state["current_node"] = created_node.get("id")
        save_session_state(session_state)
        payload["current_doc"] = session_state["current_doc"]
        payload["current_node"] = session_state["current_node"]

    append_history_entry("workflow capture", meta.get("doc_path") or resolved_doc_ref)
    emit_workflow_result(payload, json_output=json_output or root_json_output(ctx))
    return 0


@cli.group()
def session() -> None:
    """Session and state commands for current document/node context and local command history."""


@session.command("status")
@click.option("--json", "json_output", is_flag=True, help="Emit session state as JSON.")
@click.pass_context
def session_status(ctx: click.Context, json_output: bool) -> int:
    """Show the current session state."""
    emit_session_status(load_session_state(), json_output=json_output or root_json_output(ctx))
    return 0


@session.command("state-path")
@click.option("--json", "json_output", is_flag=True, help="Emit the session state path as JSON.")
@click.pass_context
def state_path_command(ctx: click.Context, json_output: bool) -> int:
    """Show the session state file path."""
    payload = {"state_path": str(session_state_path())}
    if json_output or root_json_output(ctx):
        emit_json(payload)
    else:
        click.echo(payload["state_path"])
    return 0


@session.command("use-doc")
@click.argument("doc_ref", nargs=-1)
def use_doc(doc_ref: tuple[str, ...]) -> int:
    """Persist the current document reference."""
    if not doc_ref:
        raise click.UsageError("use-doc requires a document reference.")
    value = " ".join(doc_ref)
    session_state = load_session_state()
    session_state["current_doc"] = value
    save_session_state(session_state)
    append_command_history(f"session use-doc {value}")
    click.echo(f"Current doc: {value}")
    return 0


@session.command("use-node")
@click.argument("node_ref", nargs=-1)
def use_node(node_ref: tuple[str, ...]) -> int:
    """Persist the current node reference."""
    if not node_ref:
        raise click.UsageError("use-node requires a node reference.")
    value = " ".join(node_ref)
    session_state = load_session_state()
    session_state["current_node"] = value
    save_session_state(session_state)
    append_command_history(f"session use-node {value}")
    click.echo(f"Current node: {value}")
    return 0


@session.command("use-daily")
@click.argument("folder_ref", nargs=-1)
def use_daily(folder_ref: tuple[str, ...]) -> int:
    """Resolve and persist the current daily document reference."""
    raw_value = " ".join(folder_ref).strip() if folder_ref else None
    try:
        resolved_folder_ref = mubu_probe.resolve_daily_folder_ref(raw_value)
        doc_ref = resolve_current_daily_doc_ref(resolved_folder_ref)
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc
    session_state = load_session_state()
    session_state["current_doc"] = doc_ref
    save_session_state(session_state)
    append_command_history(f"session use-daily {resolved_folder_ref}")
    click.echo(f"Current doc: {doc_ref}")
    return 0


@session.command("clear-doc")
def clear_doc() -> int:
    """Clear the current document reference."""
    session_state = load_session_state()
    session_state["current_doc"] = None
    save_session_state(session_state)
    append_command_history("session clear-doc")
    click.echo("Current doc cleared.")
    return 0


@session.command("clear-node")
def clear_node() -> int:
    """Clear the current node reference."""
    session_state = load_session_state()
    session_state["current_node"] = None
    save_session_state(session_state)
    append_command_history("session clear-node")
    click.echo("Current node cleared.")
    return 0


@session.command("history")
@click.option("--limit", default=10, show_default=True, type=int, help="How many recent entries to show.")
@click.option("--json", "json_output", is_flag=True, help="Emit command history as JSON.")
@click.pass_context
def history_command(ctx: click.Context, limit: int, json_output: bool) -> int:
    """Show recent command history stored in session state."""
    emit_session_history(load_session_state(), max(1, limit), json_output=json_output or root_json_output(ctx))
    return 0


@cli.command("repl", help=REPL_COMMAND_HELP)
@click.pass_context
def repl_command(ctx: click.Context) -> int:
    """Interactive REPL for the Mubu CLI."""
    root = ctx.find_root()
    program_name = None
    if root is not None and root.obj is not None:
        program_name = root.obj.get("prog_name")
    return run_repl(program_name)


def create_legacy_command(command_name: str, help_text: str) -> click.Command:
    @click.command(name=command_name, help=help_text, context_settings=CONTEXT_SETTINGS, add_help_option=False)
    @click.argument("probe_args", nargs=-1, type=click.UNPROCESSED)
    @click.pass_context
    def legacy(ctx: click.Context, probe_args: tuple[str, ...]) -> int:
        return invoke_probe_command(ctx, command_name, probe_args)

    return legacy


for _command_name, _help_text in LEGACY_COMMANDS.items():
    cli.add_command(create_legacy_command(_command_name, _help_text))


def dispatch(argv: list[str] | None = None, prog_name: str | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    normalized_prog_name = normalize_program_name(prog_name or sys.argv[0])
    try:
        result = cli.main(args=args, prog_name=normalized_prog_name, standalone_mode=False)
    except click.exceptions.Exit as exc:
        return int(exc.exit_code)
    except click.ClickException as exc:
        exc.show()
        return int(exc.exit_code)
    return int(result or 0)


def entrypoint(argv: list[str] | None = None) -> int:
    return dispatch(argv, prog_name=sys.argv[0])


__all__ = [
    "REPL_HELP",
    "append_command_history",
    "build_session_payload",
    "cli",
    "default_session_state",
    "dispatch",
    "entrypoint",
    "normalize_program_name",
    "expand_repl_aliases",
    "expand_repl_aliases_with_state",
    "handle_repl_builtin",
    "load_session_state",
    "repl_help_text",
    "resolve_current_daily_doc_ref",
    "run_repl",
    "save_session_state",
    "session_state_dir",
    "session_state_path",
]
