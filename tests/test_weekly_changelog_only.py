"""RED gate: future changelog work is weekly-only."""

from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


class WeeklyChangelogOnlyTests(unittest.TestCase):
    def test_active_rules_explicitly_forbid_daily_changelog(self) -> None:
        for path in ("AGENTS.md", "README.md", "docs/versions/README.md", "docs/versions/versioning-policy.md"):
            with self.subTest(path=path):
                text = read(path)
                self.assertRegex(text, r"只按周|仅按周|按周维护")
                self.assertRegex(text, r"不再创建日报|不创建日报|不得创建日报")

    def test_version_policy_has_no_current_daily_release_instruction(self) -> None:
        text = read("docs/versions/versioning-policy.md")
        forbidden = (
            r"每日可以发布",
            r"每日.*PATCH",
            r"每日工程记录",
            r"daily changelog",
        )
        violations = [pattern for pattern in forbidden if re.search(pattern, text, re.I)]
        self.assertEqual(violations, [], "版本规范仍包含日报/每日发布规则")

    def test_current_version_index_points_to_weekly_engineering_records(self) -> None:
        text = read("docs/versions/README.md")
        self.assertRegex(text, r"周 changelog|按周")
        self.assertNotRegex(text, r"每日工程记录|daily changelog")

    def test_active_workflow_names_week_file_not_daily_file(self) -> None:
        agents = read("AGENTS.md")
        self.assertRegex(agents, r"changelog_M_D-D\.md")
        self.assertRegex(agents, r"不再创建日报")
        self.assertNotRegex(agents, r"日报文件.*现行|每日 changelog.*维护")

    def test_daily_files_are_not_reintroduced_as_tracked_current_files(self) -> None:
        gitignore = read(".gitignore")
        self.assertRegex(gitignore, r"(?m)^/?日报\.md$")


if __name__ == "__main__":
    unittest.main()
