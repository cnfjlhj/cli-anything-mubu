import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from cli_anything.mubu.mubu_cli import expand_repl_aliases_with_state
from mubu_probe import DEFAULT_BACKUP_ROOT, DEFAULT_STORAGE_ROOT


REPO_ROOT = Path(__file__).resolve().parents[4]
SAMPLE_DOC_REF = "workspace/Daily tasks/2026.03.18"
SAMPLE_NODE_ID = "node-demo1"
HAS_LOCAL_DATA = DEFAULT_BACKUP_ROOT.is_dir() and DEFAULT_STORAGE_ROOT.is_dir()


def resolve_cli() -> list[str]:
    installed = shutil.which("cli-anything-mubu")
    if installed:
        return [installed]
    return [sys.executable, "-m", "cli_anything.mubu"]


class CliEntrypointTests(unittest.TestCase):
    CLI_BASE = resolve_cli()

    def run_cli(self, args, input_text=None, extra_env=None):
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
        )

    def test_help_renders_root_commands(self):
        result = self.run_cli(["--help"])
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("discover", result.stdout)
        self.assertIn("inspect", result.stdout)
        self.assertIn("mutate", result.stdout)
        self.assertIn("session", result.stdout)
        self.assertIn("daily-current", result.stdout)
        self.assertIn("create-child", result.stdout)
        self.assertIn("delete-node", result.stdout)

    def test_repl_help_renders(self):
        result = self.run_cli(["repl", "--help"])
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("Interactive REPL", result.stdout)
        self.assertIn("use-node", result.stdout)

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

    @unittest.skipUnless(HAS_LOCAL_DATA, "Mubu local data directories not found")
    def test_grouped_discover_daily_current_supports_global_json_flag(self):
        result = self.run_cli(["--json", "discover", "daily-current"])
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


if __name__ == "__main__":
    unittest.main()
