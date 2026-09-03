from __future__ import annotations

import re
import unittest
from pathlib import Path


class FrontendSubmissionFlowTests(unittest.TestCase):
    def test_successful_submission_keeps_the_pairing_workspace_visible(self) -> None:
        source = Path("frontend/src/StudioShell.tsx").read_text(encoding="utf-8")
        match = re.search(
            r"async function generateVideo\(\) \{(?P<body>.*?)\n  \}\n\n  async function cancelHistoryTask",
            source,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(match)
        body = match.group("body")

        self.assertIn('setNotice("작업을 제출했습니다. 현재 이미지와 프롬프트는 유지됩니다.");', body)
        self.assertNotIn("loadWorkflowIntoState(selectedWorkflow", body)
        self.assertNotIn('onNavigate("review.history")', body)


if __name__ == "__main__":
    unittest.main()
