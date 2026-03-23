from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import mubu_probe


MODULE_PATH = Path(__file__).resolve()
HARNESS_ROOT = MODULE_PATH.parents[2]
REPO_ROOT = MODULE_PATH.parents[3]
HAS_HARNESS_SOURCE = (HARNESS_ROOT / "setup.py").is_file()
HAS_REPO_SOURCE = (REPO_ROOT / "setup.py").is_file()
HAS_CANONICAL_TESTS = (HARNESS_ROOT / "cli_anything" / "mubu" / "tests").is_dir()


@dataclass
class StepResult:
    name: str
    ok: bool
    command: str | None
    details: str
    skipped: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "command": self.command,
            "details": self.details,
            "skipped": self.skipped,
        }


def run_command(
    name: str,
    cmd: list[str],
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: int = 300,
) -> StepResult:
    merged_env = os.environ.copy()
    merged_env["PYTHONPATH"] = str(HARNESS_ROOT) + os.pathsep + merged_env.get("PYTHONPATH", "")
    if env:
        merged_env.update(env)
    result = subprocess.run(
        cmd,
        cwd=cwd,
        env=merged_env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    details = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
    return StepResult(
        name=name,
        ok=result.returncode == 0,
        command=" ".join(cmd),
        details=details or f"exit={result.returncode}",
    )


def detect_daily_folder_ref() -> str | None:
    if not (mubu_probe.DEFAULT_BACKUP_ROOT.is_dir() and mubu_probe.DEFAULT_STORAGE_ROOT.is_dir()):
        return None

    metas = mubu_probe.load_document_metas(mubu_probe.DEFAULT_STORAGE_ROOT)
    folders = mubu_probe.load_folders(mubu_probe.DEFAULT_STORAGE_ROOT)
    _, folder_paths = mubu_probe.build_folder_indexes(folders)
    docs_by_folder: dict[str, list[dict[str, object]]] = {}
    for meta in metas:
        folder_id = meta.get("folder_id")
        if isinstance(folder_id, str):
            docs_by_folder.setdefault(folder_id, []).append(meta)

    best_path: str | None = None
    best_score = -1
    for folder in folders:
        folder_id = folder.get("folder_id")
        if not isinstance(folder_id, str):
            continue
        _, candidates = mubu_probe.choose_current_daily_document(docs_by_folder.get(folder_id, []))
        if not candidates:
            continue
        folder_path = folder_paths.get(folder_id, "")
        if not folder_path:
            continue
        score = max(
            max(item.get("updated_at") or 0, item.get("created_at") or 0)
            for item in candidates
        )
        if score > best_score:
            best_score = score
            best_path = folder_path
    return best_path


def resolve_entrypoint(command_name: str, module_name: str) -> list[str]:
    installed = shutil.which(command_name)
    if installed:
        return [installed]
    return [sys.executable, "-m", module_name]


def choose_pickable_node(nodes_payload: dict[str, Any]) -> tuple[str, str]:
    doc = nodes_payload.get("document", nodes_payload)
    doc_ref = doc.get("doc_path")
    if not isinstance(doc_ref, str) or not doc_ref:
        raise RuntimeError("daily-nodes did not return a usable doc_path")
    for item in nodes_payload.get("nodes", []):
        node_id = item.get("node_id")
        if isinstance(node_id, str) and node_id:
            return doc_ref, node_id
    raise RuntimeError("daily-nodes did not return a usable node_id")


def resolve_live_smoke_doc_refs(daily_folder_ref: str) -> tuple[str | None, str | None]:
    metas = mubu_probe.load_document_metas(mubu_probe.DEFAULT_STORAGE_ROOT)
    folders = mubu_probe.load_folders(mubu_probe.DEFAULT_STORAGE_ROOT)
    docs, folder, ambiguous = mubu_probe.folder_documents(metas, folders, daily_folder_ref)
    if folder is None:
        return None, None
    current_doc, candidates = mubu_probe.choose_current_daily_document(docs)
    current_doc_ref = current_doc.get("doc_path") if isinstance(current_doc, dict) else None
    execute_doc_ref: str | None = None
    for candidate in candidates:
        doc_id = candidate.get("doc_id")
        doc_path = candidate.get("doc_path")
        if not isinstance(doc_id, str) or not isinstance(doc_path, str):
            continue
        events = mubu_probe.load_change_events(mubu_probe.DEFAULT_LOG_ROOT, doc_id=doc_id, limit=None)
        member_context = mubu_probe.resolve_mutation_member_context(events, doc_id, execute=True)
        if member_context is not None:
            execute_doc_ref = doc_path
            break
    return current_doc_ref, execute_doc_ref


def run_live_smoke(mubu_cli: list[str]) -> StepResult:
    daily_folder_ref = detect_daily_folder_ref()
    if daily_folder_ref is None:
        return StepResult(
            name="live-smoke",
            ok=True,
            command=None,
            details="skipped: local Mubu data or daily folder not found",
            skipped=True,
        )

    state_dir = tempfile.mkdtemp(prefix="mubu-cli-verify-state-")
    env = {
        "CLI_ANYTHING_MUBU_STATE_DIR": state_dir,
        "MUBU_DAILY_FOLDER": daily_folder_ref,
    }

    steps: list[dict[str, Any]] = []
    created_node_ids: list[tuple[str, str]] = []
    doc_ref_for_cleanup: str | None = None
    mutation_doc_ref: str | None = None
    mutation_parent_node_id: str | None = None

    try:
        current_daily_doc_ref, execute_doc_ref = resolve_live_smoke_doc_refs(daily_folder_ref)
        daily_open = run_command(
            "daily-open",
            [*mubu_cli, "workflow", "daily-open", "--json"],
            cwd=HARNESS_ROOT,
            env=env,
            timeout=120,
        )
        steps.append(daily_open.as_dict())
        if not daily_open.ok:
            return StepResult("live-smoke", False, daily_open.command, json.dumps({"steps": steps}, ensure_ascii=False, indent=2))
        daily_open_payload = json.loads(daily_open.details)
        doc_ref = daily_open_payload["current_doc"]
        doc_ref_for_cleanup = doc_ref

        daily_nodes = run_command(
            "daily-nodes",
            [*mubu_cli, "daily-nodes", "--json"],
            cwd=HARNESS_ROOT,
            env=env,
            timeout=120,
        )
        steps.append(daily_nodes.as_dict())
        if not daily_nodes.ok:
            return StepResult("live-smoke", False, daily_nodes.command, json.dumps({"steps": steps}, ensure_ascii=False, indent=2))
        daily_nodes_payload = json.loads(daily_nodes.details)
        daily_doc = daily_nodes_payload.get("document", daily_nodes_payload)
        doc_ref = daily_doc.get("doc_path") if isinstance(daily_doc, dict) else None
        parent_node_id: str | None = None
        try:
            doc_ref, parent_node_id = choose_pickable_node(daily_nodes_payload)
            doc_ref_for_cleanup = doc_ref
        except RuntimeError as exc:
            if "usable node_id" not in str(exc):
                return StepResult(
                    "live-smoke",
                    False,
                    daily_nodes.command,
                    json.dumps({"steps": steps, "error": str(exc)}, ensure_ascii=False, indent=2),
                )
            if isinstance(doc_ref, str) and doc_ref:
                doc_ref_for_cleanup = doc_ref
        if execute_doc_ref is None:
            reason = "no execute-ready daily document found in sync logs"
            if parent_node_id is None:
                reason = "current daily document has no pickable nodes and no execute-ready daily document was found"
            return StepResult(
                "live-smoke",
                True,
                None,
                json.dumps(
                    {
                        "daily_folder_ref": daily_folder_ref,
                        "current_daily_doc_ref": current_daily_doc_ref,
                        "execute_doc_ref": None,
                        "steps": steps,
                        "reason": reason,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                skipped=True,
            )
        mutation_doc_ref = doc_ref
        mutation_parent_node_id = parent_node_id
        if execute_doc_ref and (mutation_parent_node_id is None or execute_doc_ref != doc_ref):
            execute_nodes = run_command(
                "doc-nodes-execute-doc",
                [*mubu_cli, "doc-nodes", execute_doc_ref, "--json"],
                cwd=HARNESS_ROOT,
                env=env,
                timeout=120,
            )
            steps.append(execute_nodes.as_dict())
            if not execute_nodes.ok:
                return StepResult("live-smoke", False, execute_nodes.command, json.dumps({"steps": steps}, ensure_ascii=False, indent=2))
            mutation_doc_ref, mutation_parent_node_id = choose_pickable_node(json.loads(execute_nodes.details))
            doc_ref_for_cleanup = mutation_doc_ref

        for name, cmd in [
            ("pick", [*mubu_cli, "workflow", "pick", "--doc-ref", mutation_doc_ref, "--node-id", mutation_parent_node_id, "--json"]),
            ("ctx", [*mubu_cli, "workflow", "ctx", "--json"]),
        ]:
            result = run_command(name, cmd, cwd=HARNESS_ROOT, env=env, timeout=120)
            steps.append(result.as_dict())
            if not result.ok:
                return StepResult("live-smoke", False, result.command, json.dumps({"steps": steps}, ensure_ascii=False, indent=2))

        stamp = str(int(Path(state_dir).stat().st_mtime))
        append_text = f"verify-append-{stamp}"
        capture_text = f"verify-capture-{stamp}"

        append_dry = run_command(
            "append-dry",
            [*mubu_cli, "workflow", "append", "--text", append_text, "--json"],
            cwd=HARNESS_ROOT,
            env=env,
            timeout=120,
        )
        steps.append(append_dry.as_dict())
        if not append_dry.ok:
            return StepResult("live-smoke", False, append_dry.command, json.dumps({"steps": steps}, ensure_ascii=False, indent=2))

        append_exec = run_command(
            "append-exec",
            [*mubu_cli, "workflow", "append", "--text", append_text, "--execute", "--json"],
            cwd=HARNESS_ROOT,
            env=env,
            timeout=120,
        )
        steps.append(append_exec.as_dict())
        if not append_exec.ok:
            return StepResult("live-smoke", False, append_exec.command, json.dumps({"steps": steps}, ensure_ascii=False, indent=2))
        append_exec_payload = json.loads(append_exec.details)
        created_node_ids.append((mutation_doc_ref, append_exec_payload["new_child"]["node_id"]))

        capture_base = [
            *mubu_cli,
            "workflow",
            "capture",
        ]
        if mutation_doc_ref == doc_ref:
            capture_base.extend(["--daily", "--parent-node-id", mutation_parent_node_id])
        else:
            capture_base.extend(["--doc-ref", mutation_doc_ref, "--parent-node-id", mutation_parent_node_id])

        capture_dry = run_command(
            "capture-dry",
            [*capture_base, "--text", capture_text, "--json"],
            cwd=HARNESS_ROOT,
            env=env,
            timeout=120,
        )
        steps.append(capture_dry.as_dict())
        if not capture_dry.ok:
            return StepResult("live-smoke", False, capture_dry.command, json.dumps({"steps": steps}, ensure_ascii=False, indent=2))

        capture_exec = run_command(
            "capture-exec",
            [*capture_base, "--text", capture_text, "--execute", "--json"],
            cwd=HARNESS_ROOT,
            env=env,
            timeout=120,
        )
        steps.append(capture_exec.as_dict())
        if not capture_exec.ok:
            return StepResult("live-smoke", False, capture_exec.command, json.dumps({"steps": steps}, ensure_ascii=False, indent=2))
        capture_exec_payload = json.loads(capture_exec.details)
        created_node_ids.append((mutation_doc_ref, capture_exec_payload["new_child"]["node_id"]))

        compat = resolve_entrypoint("cli-anything-mubu", "cli_anything.mubu")
        compat_daily_open = run_command(
            "compat-daily-open",
            [*compat, "workflow", "daily-open", "--json"],
            cwd=HARNESS_ROOT,
            env=env,
            timeout=120,
        )
        steps.append(compat_daily_open.as_dict())
        if not compat_daily_open.ok:
            return StepResult("live-smoke", False, compat_daily_open.command, json.dumps({"steps": steps}, ensure_ascii=False, indent=2))

        cleanup_steps: list[dict[str, Any]] = []
        while created_node_ids:
            cleanup_doc_ref, cleanup_node_id = created_node_ids.pop()
            cleanup = run_command(
                f"cleanup-{cleanup_node_id}",
                [*mubu_cli, "delete-node", cleanup_doc_ref, "--node-id", cleanup_node_id, "--execute", "--json"],
                cwd=HARNESS_ROOT,
                env=env,
                timeout=120,
            )
            cleanup_steps.append(cleanup.as_dict())
            if not cleanup.ok:
                return StepResult(
                    "live-smoke",
                    False,
                    cleanup.command,
                    json.dumps({"steps": steps, "cleanup_steps": cleanup_steps}, ensure_ascii=False, indent=2),
                )

        return StepResult(
            name="live-smoke",
            ok=True,
            command=None,
            details=json.dumps(
                {
                    "daily_folder_ref": daily_folder_ref,
                    "current_daily_doc_ref": current_daily_doc_ref,
                    "execute_doc_ref": mutation_doc_ref,
                    "doc_ref": doc_ref_for_cleanup,
                    "parent_node_id": mutation_parent_node_id,
                    "steps": steps,
                    "cleanup_steps": cleanup_steps,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    finally:
        while created_node_ids:
            cleanup_doc_ref, cleanup_node_id = created_node_ids.pop()
            subprocess.run(
                [*mubu_cli, "delete-node", cleanup_doc_ref, "--node-id", cleanup_node_id, "--execute", "--json"],
                cwd=HARNESS_ROOT,
                env={**os.environ, **env, "PYTHONPATH": str(HARNESS_ROOT) + os.pathsep + os.environ.get("PYTHONPATH", "")},
                capture_output=True,
                text=True,
                timeout=120,
            )
        shutil.rmtree(state_dir, ignore_errors=True)


def render_report(results: list[StepResult], as_json: bool) -> int:
    overall_ok = all(result.ok or result.skipped for result in results)
    if as_json:
        print(json.dumps({"ok": overall_ok, "results": [result.as_dict() for result in results]}, ensure_ascii=False, indent=2))
        return 0 if overall_ok else 1

    for result in results:
        status = "SKIP" if result.skipped else ("PASS" if result.ok else "FAIL")
        print(f"[{status}] {result.name}")
        if result.command:
            print(f"  cmd: {result.command}")
        if result.details:
            for line in result.details.splitlines()[:20]:
                print(f"  {line}")
    print(f"\nOverall: {'PASS' if overall_ok else 'FAIL'}")
    return 0 if overall_ok else 1


def development_results() -> list[StepResult]:
    results: list[StepResult] = []
    if HAS_REPO_SOURCE:
        results.append(
            run_command(
                "build-root",
                [sys.executable, "setup.py", "-q", "sdist", "bdist_wheel"],
                cwd=REPO_ROOT,
                timeout=300,
            )
        )
    else:
        results.append(StepResult("build-root", True, None, "skipped: repo setup.py not available", skipped=True))

    if HAS_HARNESS_SOURCE:
        results.append(
            run_command(
                "build-harness",
                [sys.executable, "setup.py", "-q", "sdist", "bdist_wheel"],
                cwd=HARNESS_ROOT,
                timeout=300,
            )
        )
        compile_targets = [
            HARNESS_ROOT / "cli_anything" / "mubu" / "mubu_cli.py",
            HARNESS_ROOT / "cli_anything" / "mubu" / "tests" / "test_cli_entrypoint.py",
            HARNESS_ROOT / "cli_anything" / "mubu" / "tests" / "test_full_e2e.py",
            HARNESS_ROOT / "scripts" / "verify_mubu_cli.py",
        ]
        existing_targets = [str(path) for path in compile_targets if path.is_file()]
        if existing_targets:
            results.append(
                run_command(
                    "py-compile",
                    [sys.executable, "-m", "py_compile", *existing_targets],
                    cwd=HARNESS_ROOT,
                )
            )
        else:
            results.append(StepResult("py-compile", True, None, "skipped: compile targets not available", skipped=True))

        ruff = shutil.which("ruff")
        if ruff:
            lint_targets = [
                "cli_anything/mubu/mubu_cli.py",
                "cli_anything/mubu/tests/test_cli_entrypoint.py",
                "cli_anything/mubu/tests/test_full_e2e.py",
                "cli_anything/mubu/tests/test_agent_harness.py",
                "scripts/verify_mubu_cli.py",
            ]
            existing_lint_targets = [target for target in lint_targets if (HARNESS_ROOT / target).exists()]
            if existing_lint_targets:
                results.append(
                    run_command(
                        "ruff",
                        [ruff, "check", *existing_lint_targets],
                        cwd=HARNESS_ROOT,
                    )
                )
            else:
                results.append(StepResult("ruff", True, None, "skipped: lint targets not available", skipped=True))
        else:
            results.append(StepResult("ruff", True, None, "skipped: ruff not installed", skipped=True))

        if HAS_CANONICAL_TESTS:
            results.append(
                run_command(
                    "pytest",
                    [sys.executable, "-m", "pytest", "cli_anything/mubu/tests", "-q"],
                    cwd=HARNESS_ROOT,
                    timeout=900,
                )
            )
        else:
            results.append(StepResult("pytest", True, None, "skipped: canonical tests not available", skipped=True))
    else:
        results.extend(
            [
                StepResult("build-harness", True, None, "skipped: harness setup.py not available", skipped=True),
                StepResult("py-compile", True, None, "skipped: harness source not available", skipped=True),
                StepResult("ruff", True, None, "skipped: harness source not available", skipped=True),
                StepResult("pytest", True, None, "skipped: harness source not available", skipped=True),
            ]
        )
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run repeatable verification for the Mubu CLI harness.")
    parser.add_argument("--skip-live", action="store_true", help="Skip the reversible live Mubu smoke test.")
    parser.add_argument("--json", action="store_true", help="Emit the verification report as JSON.")
    args = parser.parse_args(argv)

    mubu_cli = resolve_entrypoint("mubu-cli", "cli_anything.mubu")
    compat_cli = resolve_entrypoint("cli-anything-mubu", "cli_anything.mubu")

    results = development_results()
    results.extend(
        [
            run_command("mubu-help", [*mubu_cli, "--help"], cwd=HARNESS_ROOT, timeout=120),
            run_command("mubu-workflow-help", [*mubu_cli, "workflow", "--help"], cwd=HARNESS_ROOT, timeout=120),
            run_command("compat-help", [*compat_cli, "--help"], cwd=HARNESS_ROOT, timeout=120),
            run_command("compat-workflow-help", [*compat_cli, "workflow", "--help"], cwd=HARNESS_ROOT, timeout=120),
        ]
    )

    if args.skip_live:
        results.append(StepResult("live-smoke", True, None, "skipped: --skip-live requested", skipped=True))
    else:
        results.append(run_live_smoke(mubu_cli))

    return render_report(results, as_json=args.json)


__all__ = [
    "HARNESS_ROOT",
    "REPO_ROOT",
    "StepResult",
    "detect_daily_folder_ref",
    "main",
    "render_report",
    "resolve_live_smoke_doc_refs",
    "resolve_entrypoint",
    "run_command",
    "run_live_smoke",
]
