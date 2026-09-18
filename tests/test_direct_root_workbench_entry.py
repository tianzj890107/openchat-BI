"""TDD RED: the application root serves the workbench without redirecting."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
PREFIX = "/api/ontology-agentic-analytics"


def probe(root_path: str) -> dict[str, object]:
    code = r'''
import json
from fastapi.testclient import TestClient
from bi_agent.web.app import app

client = TestClient(app, follow_redirects=False)
prefix = app.root_path
root_url = prefix or "/"

root = client.get(root_url)
compat = client.get((prefix + "/workbench") if prefix else "/workbench")
asset = client.get((prefix + "/static/vendor/antd/workbench.js") if prefix else "/static/vendor/antd/workbench.js")

print(json.dumps({
    "app_root_path": prefix,
    "root_status": root.status_code,
    "root_location": root.headers.get("location"),
    "root_content_type": root.headers.get("content-type", ""),
    "root_html": root.text,
    "compat_status": compat.status_code,
    "compat_html": compat.text,
    "asset_status": asset.status_code,
}))
'''
    env = os.environ.copy()
    env["APP_ROOT_PATH"] = root_path
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(completed.stdout.strip().splitlines()[-1])


class DirectRootWorkbenchEntryTests(unittest.TestCase):
    def assert_direct_workbench(self, result: dict[str, object], expected_prefix: str) -> None:
        self.assertEqual(result["app_root_path"], expected_prefix)
        self.assertEqual(result["root_status"], 200)
        self.assertIsNone(result["root_location"])
        self.assertIn("text/html", result["root_content_type"])
        self.assertEqual(result["compat_status"], 200)
        self.assertEqual(result["root_html"], result["compat_html"])
        self.assertIn("window.APP_ROOT_PATH", result["root_html"])
        self.assertIn(
            f'{expected_prefix}/static/vendor/antd/workbench.js',
            result["root_html"],
        )
        self.assertEqual(result["asset_status"], 200)

    def test_prefixed_root_serves_workbench_without_redirect(self) -> None:
        self.assert_direct_workbench(probe(PREFIX), PREFIX)

    def test_unprefixed_root_serves_workbench_without_redirect(self) -> None:
        self.assert_direct_workbench(probe(""), "")

    def test_source_has_one_shared_workbench_response_builder(self) -> None:
        source = (ROOT / "bi_agent/web/app.py").read_text(encoding="utf-8")
        self.assertNotIn("RedirectResponse(url=f\"{APP_ROOT_PATH}/workbench", source)
        self.assertRegex(source, r"def\s+_\w*workbench\w*response\s*\(")


if __name__ == "__main__":
    unittest.main()
