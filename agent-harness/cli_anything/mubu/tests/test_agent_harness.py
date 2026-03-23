import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SOFTWARE_ROOT = Path(__file__).resolve().parents[4]
HARNESS_ROOT = SOFTWARE_ROOT / "agent-harness"
STANDALONE_ROOT = SOFTWARE_ROOT if (SOFTWARE_ROOT / "setup.py").is_file() else None


def _find_contribution_root() -> Path:
    candidates = [SOFTWARE_ROOT, *SOFTWARE_ROOT.parents]
    for candidate in candidates:
        if (candidate / "CONTRIBUTING.md").is_file() and (candidate / "registry.json").is_file():
            return candidate
    raise AssertionError("unable to locate contribution root containing CONTRIBUTING.md and registry.json")


CONTRIBUTION_ROOT = _find_contribution_root()


class AgentHarnessPackagingTests(unittest.TestCase):
    def test_agent_harness_packaging_files_exist(self):
        self.assertTrue((HARNESS_ROOT / "setup.py").is_file())
        self.assertTrue((HARNESS_ROOT / "pyproject.toml").is_file())

    def test_agent_harness_contains_canonical_package_tree(self):
        expected_paths = [
            HARNESS_ROOT / "cli_anything" / "mubu" / "__init__.py",
            HARNESS_ROOT / "cli_anything" / "mubu" / "__main__.py",
            HARNESS_ROOT / "cli_anything" / "mubu" / "mubu_cli.py",
            HARNESS_ROOT / "cli_anything" / "mubu" / "verification.py",
            HARNESS_ROOT / "scripts" / "verify_mubu_cli.py",
            HARNESS_ROOT / "cli_anything" / "mubu" / "utils" / "__init__.py",
            HARNESS_ROOT / "cli_anything" / "mubu" / "utils" / "repl_skin.py",
            HARNESS_ROOT / "cli_anything" / "mubu" / "skills" / "SKILL.md",
            HARNESS_ROOT / "cli_anything" / "mubu" / "tests" / "TEST.md",
        ]
        for path in expected_paths:
            self.assertTrue(path.is_file(), msg=f"missing canonical harness file: {path}")

    def test_agent_harness_contains_canonical_test_modules(self):
        expected_paths = [
            HARNESS_ROOT / "cli_anything" / "mubu" / "tests" / "test_mubu_probe.py",
            HARNESS_ROOT / "cli_anything" / "mubu" / "tests" / "test_cli_entrypoint.py",
            HARNESS_ROOT / "cli_anything" / "mubu" / "tests" / "test_agent_harness.py",
            HARNESS_ROOT / "cli_anything" / "mubu" / "tests" / "test_core.py",
            HARNESS_ROOT / "cli_anything" / "mubu" / "tests" / "test_full_e2e.py",
        ]
        for path in expected_paths:
            self.assertTrue(path.is_file(), msg=f"missing canonical harness test: {path}")

    def test_contribution_files_exist(self):
        self.assertTrue((CONTRIBUTION_ROOT / "CONTRIBUTING.md").is_file())
        self.assertTrue((CONTRIBUTION_ROOT / "registry.json").is_file())

    def test_agent_harness_setup_reports_expected_name(self):
        result = subprocess.run(
            [sys.executable, str(HARNESS_ROOT / "setup.py"), "--name"],
            cwd=HARNESS_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "cli-anything-mubu")

    def test_agent_harness_setup_reports_expected_version(self):
        result = subprocess.run(
            [sys.executable, str(HARNESS_ROOT / "setup.py"), "--version"],
            cwd=HARNESS_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "0.1.0")

    def test_root_setup_targets_canonical_harness_source(self):
        if STANDALONE_ROOT is None:
            self.assertFalse((SOFTWARE_ROOT / "setup.py").exists())
            self.assertTrue((SOFTWARE_ROOT / "agent-harness" / "setup.py").is_file())
            return
        setup_text = (STANDALONE_ROOT / "setup.py").read_text()
        self.assertIn('find_namespace_packages(where="agent-harness"', setup_text)
        self.assertIn('package_dir={"": "agent-harness"}', setup_text)

    def test_setup_files_declare_click_runtime_dependency(self):
        harness_setup = (HARNESS_ROOT / "setup.py").read_text()
        if STANDALONE_ROOT is not None:
            root_setup = (STANDALONE_ROOT / "setup.py").read_text()
            self.assertIn('"click>=8.0"', root_setup)
        self.assertIn('"click>=8.0"', harness_setup)

    def test_skill_generator_assets_exist(self):
        self.assertTrue((HARNESS_ROOT / "skill_generator.py").is_file())
        self.assertTrue((HARNESS_ROOT / "templates" / "SKILL.md.template").is_file())

    def test_repl_skin_matches_cli_anything_copy_shape(self):
        repl_skin = (HARNESS_ROOT / "cli_anything" / "mubu" / "utils" / "repl_skin.py").read_text()
        self.assertIn('"""cli-anything REPL Skin — Unified terminal interface for all CLI harnesses.', repl_skin)
        self.assertIn("Copy this file into your CLI package at:", repl_skin)
        self.assertIn("skin.print_goodbye()", repl_skin)

    def test_skill_generator_can_regenerate_skill_from_canonical_harness(self):
        output_path = HARNESS_ROOT / "tmp-generated-SKILL.md"
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    str(HARNESS_ROOT / "skill_generator.py"),
                    str(HARNESS_ROOT),
                    "--output",
                    str(output_path),
                ],
                cwd=HARNESS_ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            content = output_path.read_text()
            self.assertIn('name: >-\n  cli-anything-mubu', content)
            self.assertIn("## Command Groups", content)
            self.assertIn("### Discover", content)
            self.assertNotIn("### Cli", content)
            self.assertIn("| `docs` |", content)
            self.assertIn("`daily-current`", content)
            self.assertIn("`update-text`", content)
            self.assertIn("### Session", content)
            self.assertIn("| `status` |", content)
            self.assertIn("| `state-path` |", content)
            self.assertIn("MUBU_DAILY_FOLDER", content)
            self.assertNotIn("Workspace/Daily tasks", content)
            self.assertNotIn("Daily tasks resolution", content)
            self.assertIn("## Version\n\n0.1.0", content)
        finally:
            output_path.unlink(missing_ok=True)

    def test_verify_script_help_renders(self):
        result = subprocess.run(
            [sys.executable, str(HARNESS_ROOT / "scripts" / "verify_mubu_cli.py"), "--help"],
            cwd=HARNESS_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("--skip-live", result.stdout)
        self.assertIn("--json", result.stdout)


class VerifyMubuCliScriptTests(unittest.TestCase):
    @staticmethod
    def _load_verify_script_module():
        script_path = HARNESS_ROOT / "cli_anything" / "mubu" / "verification.py"
        spec = importlib.util.spec_from_file_location("verify_mubu_cli_test_module", script_path)
        if spec is None or spec.loader is None:
            raise AssertionError(f"unable to load verify script module from {script_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    def test_run_live_smoke_removes_temp_state_dir_on_success(self):
        module = self._load_verify_script_module()
        state_dir = tempfile.mkdtemp(prefix="verify-mubu-cli-test-")
        responses = [
            module.StepResult(
                "daily-open",
                True,
                "mubu-cli workflow daily-open --json",
                json.dumps({"current_doc": "博一/Daily tasks/26.3.22"}),
            ),
            module.StepResult(
                "daily-nodes",
                True,
                "mubu-cli daily-nodes --json",
                json.dumps(
                    {
                        "document": {"doc_path": "博一/Daily tasks/26.3.22"},
                        "nodes": [{"node_id": "parent-node"}],
                    }
                ),
            ),
            module.StepResult("pick", True, "mubu-cli workflow pick ...", "ok"),
            module.StepResult("ctx", True, "mubu-cli workflow ctx ...", "ok"),
            module.StepResult("append-dry", True, "mubu-cli workflow append ...", json.dumps({"dry_run": True})),
            module.StepResult(
                "append-exec",
                True,
                "mubu-cli workflow append ... --execute",
                json.dumps({"new_child": {"node_id": "append-node"}}),
            ),
            module.StepResult("capture-dry", True, "mubu-cli workflow capture ...", json.dumps({"dry_run": True})),
            module.StepResult(
                "capture-exec",
                True,
                "mubu-cli workflow capture ... --execute",
                json.dumps({"new_child": {"node_id": "capture-node"}}),
            ),
            module.StepResult(
                "compat-daily-open",
                True,
                "cli-anything-mubu workflow daily-open --json",
                json.dumps({"current_doc": "博一/Daily tasks/26.3.22"}),
            ),
            module.StepResult("cleanup-append-node", True, "mubu-cli delete-node ...", json.dumps({"deleted": True})),
            module.StepResult("cleanup-capture-node", True, "mubu-cli delete-node ...", json.dumps({"deleted": True})),
        ]

        with (
            mock.patch.object(module, "detect_daily_folder_ref", return_value="博一/Daily tasks"),
            mock.patch.object(
                module,
                "resolve_live_smoke_doc_refs",
                return_value=("博一/Daily tasks/26.3.22", "博一/Daily tasks/26.3.22"),
            ),
            mock.patch.object(module, "resolve_entrypoint", return_value=["cli-anything-mubu"]),
            mock.patch.object(module.tempfile, "mkdtemp", return_value=state_dir),
            mock.patch.object(module, "run_command", side_effect=responses) as run_command_mock,
            mock.patch.object(module.subprocess, "run") as subprocess_run_mock,
        ):
            result = module.run_live_smoke(["mubu-cli"])

        self.assertTrue(result.ok, msg=result.details)
        self.assertFalse(Path(state_dir).exists(), msg="state dir should be removed after live smoke")
        self.assertEqual(run_command_mock.call_count, len(responses))
        subprocess_run_mock.assert_not_called()

    def test_run_live_smoke_removes_temp_state_dir_on_failure_after_create(self):
        module = self._load_verify_script_module()
        state_dir = tempfile.mkdtemp(prefix="verify-mubu-cli-test-")
        responses = [
            module.StepResult(
                "daily-open",
                True,
                "mubu-cli workflow daily-open --json",
                json.dumps({"current_doc": "博一/Daily tasks/26.3.22"}),
            ),
            module.StepResult(
                "daily-nodes",
                True,
                "mubu-cli daily-nodes --json",
                json.dumps(
                    {
                        "document": {"doc_path": "博一/Daily tasks/26.3.22"},
                        "nodes": [{"node_id": "parent-node"}],
                    }
                ),
            ),
            module.StepResult("pick", True, "mubu-cli workflow pick ...", "ok"),
            module.StepResult("ctx", True, "mubu-cli workflow ctx ...", "ok"),
            module.StepResult("append-dry", True, "mubu-cli workflow append ...", json.dumps({"dry_run": True})),
            module.StepResult(
                "append-exec",
                True,
                "mubu-cli workflow append ... --execute",
                json.dumps({"new_child": {"node_id": "append-node"}}),
            ),
            module.StepResult("capture-dry", False, "mubu-cli workflow capture ...", "boom"),
        ]

        with (
            mock.patch.object(module, "detect_daily_folder_ref", return_value="博一/Daily tasks"),
            mock.patch.object(
                module,
                "resolve_live_smoke_doc_refs",
                return_value=("博一/Daily tasks/26.3.22", "博一/Daily tasks/26.3.22"),
            ),
            mock.patch.object(module, "resolve_entrypoint", return_value=["cli-anything-mubu"]),
            mock.patch.object(module.tempfile, "mkdtemp", return_value=state_dir),
            mock.patch.object(module, "run_command", side_effect=responses),
            mock.patch.object(module.subprocess, "run") as subprocess_run_mock,
        ):
            result = module.run_live_smoke(["mubu-cli"])

        self.assertFalse(result.ok)
        self.assertFalse(Path(state_dir).exists(), msg="state dir should be removed on failure")
        subprocess_run_mock.assert_called_once()
        cleanup_cmd = subprocess_run_mock.call_args.args[0]
        self.assertEqual(cleanup_cmd[0], "mubu-cli")
        self.assertIn("delete-node", cleanup_cmd)
        self.assertIn("博一/Daily tasks/26.3.22", cleanup_cmd)
        self.assertIn("append-node", cleanup_cmd)

    def test_resolve_live_smoke_doc_refs_prefers_execute_ready_daily_doc(self):
        module = self._load_verify_script_module()
        docs = [
            {"doc_id": "doc-current", "doc_path": "博一/Daily tasks/26.3.18", "title": "26.3.18"},
            {"doc_id": "doc-ready", "doc_path": "博一/Daily tasks/26.3.22", "title": "26.3.22"},
        ]

        with (
            mock.patch.object(module.mubu_probe, "load_document_metas", return_value=[]),
            mock.patch.object(module.mubu_probe, "load_folders", return_value=[]),
            mock.patch.object(module.mubu_probe, "folder_documents", return_value=(docs, {"path": "博一/Daily tasks"}, [])),
            mock.patch.object(module.mubu_probe, "choose_current_daily_document", return_value=(docs[0], docs)),
            mock.patch.object(module.mubu_probe, "load_change_events", side_effect=[[], [{"member_id": "m1"}]]),
            mock.patch.object(
                module.mubu_probe,
                "resolve_mutation_member_context",
                side_effect=[None, {"document_id": "doc-ready", "member_id": "m1"}],
            ),
        ):
            current_doc_ref, execute_doc_ref = module.resolve_live_smoke_doc_refs("博一/Daily tasks")

        self.assertEqual(current_doc_ref, "博一/Daily tasks/26.3.18")
        self.assertEqual(execute_doc_ref, "博一/Daily tasks/26.3.22")

    def test_run_live_smoke_can_fallback_to_execute_ready_doc_when_current_daily_has_no_nodes(self):
        module = self._load_verify_script_module()
        state_dir = tempfile.mkdtemp(prefix="verify-mubu-cli-test-")
        responses = [
            module.StepResult(
                "daily-open",
                True,
                "mubu-cli workflow daily-open --json",
                json.dumps({"current_doc": "博一/Daily tasks/26.3.18"}),
            ),
            module.StepResult(
                "daily-nodes",
                True,
                "mubu-cli daily-nodes --json",
                json.dumps(
                    {
                        "document": {"doc_path": "博一/Daily tasks/26.3.18"},
                        "nodes": [],
                    }
                ),
            ),
            module.StepResult(
                "doc-nodes-execute-doc",
                True,
                "mubu-cli doc-nodes 博一/Daily tasks/26.3.22 --json",
                json.dumps(
                    {
                        "document": {"doc_path": "博一/Daily tasks/26.3.22"},
                        "nodes": [{"node_id": "execute-parent"}],
                    }
                ),
            ),
            module.StepResult("pick", True, "mubu-cli workflow pick ...", "ok"),
            module.StepResult("ctx", True, "mubu-cli workflow ctx ...", "ok"),
            module.StepResult("append-dry", True, "mubu-cli workflow append ...", json.dumps({"dry_run": True})),
            module.StepResult(
                "append-exec",
                True,
                "mubu-cli workflow append ... --execute",
                json.dumps({"new_child": {"node_id": "append-node"}}),
            ),
            module.StepResult("capture-dry", True, "mubu-cli workflow capture ...", json.dumps({"dry_run": True})),
            module.StepResult(
                "capture-exec",
                True,
                "mubu-cli workflow capture ... --execute",
                json.dumps({"new_child": {"node_id": "capture-node"}}),
            ),
            module.StepResult(
                "compat-daily-open",
                True,
                "cli-anything-mubu workflow daily-open --json",
                json.dumps({"current_doc": "博一/Daily tasks/26.3.18"}),
            ),
            module.StepResult("cleanup-append-node", True, "mubu-cli delete-node ...", json.dumps({"deleted": True})),
            module.StepResult("cleanup-capture-node", True, "mubu-cli delete-node ...", json.dumps({"deleted": True})),
        ]

        with (
            mock.patch.object(module, "detect_daily_folder_ref", return_value="博一/Daily tasks"),
            mock.patch.object(
                module,
                "resolve_live_smoke_doc_refs",
                return_value=("博一/Daily tasks/26.3.18", "博一/Daily tasks/26.3.22"),
            ),
            mock.patch.object(module, "resolve_entrypoint", return_value=["cli-anything-mubu"]),
            mock.patch.object(module.tempfile, "mkdtemp", return_value=state_dir),
            mock.patch.object(module, "run_command", side_effect=responses) as run_command_mock,
            mock.patch.object(module.subprocess, "run") as subprocess_run_mock,
        ):
            result = module.run_live_smoke(["mubu-cli"])

        self.assertTrue(result.ok, msg=result.details)
        self.assertFalse(Path(state_dir).exists(), msg="state dir should be removed after fallback live smoke")
        issued_commands = [call.args[1] for call in run_command_mock.call_args_list]
        self.assertIn(
            ["mubu-cli", "doc-nodes", "博一/Daily tasks/26.3.22", "--json"],
            issued_commands,
        )
        self.assertIn(
            [
                "mubu-cli",
                "workflow",
                "capture",
                "--doc-ref",
                "博一/Daily tasks/26.3.22",
                "--parent-node-id",
                "execute-parent",
                "--text",
                mock.ANY,
                "--json",
            ],
            issued_commands,
        )
        subprocess_run_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
