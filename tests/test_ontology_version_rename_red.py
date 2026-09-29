"""RED contract tests for the ontology-v0.0.x version-family rename.

Contract source: ``docs/specs/ontology-version-rename-and-rebuild.md``.
The whole family ``v0.1.0``-``v0.1.9`` is mapped to ``ontology-v0.0.1``-
``ontology-v0.0.10`` on the same commits, and the tag/Release lists are
rebuilt.  The current product version then advanced to the MINOR
``ontology-v0.1.0`` on 2026-09-29, so ``CURRENT`` tracks that name while
``NEW_TAGS`` stays the historical rename map.  These tests never write to
Git, GitLab or user data.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = "docs/specs/ontology-version-rename-and-rebuild.md"
CURRENT = "ontology-v0.1.0"
PACKAGING_VERSION = "0.1.0"

# (old tag, unchanged commit, new tag)
MAPPING = (
    ("v0.1.0", "e4b0a8f33a8e3343c43e78a38efdc292c14f0a47", "ontology-v0.0.1"),
    ("v0.1.1", "28bb1d63dfd427d7889de3dde4e83d618028ee2c", "ontology-v0.0.2"),
    ("v0.1.2", "c8454d82f052a6770bae975a5d865a6f37eff721", "ontology-v0.0.3"),
    ("v0.1.3", "f9012f383195b9818fa322f8e47837aea4235972", "ontology-v0.0.4"),
    ("v0.1.4", "51939b2c3e5da755c4bef0df7e665cc5ac01d776", "ontology-v0.0.5"),
    ("v0.1.5", "99ac6f1f0aaf1235bfdaa49e35957bd59dafd7a6", "ontology-v0.0.6"),
    ("v0.1.6", "1ae9894df5e2fba190dbadca483ec7a15b1cd216", "ontology-v0.0.7"),
    ("v0.1.7", "706e0d54af0c3c6604179dc8eaf2862a7faf920e", "ontology-v0.0.8"),
    ("v0.1.8", "c938fc042b26728c9909dd05e89c65b83fe852e8", "ontology-v0.0.9"),
    ("v0.1.9", "60fadfcd5d0a93e49034f1a5bfbb4917241f7fc2", "ontology-v0.0.10"),
)
NEW_TAGS = tuple(item[2] for item in MAPPING)


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _load_runner():
    """Import ``scripts/run_analytics_eval.py`` without executing ``main``."""
    spec = importlib.util.spec_from_file_location(
        "analytics_eval_runner_rename", ROOT / "scripts" / "run_analytics_eval.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class OntologyVersionRenameRedTests(unittest.TestCase):
    def test_spec_exists_and_lists_the_full_mapping(self) -> None:
        self.assertTrue((ROOT / SPEC).is_file(), f"{SPEC} must exist")
        text = read(SPEC)
        for old, commit, new in MAPPING:
            with self.subTest(old=old):
                self.assertIn(old, text)
                self.assertIn(commit, text)
                self.assertIn(new, text)
        self.assertIn("PEP 440", text)
        self.assertIn("semver", text)

    def test_pyproject_keeps_a_pep440_version(self) -> None:
        from packaging.version import Version

        pyproject = read("pyproject.toml")
        match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
        self.assertIsNotNone(match, "pyproject.toml must declare a version")
        declared = match.group(1)
        self.assertEqual(declared, PACKAGING_VERSION)
        self.assertEqual(str(Version(declared)), PACKAGING_VERSION)
        self.assertNotIn("ontology-v", pyproject)

    def test_frontend_manifests_keep_a_semver_version(self) -> None:
        self.assertEqual(json.loads(read("frontend/package.json"))["version"],
                         PACKAGING_VERSION)
        lock = json.loads(read("frontend/package-lock.json"))
        self.assertEqual(lock["packages"][""]["version"], PACKAGING_VERSION)
        self.assertEqual(lock["version"], PACKAGING_VERSION)

    def test_display_version_is_unified(self) -> None:
        cases = {
            "bi_agent/__init__.py": f'__version__ = "{CURRENT}"',
            "open_claude/__init__.py": f'__version__ = "{CURRENT}"',
            "bi_agent/web/app.py": f'APP_VERSION = "{CURRENT}"',
            "frontend/src/main.jsx": f'const PRODUCT_VERSION = "{CURRENT}";',
            "frontend/src/shell.html": f">{CURRENT}</span>",
        }
        for relative, expected in cases.items():
            with self.subTest(path=relative):
                self.assertIn(expected, read(relative))

    def test_built_frontend_bundle_is_rebuilt(self) -> None:
        bundle = read("bi_agent/web/static/vendor/antd/workbench.js")
        self.assertIn(CURRENT, bundle)
        self.assertNotIn("v0.1.9", bundle)

    def test_product_version_returns_the_new_display_name(self) -> None:
        self.assertEqual(_load_runner().product_version(), CURRENT)

    def test_version_reached_handles_the_new_prefix(self) -> None:
        reached = _load_runner()._version_reached
        self.assertTrue(reached(CURRENT, "ontology-v0.0.1"))
        self.assertTrue(reached(CURRENT, CURRENT))
        self.assertFalse(reached(CURRENT, "ontology-v0.2.0"))
        self.assertTrue(reached("0.1.0", "0.0.10"))
        self.assertFalse(reached(CURRENT, ""))
        self.assertFalse(reached(CURRENT, "not-a-version"))

    def test_version_policy_documents_the_new_scheme(self) -> None:
        policy = read("docs/versions/versioning-policy.md")
        self.assertIn("ontology-vMAJOR.MINOR.PATCH", policy)
        self.assertIn(CURRENT, policy)
        self.assertNotIn("```text\nv0.1.9\n```", policy)

    def test_version_documents_are_renamed_and_complete(self) -> None:
        versions_dir = ROOT / "docs" / "versions"
        names = {path.name for path in versions_dir.iterdir() if path.is_file()}
        expected = {"README.md", "versioning-policy.md", f"{CURRENT}.md"} | {
            f"{tag}.md" for tag in NEW_TAGS
        }
        self.assertEqual(names, expected)

    def test_root_readme_tracks_the_new_version(self) -> None:
        readme = read("README.md")
        self.assertIn(CURRENT, readme)
        # The retired ``v0.1.x`` tag family must not reappear as a link.
        self.assertNotIn("releases/v0.1.", readme)
        self.assertEqual(readme.count("/-/releases/ontology-v0.0."), 10)

    def test_agents_md_records_the_one_time_authorization(self) -> None:
        agents = read("AGENTS.md")
        self.assertIn(CURRENT, agents)
        for marker in ("v0.1.0", "v0.1.9", "ontology-v0.0.1", "ontology-v0.0.10"):
            with self.subTest(marker=marker):
                self.assertIn(marker, agents)

    def test_local_tags_are_the_renamed_names_plus_the_current_tag(self) -> None:
        """The ten renamed tags, plus ``CURRENT`` once the user authorizes it.

        ``ontology-v0.1.0`` was authorized on 2026-09-29 but is created on
        ``master`` only *after* the version-cut Merge Request merges, so the
        local list is allowed to contain it yet must never require it --
        exact-set equality would fail every pipeline until the tag exists.
        """
        proc = subprocess.run(
            ["git", "-C", str(ROOT), "tag", "--list"],
            capture_output=True, text=True, check=True,
        )
        tags = {line for line in proc.stdout.splitlines() if line.strip()}
        renamed = set(NEW_TAGS)
        allowed = renamed | {CURRENT}
        self.assertLessEqual(tags, allowed, f"unexpected tags: {sorted(tags - allowed)}")
        self.assertLessEqual(renamed, tags, f"missing renamed tags: {sorted(renamed - tags)}")


if __name__ == "__main__":
    unittest.main()
