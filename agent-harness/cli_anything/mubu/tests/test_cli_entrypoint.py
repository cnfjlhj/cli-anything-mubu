import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from cli_anything.mubu.mubu_cli import (
    dispatch,
    expand_repl_aliases_with_state,
    load_session_state,
    repl_help_text,
    save_session_state,
    session_state_dir,
)
from mubu_probe import (
    DEFAULT_BACKUP_ROOT,
    DEFAULT_STORAGE_ROOT,
    build_folder_indexes,
    choose_current_daily_document,
    load_document_metas,
    load_folders,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
SAMPLE_DOC_REF = "workspace/reference docs/sample-doc"
SAMPLE_NODE_ID = "node-sample-1"
HAS_LOCAL_DATA = DEFAULT_BACKUP_ROOT.is_dir() and DEFAULT_STORAGE_ROOT.is_dir()


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


def resolve_cli() -> list[str]:
    installed = shutil.which("cli-anything-mubu")
    if installed:
        return [installed]
    return [sys.executable, "-m", "cli_anything.mubu"]


class CliEntrypointTests(unittest.TestCase):
    CLI_BASE = resolve_cli()

    def setUp(self):
        self._state_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._state_dir.cleanup)
        self.default_env = {"CLI_ANYTHING_MUBU_STATE_DIR": self._state_dir.name}

    def run_cli(self, args, input_text=None, extra_env=None):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        env.update(self.default_env)
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            self.CLI_BASE + args,
            input=input_text,
            capture_output=True,
            text=True,
            env=env,
        )

    def test_help_renders_root_commands(self):
        result = self.run_cli(["--help"])
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("discover", result.stdout)
        self.assertIn("inspect", result.stdout)
        self.assertIn("mutate", result.stdout)
        self.assertIn("session", result.stdout)
        self.assertIn("workflow", result.stdout)
        self.assertIn("doctor", result.stdout)
        self.assertIn("verify", result.stdout)
        self.assertIn("daily-current", result.stdout)
        self.assertIn("create-child", result.stdout)
        self.assertIn("delete-node", result.stdout)

    def test_dispatch_uses_public_prog_name_when_requested(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            result = dispatch(["--help"], prog_name="mubu-cli")
        self.assertEqual(result, 0)
        self.assertIn("Usage: mubu-cli", stdout.getvalue())

    def test_dispatch_uses_compat_prog_name_when_requested(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            result = dispatch(["--help"], prog_name="cli-anything-mubu")
        self.assertEqual(result, 0)
        self.assertIn("Usage: cli-anything-mubu", stdout.getvalue())

    def test_repl_help_renders(self):
        result = self.run_cli(["repl", "--help"])
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("Interactive REPL", result.stdout)
        self.assertIn("use-node", result.stdout)

    def test_workflow_help_includes_today_scan(self):
        result = self.run_cli(["workflow", "--help"])
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("today-scan", result.stdout)
        self.assertIn("today-start", result.stdout)

    def test_repl_help_text_supports_public_brand(self):
        self.assertIn("mubu-cli", repl_help_text("mubu-cli"))

    def test_session_state_dir_defaults_to_public_brand_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            with (
                mock.patch.dict(os.environ, {}, clear=False),
                mock.patch("cli_anything.mubu.mubu_cli.Path.home", return_value=home),
            ):
                self.assertEqual(session_state_dir(), home / ".config" / "mubu-cli")

    def test_session_state_dir_falls_back_to_legacy_path_when_only_legacy_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            legacy = home / ".config" / "cli-anything-mubu"
            legacy.mkdir(parents=True)
            with (
                mock.patch.dict(os.environ, {}, clear=False),
                mock.patch("cli_anything.mubu.mubu_cli.Path.home", return_value=home),
            ):
                self.assertEqual(session_state_dir(), legacy)

    def test_default_entrypoint_starts_repl_and_can_exit(self):
        result = self.run_cli([], input_text="exit\n")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("Mubu REPL", result.stdout)

    def test_default_entrypoint_banner_includes_skill_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_cli(
                [],
                input_text="exit\n",
                extra_env={"CLI_ANYTHING_MUBU_STATE_DIR": tmpdir},
            )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("Skill:", result.stdout)
        self.assertIn(
            str(REPO_ROOT / "agent-harness" / "cli_anything" / "mubu" / "skills" / "SKILL.md"),
            result.stdout,
        )

    def test_repl_can_store_current_doc_reference(self):
        result = self.run_cli(
            [],
            input_text=f"use-doc '{SAMPLE_DOC_REF}'\ncurrent-doc\nexit\n",
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn(f"Current doc: {SAMPLE_DOC_REF}", result.stdout)

    def test_repl_can_store_current_node_reference(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_cli(
                [],
                input_text=f"use-node {SAMPLE_NODE_ID}\ncurrent-node\nexit\n",
                extra_env={"CLI_ANYTHING_MUBU_STATE_DIR": tmpdir},
            )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn(f"Current node: {SAMPLE_NODE_ID}", result.stdout)

    def test_repl_persists_current_doc_between_processes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {"CLI_ANYTHING_MUBU_STATE_DIR": tmpdir}

            first = self.run_cli(
                [],
                input_text=f"use-doc '{SAMPLE_DOC_REF}'\nexit\n",
                extra_env=env,
            )
            self.assertEqual(first.returncode, 0, msg=first.stderr)

            second = self.run_cli(
                [],
                input_text="current-doc\nexit\n",
                extra_env=env,
            )
            self.assertEqual(second.returncode, 0, msg=second.stderr)
            self.assertIn(f"Current doc: {SAMPLE_DOC_REF}", second.stdout)

    def test_repl_persists_current_node_between_processes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {"CLI_ANYTHING_MUBU_STATE_DIR": tmpdir}

            first = self.run_cli(
                [],
                input_text=f"use-node {SAMPLE_NODE_ID}\nexit\n",
                extra_env=env,
            )
            self.assertEqual(first.returncode, 0, msg=first.stderr)

            second = self.run_cli(
                [],
                input_text="current-node\nexit\n",
                extra_env=env,
            )
            self.assertEqual(second.returncode, 0, msg=second.stderr)
            self.assertIn(f"Current node: {SAMPLE_NODE_ID}", second.stdout)

    def test_repl_aliases_expand_current_doc_and_node(self):
        expanded = expand_repl_aliases_with_state(
            ["delete-node", "@doc", "--node-id", "@node", "--from", "@current"],
            {"current_doc": SAMPLE_DOC_REF, "current_node": SAMPLE_NODE_ID},
        )
        self.assertEqual(
            expanded,
            ["delete-node", SAMPLE_DOC_REF, "--node-id", SAMPLE_NODE_ID, "--from", SAMPLE_DOC_REF],
        )

    def test_repl_clear_doc_persists_between_processes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {"CLI_ANYTHING_MUBU_STATE_DIR": tmpdir}

            self.run_cli(
                [],
                input_text=f"use-doc '{SAMPLE_DOC_REF}'\nexit\n",
                extra_env=env,
            )

            cleared = self.run_cli(
                [],
                input_text="clear-doc\nexit\n",
                extra_env=env,
            )
            self.assertEqual(cleared.returncode, 0, msg=cleared.stderr)

            final = self.run_cli(
                [],
                input_text="current-doc\nexit\n",
                extra_env=env,
            )
            self.assertEqual(final.returncode, 0, msg=final.stderr)
            self.assertIn("Current doc: <unset>", final.stdout)

    def test_repl_clear_node_persists_between_processes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {"CLI_ANYTHING_MUBU_STATE_DIR": tmpdir}

            self.run_cli(
                [],
                input_text=f"use-node {SAMPLE_NODE_ID}\nexit\n",
                extra_env=env,
            )

            cleared = self.run_cli(
                [],
                input_text="clear-node\nexit\n",
                extra_env=env,
            )
            self.assertEqual(cleared.returncode, 0, msg=cleared.stderr)

            final = self.run_cli(
                [],
                input_text="current-node\nexit\n",
                extra_env=env,
            )
            self.assertEqual(final.returncode, 0, msg=final.stderr)
            self.assertIn("Current node: <unset>", final.stdout)

    @unittest.skipUnless(HAS_DAILY_FOLDER, "Mubu local data or daily folder not found")
    def test_grouped_discover_daily_current_supports_global_json_flag(self):
        missing = self.run_cli(["--json", "discover", "daily-current"])
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("MUBU_DAILY_FOLDER", missing.stderr)

        result = self.run_cli(
            ["--json", "discover", "daily-current"],
            extra_env={"MUBU_DAILY_FOLDER": DETECTED_DAILY_FOLDER_REF},
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn('"doc_path"', result.stdout)

    def test_session_status_reports_json_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {"CLI_ANYTHING_MUBU_STATE_DIR": tmpdir}
            self.run_cli(
                ["session", "use-doc", SAMPLE_DOC_REF],
                extra_env=env,
            )
            self.run_cli(
                ["session", "use-node", SAMPLE_NODE_ID],
                extra_env=env,
            )
            result = self.run_cli(
                ["session", "status", "--json"],
                extra_env=env,
            )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn(f'"current_doc": "{SAMPLE_DOC_REF}"', result.stdout)
        self.assertIn(f'"current_node": "{SAMPLE_NODE_ID}"', result.stdout)

    def test_verify_command_delegates_to_packaged_verifier(self):
        with mock.patch("cli_anything.mubu.mubu_cli.run_packaged_verify", return_value=0) as verify_mock:
            result = dispatch(["verify", "--skip-live", "--json"], prog_name="mubu-cli")
        self.assertEqual(result, 0)
        verify_mock.assert_called_once_with(["--skip-live", "--json"])

    def test_doctor_reports_json_health(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {"CLI_ANYTHING_MUBU_STATE_DIR": tmpdir}
            backup_root = Path(tmpdir) / "backup"
            storage_root = Path(tmpdir) / ".storage"
            log_root = Path(tmpdir) / "log"
            backup_root.mkdir()
            storage_root.mkdir()
            log_root.mkdir()

            stdout = io.StringIO()
            with (
                mock.patch.dict(os.environ, env, clear=False),
                mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.DEFAULT_BACKUP_ROOT", backup_root),
                mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.DEFAULT_STORAGE_ROOT", storage_root),
                mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.DEFAULT_LOG_ROOT", log_root),
                mock.patch(
                    "cli_anything.mubu.mubu_cli.mubu_probe.get_active_user",
                    return_value={"user_id": "user-1", "display_name": "Test User", "token": "secret"},
                ),
                mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.resolve_daily_folder_ref", return_value="博一/Daily tasks"),
                mock.patch("cli_anything.mubu.mubu_cli.resolve_current_daily_doc_ref", return_value="博一/Daily tasks/26.3.22"),
                contextlib.redirect_stdout(stdout),
            ):
                result = dispatch(["doctor", "--json"], prog_name="mubu-cli")

        self.assertEqual(result, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["checks"]["backup_root"]["ok"])
        self.assertTrue(payload["checks"]["storage_root"]["ok"])
        self.assertTrue(payload["checks"]["log_root"]["ok"])
        self.assertTrue(payload["checks"]["session_dir"]["ok"])
        self.assertTrue(payload["checks"]["active_user"]["ok"])
        self.assertEqual(payload["checks"]["active_user"]["user_id"], "user-1")
        self.assertTrue(payload["checks"]["daily_folder"]["ok"])
        self.assertEqual(payload["checks"]["daily_folder"]["resolved_folder_ref"], "博一/Daily tasks")
        self.assertEqual(payload["checks"]["daily_folder"]["resolved_doc_ref"], "博一/Daily tasks/26.3.22")
        self.assertIn("state_path", payload["session"])

    def test_workflow_daily_open_updates_session_and_clears_current_node(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {"CLI_ANYTHING_MUBU_STATE_DIR": tmpdir}
            with mock.patch.dict(os.environ, env, clear=False):
                session_state = load_session_state()
                session_state["current_node"] = SAMPLE_NODE_ID
                save_session_state(session_state)

                stdout = io.StringIO()
                with (
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.resolve_daily_folder_ref", return_value="Workspace/Daily"),
                    mock.patch("cli_anything.mubu.mubu_cli.resolve_current_daily_doc_ref", return_value=SAMPLE_DOC_REF),
                    contextlib.redirect_stdout(stdout),
                ):
                    result = dispatch(["workflow", "daily-open", "--json"], prog_name="mubu-cli")

                self.assertEqual(result, 0)
                payload = json.loads(stdout.getvalue())
                self.assertEqual(payload["current_doc"], SAMPLE_DOC_REF)
                self.assertIsNone(payload["current_node"])
                self.assertEqual(payload["resolved_folder_ref"], "Workspace/Daily")

                persisted = load_session_state()
                self.assertEqual(persisted["current_doc"], SAMPLE_DOC_REF)
                self.assertIsNone(persisted["current_node"])

    def test_workflow_today_scan_resolves_daily_and_extracts_task_sections(self):
        remote_doc = {
            "baseVersion": 7,
            "definition": json.dumps(
                {
                    "nodes": [
                        {"id": "ddl-root", "text": "<span>DDL表(To Do List)</span>", "children": []},
                        {
                            "id": "record-root",
                            "text": "<span>记录-今天做了啥（计划做啥）</span>",
                            "children": [
                                {
                                    "id": "log-root",
                                    "text": "<span>日志流</span>",
                                    "children": [
                                        {
                                            "id": "ing-root",
                                            "text": "<span>ing</span>",
                                            "children": [
                                                {"id": "ing-1", "text": "<span>正在处理的事</span>", "children": []}
                                            ],
                                        },
                                        {
                                            "id": "main-root",
                                            "text": "<span>主线（最多三条）</span>",
                                            "children": [
                                                {"id": "main-1", "text": "<span>整理，更新</span>", "children": []},
                                                {"id": "main-2", "text": "<span>看现代科研指北</span>", "children": []},
                                            ],
                                        },
                                        {
                                            "id": "todo-root",
                                            "text": "<span>todo</span>",
                                            "children": [
                                                {"id": "todo-1", "text": "<span>去看一下 cron 相关内容</span>", "children": []}
                                            ],
                                        },
                                    ],
                                }
                            ],
                        },
                    ]
                }
            ),
        }
        meta = {"doc_id": "doc-1", "doc_path": SAMPLE_DOC_REF, "title": "Sample Doc"}

        with tempfile.TemporaryDirectory() as tmpdir:
            env = {"CLI_ANYTHING_MUBU_STATE_DIR": tmpdir}
            with mock.patch.dict(os.environ, env, clear=False):
                stdout = io.StringIO()
                with (
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.resolve_daily_folder_ref", return_value="Workspace/Daily"),
                    mock.patch("cli_anything.mubu.mubu_cli.resolve_current_daily_doc_ref", return_value=SAMPLE_DOC_REF),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.load_document_metas", return_value=[meta]),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.load_folders", return_value=[]),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.resolve_document_reference", return_value=(meta, [])),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.get_active_user", return_value={"token": "t", "user_id": "u"}),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.fetch_document_remote", return_value=remote_doc),
                    contextlib.redirect_stdout(stdout),
                ):
                    result = dispatch(["workflow", "today-scan", "--json"], prog_name="mubu-cli")

                self.assertEqual(result, 0)
                payload = json.loads(stdout.getvalue())
                self.assertEqual(payload["resolved_folder_ref"], "Workspace/Daily")
                self.assertEqual(payload["document"]["doc_path"], SAMPLE_DOC_REF)
                self.assertEqual(payload["current_doc"], SAMPLE_DOC_REF)
                self.assertIsNone(payload["current_node"])
                self.assertEqual(payload["strategy"]["task_root"]["text"], "日志流")
                self.assertEqual([section["name"] for section in payload["sections"]], ["main", "todo", "ing"])
                self.assertEqual(payload["sections"][0]["items"][0]["text"], "整理，更新")
                self.assertEqual(payload["sections"][1]["items"][0]["text"], "去看一下 cron 相关内容")
                self.assertEqual(payload["sections"][2]["items"][0]["text"], "正在处理的事")

                persisted = load_session_state()
                self.assertEqual(persisted["current_doc"], SAMPLE_DOC_REF)
                self.assertIsNone(persisted["current_node"])

    def test_workflow_today_scan_skips_blank_task_items(self):
        remote_doc = {
            "baseVersion": 7,
            "definition": json.dumps(
                {
                    "nodes": [
                        {
                            "id": "record-root",
                            "text": "<span>记录-今天做了啥（计划做啥）</span>",
                            "children": [
                                {
                                    "id": "log-root",
                                    "text": "<span>日志流</span>",
                                    "children": [
                                        {
                                            "id": "todo-root",
                                            "text": "<span>todo</span>",
                                            "children": [
                                                {"id": "todo-1", "text": "<span>有效任务</span>", "children": []},
                                                {"id": "todo-blank", "text": "", "note": "", "children": []},
                                            ],
                                        }
                                    ],
                                }
                            ],
                        }
                    ]
                }
            ),
        }
        meta = {"doc_id": "doc-1", "doc_path": SAMPLE_DOC_REF, "title": "Sample Doc"}

        with tempfile.TemporaryDirectory() as tmpdir:
            env = {"CLI_ANYTHING_MUBU_STATE_DIR": tmpdir}
            with mock.patch.dict(os.environ, env, clear=False):
                stdout = io.StringIO()
                with (
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.resolve_daily_folder_ref", return_value="Workspace/Daily"),
                    mock.patch("cli_anything.mubu.mubu_cli.resolve_current_daily_doc_ref", return_value=SAMPLE_DOC_REF),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.load_document_metas", return_value=[meta]),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.load_folders", return_value=[]),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.resolve_document_reference", return_value=(meta, [])),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.get_active_user", return_value={"token": "t", "user_id": "u"}),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.fetch_document_remote", return_value=remote_doc),
                    contextlib.redirect_stdout(stdout),
                ):
                    result = dispatch(["workflow", "today-scan", "--json"], prog_name="mubu-cli")

                self.assertEqual(result, 0)
                payload = json.loads(stdout.getvalue())
                self.assertEqual(len(payload["sections"]), 1)
                self.assertEqual(len(payload["sections"][0]["items"]), 1)
                self.assertEqual(payload["sections"][0]["items"][0]["text"], "有效任务")

    def test_workflow_today_start_creates_today_doc_from_latest_template_source(self):
        docs = [
            {
                "doc_id": "doc-template",
                "folder_id": "dailyA",
                "title": "26.3.22模板",
                "updated_at": 130,
                "doc_path": "Workspace/Daily/26.3.22模板",
            },
            {
                "doc_id": "doc-yesterday",
                "folder_id": "dailyA",
                "title": "26.3.22",
                "updated_at": 120,
                "doc_path": "Workspace/Daily/26.3.22",
            },
            {
                "doc_id": "doc-older",
                "folder_id": "dailyA",
                "title": "26.3.21",
                "updated_at": 110,
                "doc_path": "Workspace/Daily/26.3.21",
            },
        ]
        folders = [
            {"folder_id": "rootA", "name": "Workspace", "parent_id": "0", "path": "Workspace"},
            {"folder_id": "dailyA", "name": "Daily", "parent_id": "rootA", "path": "Workspace/Daily"},
        ]
        copy_result = {
            "execute": True,
            "request": {"pathname": "/v3/api/list/copy_doc", "method": "POST", "data": {"id": "doc-template"}},
            "response": {
                "code": 0,
                "data": {"id": "doc-new", "name": "26.3.22模板-副本", "folderId": "dailyA"},
            },
        }
        rename_result = {
            "execute": True,
            "request": {
                "pathname": "/v3/api/list/rename_doc",
                "method": "POST",
                "data": {"documentId": "doc-new", "name": "26.3.23"},
            },
            "response": {"code": 0, "data": {"version": 1774244877030}},
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            env = {"CLI_ANYTHING_MUBU_STATE_DIR": tmpdir}
            with mock.patch.dict(os.environ, env, clear=False):
                stdout = io.StringIO()
                with (
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.resolve_daily_folder_ref", return_value="Workspace/Daily"),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.load_document_metas", return_value=docs),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.load_folders", return_value=folders),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.current_local_date", return_value=date(2026, 3, 23)),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.get_active_user", return_value={"token": "t", "user_id": "u"}),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.perform_copy_document", return_value=copy_result),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.perform_rename_document", return_value=rename_result),
                    contextlib.redirect_stdout(stdout),
                ):
                    result = dispatch(["workflow", "today-start", "--json"], prog_name="mubu-cli")

                self.assertEqual(result, 0)
                payload = json.loads(stdout.getvalue())
                self.assertTrue(payload["created"])
                self.assertEqual(payload["today_title"], "26.3.23")
                self.assertEqual(payload["template_source"]["doc_id"], "doc-template")
                self.assertEqual(payload["document"]["doc_id"], "doc-new")
                self.assertEqual(payload["current_doc"], "doc-new")
                self.assertIsNone(payload["current_node"])

                persisted = load_session_state()
                self.assertEqual(persisted["current_doc"], "doc-new")
                self.assertIsNone(persisted["current_node"])

    def test_workflow_today_start_reuses_existing_today_doc_without_copying(self):
        docs = [
            {
                "doc_id": "doc-today",
                "folder_id": "dailyA",
                "title": "26.3.23",
                "updated_at": 140,
                "doc_path": "Workspace/Daily/26.3.23",
            },
            {
                "doc_id": "doc-template",
                "folder_id": "dailyA",
                "title": "26.3.22模板",
                "updated_at": 130,
                "doc_path": "Workspace/Daily/26.3.22模板",
            },
        ]
        folders = [
            {"folder_id": "rootA", "name": "Workspace", "parent_id": "0", "path": "Workspace"},
            {"folder_id": "dailyA", "name": "Daily", "parent_id": "rootA", "path": "Workspace/Daily"},
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            env = {"CLI_ANYTHING_MUBU_STATE_DIR": tmpdir}
            with mock.patch.dict(os.environ, env, clear=False):
                stdout = io.StringIO()
                with (
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.resolve_daily_folder_ref", return_value="Workspace/Daily"),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.load_document_metas", return_value=docs),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.load_folders", return_value=folders),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.current_local_date", return_value=date(2026, 3, 23)),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.perform_copy_document") as copy_mock,
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.perform_rename_document") as rename_mock,
                    contextlib.redirect_stdout(stdout),
                ):
                    result = dispatch(["workflow", "today-start", "--json"], prog_name="mubu-cli")

                self.assertEqual(result, 0)
                payload = json.loads(stdout.getvalue())
                self.assertFalse(payload["created"])
                self.assertEqual(payload["document"]["doc_id"], "doc-today")
                self.assertEqual(payload["document"]["doc_path"], "Workspace/Daily/26.3.23")
                self.assertEqual(payload["current_doc"], "Workspace/Daily/26.3.23")
                copy_mock.assert_not_called()
                rename_mock.assert_not_called()

                persisted = load_session_state()
                self.assertEqual(persisted["current_doc"], "Workspace/Daily/26.3.23")
                self.assertIsNone(persisted["current_node"])

    def test_workflow_today_start_reuses_current_session_doc_before_local_metadata_sync(self):
        docs = [
            {
                "doc_id": "doc-template",
                "folder_id": "dailyA",
                "title": "26.3.22模板",
                "updated_at": 130,
                "doc_path": "Workspace/Daily/26.3.22模板",
            },
            {
                "doc_id": "doc-yesterday",
                "folder_id": "dailyA",
                "title": "26.3.22",
                "updated_at": 120,
                "doc_path": "Workspace/Daily/26.3.22",
            },
        ]
        folders = [
            {"folder_id": "rootA", "name": "Workspace", "parent_id": "0", "path": "Workspace"},
            {"folder_id": "dailyA", "name": "Daily", "parent_id": "rootA", "path": "Workspace/Daily"},
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            env = {"CLI_ANYTHING_MUBU_STATE_DIR": tmpdir}
            with mock.patch.dict(os.environ, env, clear=False):
                session_state = load_session_state()
                session_state["current_doc"] = "doc-new"
                save_session_state(session_state)

                stdout = io.StringIO()
                with (
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.resolve_daily_folder_ref", return_value="Workspace/Daily"),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.load_document_metas", return_value=docs),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.load_folders", return_value=folders),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.current_local_date", return_value=date(2026, 3, 23)),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.get_active_user", return_value={"token": "t", "user_id": "u"}),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.fetch_document_name", return_value="26.3.23"),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.perform_copy_document") as copy_mock,
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.perform_rename_document") as rename_mock,
                    contextlib.redirect_stdout(stdout),
                ):
                    result = dispatch(["workflow", "today-start", "--json"], prog_name="mubu-cli")

                self.assertEqual(result, 0)
                payload = json.loads(stdout.getvalue())
                self.assertFalse(payload["created"])
                self.assertEqual(payload["document"]["doc_id"], "doc-new")
                self.assertEqual(payload["current_doc"], "doc-new")
                copy_mock.assert_not_called()
                rename_mock.assert_not_called()

                persisted = load_session_state()
                self.assertEqual(persisted["current_doc"], "doc-new")
                self.assertIsNone(persisted["current_node"])

    def test_workflow_pick_uses_current_doc_and_updates_current_node(self):
        remote_doc = {
            "baseVersion": 7,
            "definition": json.dumps(
                {
                    "nodes": [
                        {
                            "id": SAMPLE_NODE_ID,
                            "text": "<span>谢赛宁 七小时马拉松访谈</span>",
                            "children": [],
                        }
                    ]
                }
            ),
        }
        meta = {"doc_id": "doc-1", "doc_path": SAMPLE_DOC_REF, "title": "Sample Doc"}

        with tempfile.TemporaryDirectory() as tmpdir:
            env = {"CLI_ANYTHING_MUBU_STATE_DIR": tmpdir}
            with mock.patch.dict(os.environ, env, clear=False):
                session_state = load_session_state()
                session_state["current_doc"] = SAMPLE_DOC_REF
                save_session_state(session_state)

                stdout = io.StringIO()
                with (
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.load_document_metas", return_value=[meta]),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.load_folders", return_value=[]),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.resolve_document_reference", return_value=(meta, [])),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.get_active_user", return_value={"token": "t", "user_id": "u"}),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.fetch_document_remote", return_value=remote_doc),
                    contextlib.redirect_stdout(stdout),
                ):
                    result = dispatch(["workflow", "pick", "谢赛宁", "--json"], prog_name="mubu-cli")

                self.assertEqual(result, 0)
                payload = json.loads(stdout.getvalue())
                self.assertEqual(payload["current_doc"], SAMPLE_DOC_REF)
                self.assertEqual(payload["current_node"], SAMPLE_NODE_ID)
                self.assertEqual(payload["match_count"], 1)
                self.assertEqual(payload["selected"]["node_id"], SAMPLE_NODE_ID)

                persisted = load_session_state()
                self.assertEqual(persisted["current_node"], SAMPLE_NODE_ID)

    def test_workflow_pick_accepts_query_option_alias(self):
        remote_doc = {
            "baseVersion": 7,
            "definition": json.dumps(
                {
                    "nodes": [
                        {
                            "id": SAMPLE_NODE_ID,
                            "text": "<span>2026年</span>",
                            "children": [],
                        }
                    ]
                }
            ),
        }
        meta = {"doc_id": "doc-1", "doc_path": SAMPLE_DOC_REF, "title": "Sample Doc"}

        with tempfile.TemporaryDirectory() as tmpdir:
            env = {"CLI_ANYTHING_MUBU_STATE_DIR": tmpdir}
            with mock.patch.dict(os.environ, env, clear=False):
                session_state = load_session_state()
                session_state["current_doc"] = SAMPLE_DOC_REF
                save_session_state(session_state)

                stdout = io.StringIO()
                with (
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.load_document_metas", return_value=[meta]),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.load_folders", return_value=[]),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.resolve_document_reference", return_value=(meta, [])),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.get_active_user", return_value={"token": "t", "user_id": "u"}),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.fetch_document_remote", return_value=remote_doc),
                    contextlib.redirect_stdout(stdout),
                ):
                    result = dispatch(["workflow", "pick", "--query", "2026年", "--json"], prog_name="mubu-cli")

                self.assertEqual(result, 0)
                payload = json.loads(stdout.getvalue())
                self.assertEqual(payload["query"], "2026年")
                self.assertEqual(payload["current_doc"], SAMPLE_DOC_REF)
                self.assertEqual(payload["current_node"], SAMPLE_NODE_ID)
                self.assertEqual(payload["selected"]["node_id"], SAMPLE_NODE_ID)

                persisted = load_session_state()
                self.assertEqual(persisted["current_node"], SAMPLE_NODE_ID)

    def test_workflow_pick_rejects_positional_query_and_query_option_together(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            result = dispatch(
                ["workflow", "pick", "Inbox", "--query", "2026年"],
                prog_name="mubu-cli",
            )

        self.assertEqual(result, 2)
        self.assertIn("either a positional query or --query, not both", stderr.getvalue())

    def test_workflow_pick_accepts_backup_only_doc_id_reference(self):
        remote_doc = {
            "baseVersion": 7,
            "definition": json.dumps(
                {
                    "nodes": [
                        {
                            "id": SAMPLE_NODE_ID,
                            "text": "<span>2026年</span>",
                            "children": [],
                        }
                    ]
                }
            ),
        }

        with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as backup_tmp:
            env = {"CLI_ANYTHING_MUBU_STATE_DIR": tmpdir}
            backup_root = Path(backup_tmp)
            doc_dir = backup_root / "doc-backup-only"
            doc_dir.mkdir()
            (doc_dir / "2026-03-23 09'00.json").write_text(
                json.dumps(
                    {
                        "nodes": [
                            {
                                "id": "n1",
                                "text": "<span>Backup Only Title</span>",
                                "children": [],
                            }
                        ]
                    }
                )
            )

            with mock.patch.dict(os.environ, env, clear=False):
                stdout = io.StringIO()
                with (
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.DEFAULT_BACKUP_ROOT", backup_root),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.load_document_metas", return_value=[]),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.load_folders", return_value=[]),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.get_active_user", return_value={"token": "t", "user_id": "u"}),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.fetch_document_remote", return_value=remote_doc),
                    contextlib.redirect_stdout(stdout),
                ):
                    result = dispatch(
                        ["workflow", "pick", "--doc-ref", "doc-backup-only", "--query", "2026年", "--json"],
                        prog_name="mubu-cli",
                    )

                self.assertEqual(result, 0)
                payload = json.loads(stdout.getvalue())
                self.assertEqual(payload["document"]["doc_id"], "doc-backup-only")
                self.assertEqual(payload["document"]["doc_path"], "doc-backup-only")
                self.assertEqual(payload["document"]["title"], "Backup Only Title")
                self.assertEqual(payload["current_doc"], "doc-backup-only")
                self.assertEqual(payload["current_node"], SAMPLE_NODE_ID)

    def test_workflow_pick_persists_doc_id_for_root_metadata_match(self):
        remote_doc = {
            "baseVersion": 7,
            "definition": json.dumps(
                {
                    "nodes": [
                        {
                            "id": SAMPLE_NODE_ID,
                            "text": "<span>2026年</span>",
                            "children": [],
                        }
                    ]
                }
            ),
        }
        meta = {"doc_id": "doc-root", "folder_id": "0", "title": "Root Title", "updated_at": 20}

        with tempfile.TemporaryDirectory() as tmpdir:
            env = {"CLI_ANYTHING_MUBU_STATE_DIR": tmpdir}
            with mock.patch.dict(os.environ, env, clear=False):
                stdout = io.StringIO()
                with (
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.load_document_metas", return_value=[meta]),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.load_folders", return_value=[]),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.get_active_user", return_value={"token": "t", "user_id": "u"}),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.fetch_document_remote", return_value=remote_doc),
                    contextlib.redirect_stdout(stdout),
                ):
                    result = dispatch(
                        ["workflow", "pick", "--doc-ref", "doc-root", "--query", "2026年", "--json"],
                        prog_name="mubu-cli",
                    )

                self.assertEqual(result, 0)
                payload = json.loads(stdout.getvalue())
                self.assertEqual(payload["document"]["doc_id"], "doc-root")
                self.assertEqual(payload["document"]["title"], "Root Title")
                self.assertEqual(payload["current_doc"], "doc-root")
                self.assertEqual(payload["current_node"], SAMPLE_NODE_ID)

    def test_workflow_pick_can_list_candidates_without_mutating_session(self):
        remote_doc = {
            "baseVersion": 7,
            "definition": json.dumps(
                {
                    "nodes": [
                        {"id": "node-1", "text": "<span>Inbox alpha</span>", "children": []},
                        {"id": "node-2", "text": "<span>Inbox beta</span>", "children": []},
                    ]
                }
            ),
        }
        meta = {"doc_id": "doc-1", "doc_path": SAMPLE_DOC_REF, "title": "Sample Doc"}

        with tempfile.TemporaryDirectory() as tmpdir:
            env = {"CLI_ANYTHING_MUBU_STATE_DIR": tmpdir}
            with mock.patch.dict(os.environ, env, clear=False):
                session_state = load_session_state()
                session_state["current_doc"] = SAMPLE_DOC_REF
                session_state["current_node"] = "existing-node"
                save_session_state(session_state)

                stdout = io.StringIO()
                with (
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.load_document_metas", return_value=[meta]),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.load_folders", return_value=[]),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.resolve_document_reference", return_value=(meta, [])),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.get_active_user", return_value={"token": "t", "user_id": "u"}),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.fetch_document_remote", return_value=remote_doc),
                    contextlib.redirect_stdout(stdout),
                ):
                    result = dispatch(["workflow", "pick", "Inbox", "--list", "--json"], prog_name="mubu-cli")

                self.assertEqual(result, 0)
                payload = json.loads(stdout.getvalue())
                self.assertEqual(payload["match_count"], 2)
                self.assertEqual(payload["current_doc"], SAMPLE_DOC_REF)
                self.assertEqual(payload["current_node"], "existing-node")
                self.assertEqual([item["node_id"] for item in payload["candidates"]], ["node-1", "node-2"])

                persisted = load_session_state()
                self.assertEqual(persisted["current_doc"], SAMPLE_DOC_REF)
                self.assertEqual(persisted["current_node"], "existing-node")

    def test_workflow_ctx_uses_current_session_target(self):
        remote_doc = {
            "baseVersion": 7,
            "definition": json.dumps(
                {
                    "nodes": [
                        {
                            "id": "parent-1",
                            "text": "<span>Parent</span>",
                            "children": [
                                {"id": "before-1", "text": "<span>Before</span>", "children": []},
                                {
                                    "id": SAMPLE_NODE_ID,
                                    "text": "<span>Current</span>",
                                    "children": [
                                        {"id": "child-1", "text": "<span>Child</span>", "children": []}
                                    ],
                                },
                                {"id": "after-1", "text": "<span>After</span>", "children": []},
                            ],
                        }
                    ]
                }
            ),
        }
        meta = {"doc_id": "doc-1", "doc_path": SAMPLE_DOC_REF, "title": "Sample Doc"}

        with tempfile.TemporaryDirectory() as tmpdir:
            env = {"CLI_ANYTHING_MUBU_STATE_DIR": tmpdir}
            with mock.patch.dict(os.environ, env, clear=False):
                session_state = load_session_state()
                session_state["current_doc"] = SAMPLE_DOC_REF
                session_state["current_node"] = SAMPLE_NODE_ID
                save_session_state(session_state)

                stdout = io.StringIO()
                with (
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.load_document_metas", return_value=[meta]),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.load_folders", return_value=[]),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.resolve_document_reference", return_value=(meta, [])),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.get_active_user", return_value={"token": "t", "user_id": "u"}),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.fetch_document_remote", return_value=remote_doc),
                    contextlib.redirect_stdout(stdout),
                ):
                    result = dispatch(["workflow", "ctx", "--json"], prog_name="mubu-cli")

                self.assertEqual(result, 0)
                payload = json.loads(stdout.getvalue())
                self.assertEqual(payload["target"]["node_id"], SAMPLE_NODE_ID)
                self.assertEqual(payload["parent"]["node_id"], "parent-1")
                self.assertEqual(len(payload["siblings_before"]), 1)
                self.assertEqual(len(payload["siblings_after"]), 1)
                self.assertEqual(len(payload["children"]), 1)

    def test_workflow_append_uses_current_context_for_dry_run(self):
        remote_doc = {
            "baseVersion": 7,
            "definition": json.dumps(
                {
                    "nodes": [
                        {
                            "id": SAMPLE_NODE_ID,
                            "text": "<span>Current</span>",
                            "children": [],
                        }
                    ]
                }
            ),
        }
        meta = {"doc_id": "doc-1", "doc_path": SAMPLE_DOC_REF, "title": "Sample Doc"}

        with tempfile.TemporaryDirectory() as tmpdir:
            env = {"CLI_ANYTHING_MUBU_STATE_DIR": tmpdir}
            with mock.patch.dict(os.environ, env, clear=False):
                session_state = load_session_state()
                session_state["current_doc"] = SAMPLE_DOC_REF
                session_state["current_node"] = SAMPLE_NODE_ID
                save_session_state(session_state)

                stdout = io.StringIO()
                with (
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.load_document_metas", return_value=[meta]),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.load_folders", return_value=[]),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.resolve_document_reference", return_value=(meta, [])),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.get_active_user", return_value={"token": "t", "user_id": "u"}),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.load_change_events", return_value=[]),
                    mock.patch(
                        "cli_anything.mubu.mubu_cli.mubu_probe.resolve_mutation_member_context",
                        return_value={"document_id": "doc-1", "member_id": None},
                    ),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.fetch_document_remote", return_value=remote_doc),
                    contextlib.redirect_stdout(stdout),
                ):
                    result = dispatch(
                        ["workflow", "append", "--text", "dry run child", "--json"],
                        prog_name="mubu-cli",
                    )

                self.assertEqual(result, 0)
                payload = json.loads(stdout.getvalue())
                self.assertFalse(payload["execute"])
                self.assertEqual(payload["document"]["doc_path"], SAMPLE_DOC_REF)
                self.assertEqual(payload["target_parent"]["node_id"], SAMPLE_NODE_ID)
                self.assertEqual(payload["new_child"]["text"], "dry run child")

                persisted = load_session_state()
                self.assertEqual(persisted["current_node"], SAMPLE_NODE_ID)

    def test_workflow_capture_can_resolve_daily_and_query_parent_for_dry_run(self):
        remote_doc = {
            "baseVersion": 7,
            "definition": json.dumps(
                {
                    "nodes": [
                        {
                            "id": SAMPLE_NODE_ID,
                            "text": "<span>Inbox</span>",
                            "children": [],
                        }
                    ]
                }
            ),
        }
        meta = {"doc_id": "doc-1", "doc_path": SAMPLE_DOC_REF, "title": "Sample Doc"}

        with tempfile.TemporaryDirectory() as tmpdir:
            env = {"CLI_ANYTHING_MUBU_STATE_DIR": tmpdir}
            with mock.patch.dict(os.environ, env, clear=False):
                stdout = io.StringIO()
                with (
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.resolve_daily_folder_ref", return_value="Workspace/Daily"),
                    mock.patch("cli_anything.mubu.mubu_cli.resolve_current_daily_doc_ref", return_value=SAMPLE_DOC_REF),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.load_document_metas", return_value=[meta]),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.load_folders", return_value=[]),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.resolve_document_reference", return_value=(meta, [])),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.get_active_user", return_value={"token": "t", "user_id": "u"}),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.load_change_events", return_value=[]),
                    mock.patch(
                        "cli_anything.mubu.mubu_cli.mubu_probe.resolve_mutation_member_context",
                        return_value={"document_id": "doc-1", "member_id": None},
                    ),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.fetch_document_remote", return_value=remote_doc),
                    contextlib.redirect_stdout(stdout),
                ):
                    result = dispatch(
                        ["workflow", "capture", "--daily", "--query", "Inbox", "--text", "captured idea", "--json"],
                        prog_name="mubu-cli",
                    )

                self.assertEqual(result, 0)
                payload = json.loads(stdout.getvalue())
                self.assertFalse(payload["execute"])
                self.assertEqual(payload["document"]["doc_path"], SAMPLE_DOC_REF)
                self.assertEqual(payload["target_parent"]["node_id"], SAMPLE_NODE_ID)
                self.assertEqual(payload["current_doc"], SAMPLE_DOC_REF)
                self.assertEqual(payload["current_node"], SAMPLE_NODE_ID)

                persisted = load_session_state()
                self.assertEqual(persisted["current_doc"], SAMPLE_DOC_REF)
                self.assertEqual(persisted["current_node"], SAMPLE_NODE_ID)

    def test_workflow_capture_accepts_explicit_daily_folder_without_env(self):
        remote_doc = {
            "baseVersion": 7,
            "definition": json.dumps(
                {
                    "nodes": [
                        {
                            "id": SAMPLE_NODE_ID,
                            "text": "<span>Inbox</span>",
                            "children": [],
                        }
                    ]
                }
            ),
        }
        meta = {"doc_id": "doc-1", "doc_path": SAMPLE_DOC_REF, "title": "Sample Doc"}

        with tempfile.TemporaryDirectory() as tmpdir:
            env = {"CLI_ANYTHING_MUBU_STATE_DIR": tmpdir}
            with mock.patch.dict(os.environ, env, clear=False):
                stdout = io.StringIO()

                def resolve_daily_folder(folder_ref, env=None):
                    if folder_ref:
                        return folder_ref
                    raise RuntimeError("daily folder reference required")

                with (
                    mock.patch(
                        "cli_anything.mubu.mubu_cli.mubu_probe.resolve_daily_folder_ref",
                        side_effect=resolve_daily_folder,
                    ),
                    mock.patch("cli_anything.mubu.mubu_cli.resolve_current_daily_doc_ref", return_value=SAMPLE_DOC_REF),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.load_document_metas", return_value=[meta]),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.load_folders", return_value=[]),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.resolve_document_reference", return_value=(meta, [])),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.get_active_user", return_value={"token": "t", "user_id": "u"}),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.load_change_events", return_value=[]),
                    mock.patch(
                        "cli_anything.mubu.mubu_cli.mubu_probe.resolve_mutation_member_context",
                        return_value={"document_id": "doc-1", "member_id": None},
                    ),
                    mock.patch("cli_anything.mubu.mubu_cli.mubu_probe.fetch_document_remote", return_value=remote_doc),
                    contextlib.redirect_stdout(stdout),
                ):
                    result = dispatch(
                        [
                            "workflow",
                            "capture",
                            "--daily",
                            "--daily-folder",
                            "Workspace/Daily",
                            "--query",
                            "Inbox",
                            "--text",
                            "captured idea",
                            "--json",
                        ],
                        prog_name="mubu-cli",
                    )

                self.assertEqual(result, 0)
                payload = json.loads(stdout.getvalue())
                self.assertEqual(payload["resolved_folder_ref"], "Workspace/Daily")
                self.assertEqual(payload["document"]["doc_path"], SAMPLE_DOC_REF)


if __name__ == "__main__":
    unittest.main()
