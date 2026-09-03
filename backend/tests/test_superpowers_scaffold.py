from __future__ import annotations

import os
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class SuperpowersScaffoldTests(unittest.TestCase):
    def test_agent_instructions_define_the_project_workflow(self) -> None:
        instructions = (PROJECT_ROOT / "AGENTS.md").read_text(encoding="utf-8")

        self.assertIn("Superpowers", instructions)
        self.assertIn("brainstorming", instructions)
        self.assertIn("test-driven-development", instructions)
        self.assertIn("verification-before-completion", instructions)

    def test_superpowers_readme_documents_specs_plans_and_verification(self) -> None:
        guide = (PROJECT_ROOT / "docs/superpowers/README.md").read_text(encoding="utf-8")

        self.assertIn("specs/", guide)
        self.assertIn("plans/", guide)
        self.assertIn("scripts/verify.sh", guide)

    def test_verify_script_is_available_and_executable(self) -> None:
        script = PROJECT_ROOT / "scripts/verify.sh"

        self.assertTrue(script.is_file())
        self.assertTrue(os.access(script, os.X_OK))


if __name__ == "__main__":
    unittest.main()
