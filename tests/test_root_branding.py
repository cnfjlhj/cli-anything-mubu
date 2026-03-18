import json
import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class RootBrandingTests(unittest.TestCase):
    def test_root_setup_reports_public_package_name(self):
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "setup.py"), "--name"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "mubu-cli")

    def test_root_setup_exposes_public_and_compat_entrypoints(self):
        setup_text = (REPO_ROOT / "setup.py").read_text(encoding="utf-8")
        self.assertIn('"mubu-cli=cli_anything.mubu.mubu_cli:entrypoint"', setup_text)
        self.assertIn('"cli-anything-mubu=cli_anything.mubu.mubu_cli:entrypoint"', setup_text)

    def test_root_registry_uses_public_brand(self):
        registry = json.loads((REPO_ROOT / "registry.json").read_text(encoding="utf-8"))
        self.assertEqual(registry["name"], "mubu-cli")
        self.assertEqual(registry["entry_point"], "mubu-cli")

    def test_root_skill_and_readme_present_mubu_cli_brand(self):
        skill_text = (REPO_ROOT / "SKILL.md").read_text(encoding="utf-8")
        readme_text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("name: mubu-cli", skill_text)
        self.assertIn("# mubu-cli", skill_text)
        self.assertIn("# mubu-cli", readme_text)
        self.assertIn("`mubu-cli`", readme_text)


if __name__ == "__main__":
    unittest.main()
