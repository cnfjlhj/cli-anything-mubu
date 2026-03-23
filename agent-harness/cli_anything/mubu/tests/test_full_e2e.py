"""Full end-to-end tests for cli-anything-mubu.

These tests invoke the CLI against real local Mubu desktop data.
They require the Mubu desktop app to have been used on this machine
so that backup, storage, and log directories exist.

Tests are skipped automatically when local data directories are missing.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]

# Import mubu_probe defaults for path detection
sys.path.insert(0, str(REPO_ROOT / "agent-harness"))
try:
    from mubu_probe import (
        DEFAULT_BACKUP_ROOT,
        DEFAULT_STORAGE_ROOT,
        build_folder_indexes,
        choose_current_daily_document,
        folder_documents,
        load_document_metas,
        load_folders,
    )
finally:
    sys.path.pop(0)

HAS_LOCAL_DATA = (
    DEFAULT_BACKUP_ROOT.is_dir()
    and DEFAULT_STORAGE_ROOT.is_dir()
)


def detect_daily_folder_ref() -> str | None:
    if not HAS_LOCAL_DATA:
        return None

    metas = load_document_metas(DEFAULT_STORAGE_ROOT)
    folders = load_folders(DEFAULT_STORAGE_ROOT)
    _, folder_paths = build_folder_indexes(folders)
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
        _, candidates = choose_current_daily_document(docs_by_folder.get(folder_id, []))
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


DETECTED_DAILY_FOLDER_REF = detect_daily_folder_ref()
HAS_DAILY_FOLDER = HAS_LOCAL_DATA and DETECTED_DAILY_FOLDER_REF is not None

SKIP_REASON = "Mubu local data or a daily-style folder was not found"
LIVE_API_SKIP_MARKERS = (
    "CERTIFICATE_VERIFY_FAILED",
    "SSLCertVerificationError",
    "Hostname mismatch",
    "request failed for https://api2.mubu.com",
    "urlopen error",
)


def prioritized_daily_doc_refs() -> list[str]:
    if not HAS_DAILY_FOLDER or DETECTED_DAILY_FOLDER_REF is None:
        return []

    metas = load_document_metas(DEFAULT_STORAGE_ROOT)
    folders = load_folders(DEFAULT_STORAGE_ROOT)
    docs, folder, _ambiguous = folder_documents(metas, folders, DETECTED_DAILY_FOLDER_REF)
    if folder is None:
        return []

    current_doc, candidates = choose_current_daily_document(docs)
    ordered_refs: list[str] = []
    for candidate in ([current_doc] if current_doc else []) + list(candidates):
        if not isinstance(candidate, dict):
            continue
        doc_ref = candidate.get("doc_path")
        if isinstance(doc_ref, str) and doc_ref and doc_ref not in ordered_refs:
            ordered_refs.append(doc_ref)
    return ordered_refs


PRIORITIZED_DAILY_DOC_REFS = prioritized_daily_doc_refs()


def assert_cli_success_or_skip(testcase: unittest.TestCase, result: subprocess.CompletedProcess) -> None:
    if result.returncode == 0:
        return
    details = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
    if any(marker in details for marker in LIVE_API_SKIP_MARKERS):
        testcase.skipTest(f"live Mubu API unavailable in this environment: {details.splitlines()[-1]}")
    testcase.fail(details or f"CLI exited with status {result.returncode}")


def resolve_cli() -> list[str]:
    installed = shutil.which("cli-anything-mubu")
    if installed:
        return [installed]
    return [sys.executable, "-m", "cli_anything.mubu"]


@unittest.skipUnless(HAS_DAILY_FOLDER, SKIP_REASON)
class DiscoverE2ETests(unittest.TestCase):
    CLI_BASE = resolve_cli()

    def run_cli(self, args: list[str], extra_env: dict | None = None) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            self.CLI_BASE + args,
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )

    def test_docs_returns_json_list(self):
        result = self.run_cli(["docs", "--limit", "3", "--json"])
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        data = json.loads(result.stdout)
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)
        self.assertIn("doc_id", data[0])

    def test_folders_returns_json_list(self):
        result = self.run_cli(["folders", "--json"])
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        data = json.loads(result.stdout)
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)
        self.assertIn("folder_id", data[0])

    def test_recent_returns_json_list(self):
        result = self.run_cli(["recent", "--limit", "3", "--json"])
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        data = json.loads(result.stdout)
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)

    def test_daily_current_returns_doc_path(self):
        result = self.run_cli(
            ["daily-current", "--json"],
            extra_env={"MUBU_DAILY_FOLDER": DETECTED_DAILY_FOLDER_REF},
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        data = json.loads(result.stdout)
        # Response wraps document info in a nested structure
        doc = data.get("document", data)
        self.assertIn("doc_path", doc)
        self.assertIn(DETECTED_DAILY_FOLDER_REF, doc["doc_path"])


@unittest.skipUnless(HAS_DAILY_FOLDER, SKIP_REASON)
class InspectE2ETests(unittest.TestCase):
    CLI_BASE = resolve_cli()

    def run_cli(self, args: list[str], extra_env: dict | None = None) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            self.CLI_BASE + args,
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )

    def test_search_finds_results(self):
        result = self.run_cli(["search", "日", "--limit", "3", "--json"])
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        data = json.loads(result.stdout)
        self.assertIsInstance(data, list)

    def test_daily_nodes_returns_node_list(self):
        result = self.run_cli(
            ["daily-nodes", "--json"],
            extra_env={"MUBU_DAILY_FOLDER": DETECTED_DAILY_FOLDER_REF},
        )
        assert_cli_success_or_skip(self, result)
        data = json.loads(result.stdout)
        self.assertIn("nodes", data)
        self.assertIsInstance(data["nodes"], list)


@unittest.skipUnless(HAS_DAILY_FOLDER, SKIP_REASON)
class SessionE2ETests(unittest.TestCase):
    CLI_BASE = resolve_cli()

    def run_cli(self, args: list[str], input_text: str | None = None, extra_env: dict | None = None) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            self.CLI_BASE + args,
            input=input_text,
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )

    def test_session_use_daily_sets_current_doc(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {
                "CLI_ANYTHING_MUBU_STATE_DIR": tmpdir,
                "MUBU_DAILY_FOLDER": DETECTED_DAILY_FOLDER_REF,
            }
            self.run_cli(["session", "use-daily"], extra_env=env)
            result = self.run_cli(["session", "status", "--json"], extra_env=env)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            data = json.loads(result.stdout)
            self.assertIsNotNone(data.get("current_doc"))
            self.assertIn(DETECTED_DAILY_FOLDER_REF, data["current_doc"])

    def test_repl_use_daily_then_daily_nodes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {
                "CLI_ANYTHING_MUBU_STATE_DIR": tmpdir,
                "MUBU_DAILY_FOLDER": DETECTED_DAILY_FOLDER_REF,
            }
            result = self.run_cli(
                [],
                input_text="use-daily\ndaily-nodes --json\nexit\n",
                extra_env=env,
            )
            assert_cli_success_or_skip(self, result)
            self.assertIn('"nodes"', result.stdout)


@unittest.skipUnless(HAS_DAILY_FOLDER, SKIP_REASON)
class MutateDryRunE2ETests(unittest.TestCase):
    """Test mutation commands in dry-run mode (no --execute)."""

    CLI_BASE = resolve_cli()

    def run_cli(self, args: list[str], extra_env: dict | None = None) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            self.CLI_BASE + args,
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )

    def _resolve_daily_node(self) -> tuple[str, str]:
        """Helper: get a stable daily document reference and first node id."""
        result = self.run_cli(
            ["daily-nodes", "--json"],
            extra_env={"MUBU_DAILY_FOLDER": DETECTED_DAILY_FOLDER_REF},
        )
        assert_cli_success_or_skip(self, result)
        current_payload = json.loads(result.stdout)
        current_doc = current_payload.get("document", current_payload)
        candidate_doc_refs: list[str] = []
        current_doc_ref = current_doc.get("doc_path") if isinstance(current_doc, dict) else None
        if isinstance(current_doc_ref, str) and current_doc_ref:
            candidate_doc_refs.append(current_doc_ref)
        for doc_ref in PRIORITIZED_DAILY_DOC_REFS:
            if doc_ref not in candidate_doc_refs:
                candidate_doc_refs.append(doc_ref)

        for doc_ref in candidate_doc_refs:
            if doc_ref == current_doc_ref:
                payload = current_payload
            else:
                doc_nodes = self.run_cli(["doc-nodes", doc_ref, "--json"])
                assert_cli_success_or_skip(self, doc_nodes)
                payload = json.loads(doc_nodes.stdout)

            for item in payload.get("nodes", []):
                node_id = item.get("node_id")
                if isinstance(node_id, str) and node_id:
                    return doc_ref, node_id

        self.skipTest("no daily document with pickable nodes found in local Mubu data")

    def test_update_text_dry_run(self):
        doc_ref, node_id = self._resolve_daily_node()
        result = self.run_cli([
            "update-text", doc_ref,
            "--node-id", node_id,
            "--text", "dry run test",
            "--json",
        ])
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        data = json.loads(result.stdout)
        self.assertIn("request", data)
        self.assertFalse(data.get("executed", False))

    def test_create_child_dry_run(self):
        doc_ref, node_id = self._resolve_daily_node()
        result = self.run_cli([
            "create-child", doc_ref,
            "--parent-node-id", node_id,
            "--text", "dry run child",
            "--json",
        ])
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        data = json.loads(result.stdout)
        self.assertIn("request", data)
        self.assertFalse(data.get("executed", False))

    def test_delete_node_dry_run(self):
        doc_ref, node_id = self._resolve_daily_node()
        result = self.run_cli([
            "delete-node", doc_ref,
            "--node-id", node_id,
            "--json",
        ])
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        data = json.loads(result.stdout)
        self.assertFalse(data.get("executed", False))


@unittest.skipUnless(HAS_DAILY_FOLDER, SKIP_REASON)
class WorkflowE2ETests(unittest.TestCase):
    CLI_BASE = resolve_cli()

    def run_cli(self, args: list[str], extra_env: dict | None = None) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            self.CLI_BASE + args,
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )

    def _resolve_pickable_daily_node(self) -> tuple[str, str]:
        result = self.run_cli(
            ["daily-nodes", "--json"],
            extra_env={"MUBU_DAILY_FOLDER": DETECTED_DAILY_FOLDER_REF},
        )
        assert_cli_success_or_skip(self, result)
        data = json.loads(result.stdout)
        doc = data.get("document", data)
        doc_ref = doc["doc_path"]
        for item in data.get("nodes", []):
            if item.get("node_id") and (item.get("text") or item.get("note") or item.get("child_count", 0) >= 0):
                return doc_ref, item["node_id"]
        self.skipTest("no pickable daily node found in current daily document")

    def test_workflow_daily_open_sets_current_doc(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {
                "CLI_ANYTHING_MUBU_STATE_DIR": tmpdir,
                "MUBU_DAILY_FOLDER": DETECTED_DAILY_FOLDER_REF,
            }
            result = self.run_cli(["workflow", "daily-open", "--json"], extra_env=env)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            data = json.loads(result.stdout)
            self.assertIsNone(data.get("current_node"))
            self.assertIn(DETECTED_DAILY_FOLDER_REF, data["current_doc"])

    def test_workflow_today_scan_returns_actionable_sections(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {
                "CLI_ANYTHING_MUBU_STATE_DIR": tmpdir,
                "MUBU_DAILY_FOLDER": DETECTED_DAILY_FOLDER_REF,
            }
            result = self.run_cli(["workflow", "today-scan", "--json"], extra_env=env)
            assert_cli_success_or_skip(self, result)
            data = json.loads(result.stdout)
            self.assertIn("document", data)
            self.assertIn(DETECTED_DAILY_FOLDER_REF, data["document"]["doc_path"])
            self.assertIn("sections", data)
            self.assertIsInstance(data["sections"], list)
            self.assertIn("strategy", data)
            self.assertIn("actionable_total", data["strategy"])
            self.assertEqual(data["current_doc"], data["document"]["doc_path"])
            self.assertIsNone(data["current_node"])

    def test_workflow_pick_ctx_and_append_dry_run(self):
        doc_ref, node_id = self._resolve_pickable_daily_node()
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {
                "CLI_ANYTHING_MUBU_STATE_DIR": tmpdir,
                "MUBU_DAILY_FOLDER": DETECTED_DAILY_FOLDER_REF,
            }
            open_result = self.run_cli(["workflow", "daily-open", "--json"], extra_env=env)
            self.assertEqual(open_result.returncode, 0, msg=open_result.stderr)

            pick_result = self.run_cli(
                ["workflow", "pick", "--doc-ref", doc_ref, "--node-id", node_id, "--json"],
                extra_env=env,
            )
            assert_cli_success_or_skip(self, pick_result)
            pick_data = json.loads(pick_result.stdout)
            self.assertEqual(pick_data["current_node"], node_id)

            ctx_result = self.run_cli(["workflow", "ctx", "--json"], extra_env=env)
            assert_cli_success_or_skip(self, ctx_result)
            ctx_data = json.loads(ctx_result.stdout)
            self.assertEqual(ctx_data["target"]["node_id"], node_id)

            append_result = self.run_cli(
                ["workflow", "append", "--text", "workflow dry run child", "--json"],
                extra_env=env,
            )
            assert_cli_success_or_skip(self, append_result)
            append_data = json.loads(append_result.stdout)
            self.assertFalse(append_data.get("execute", True))
            self.assertEqual(append_data["target_parent"]["node_id"], node_id)
            self.assertIn("request", append_data)

    def test_workflow_capture_dry_run_with_explicit_parent(self):
        _doc_ref, node_id = self._resolve_pickable_daily_node()
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {
                "CLI_ANYTHING_MUBU_STATE_DIR": tmpdir,
                "MUBU_DAILY_FOLDER": DETECTED_DAILY_FOLDER_REF,
            }
            result = self.run_cli(
                ["workflow", "capture", "--daily", "--parent-node-id", node_id, "--text", "workflow capture dry run", "--json"],
                extra_env=env,
            )
            assert_cli_success_or_skip(self, result)
            data = json.loads(result.stdout)
            self.assertFalse(data.get("execute", True))
            self.assertEqual(data["target_parent"]["node_id"], node_id)
            self.assertIn(DETECTED_DAILY_FOLDER_REF, data["current_doc"])


if __name__ == "__main__":
    unittest.main()
