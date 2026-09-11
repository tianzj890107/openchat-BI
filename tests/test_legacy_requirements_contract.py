"""RED: the legacy requirements list must not miss declared dependencies.

`open_claude/requirements.txt` is a leftover from the v0.1.0 CLI-only release.
Nothing in the repository reads it, but an external build script may still run
`pip install -r open_claude/requirements.txt`; in that case the image must still
get every dependency declared in `pyproject.toml`, otherwise `python -m
bi_agent.web` dies on `ModuleNotFoundError: No module named 'dotenv'`.
"""

from __future__ import annotations

from pathlib import Path
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
LEGACY_REQUIREMENTS = ROOT / "open_claude" / "requirements.txt"


def declared_requirements() -> list[str]:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    project = data["project"]
    requirements = list(project.get("dependencies") or [])
    for extra in (project.get("optional-dependencies") or {}).values():
        requirements.extend(extra)
    return requirements


def legacy_requirements() -> list[str]:
    lines = []
    for raw in LEGACY_REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            lines.append(line)
    return lines


class LegacyRequirementsContractTests(unittest.TestCase):
    def test_legacy_requirements_file_still_exists(self) -> None:
        self.assertTrue(LEGACY_REQUIREMENTS.is_file())

    def test_legacy_requirements_covers_every_declared_dependency(self) -> None:
        legacy = legacy_requirements()
        for requirement in declared_requirements():
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, legacy)

    def test_legacy_requirements_points_at_the_canonical_install(self) -> None:
        text = LEGACY_REQUIREMENTS.read_text(encoding="utf-8")
        self.assertIn("pip install", text)
        self.assertIn(".[web]", text)


if __name__ == "__main__":
    unittest.main()
