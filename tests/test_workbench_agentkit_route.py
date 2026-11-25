"""Serve AgentKit at both default entries and retain an explicit legacy fallback."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
PREFIX = "/api/ontology-agentic-analytics"
AGENTKIT_JS = "static/vendor/agentkit/workbench-agentkit.js"
AGENTKIT_CSS = "static/vendor/agentkit/workbench-agentkit.css"


def probe(root_path: str) -> dict[str, object]:
    code = r'''
import hashlib
import json
from fastapi.testclient import TestClient
from bi_agent.web.app import app

client = TestClient(app, follow_redirects=False)
prefix = app.root_path
def url(path):
    return (prefix + path) if prefix else path

agentkit = client.get(url("/workbench-agentkit"))
workbench = client.get(url("/workbench?prompt=PACK"))
legacy = client.get(url("/workbench-legacy"))
root = client.get(prefix or "/")
js = client.get(url("/static/vendor/agentkit/workbench-agentkit.js"))
css = client.get(url("/static/vendor/agentkit/workbench-agentkit.css"))
legacy_js = client.get(url("/static/vendor/antd-legacy/workbench-legacy.js"))
legacy_css = client.get(url("/static/vendor/antd-legacy/workbench-legacy.css"))

print(json.dumps({
    "app_root_path": prefix,
    "agentkit_status": agentkit.status_code,
    "agentkit_type": agentkit.headers.get("content-type", ""),
    "agentkit_cache": agentkit.headers.get("cache-control", ""),
    "agentkit_html": agentkit.text,
    "workbench_status": workbench.status_code,
    "workbench_html": workbench.text,
    "workbench_location": workbench.headers.get("location"),
    "legacy_status": legacy.status_code,
    "legacy_html": legacy.text,
    "legacy_js_status": legacy_js.status_code,
    "legacy_js_md5": hashlib.md5(legacy_js.content or b"").hexdigest(),
    "legacy_css_status": legacy_css.status_code,
    "legacy_css_md5": hashlib.md5(legacy_css.content or b"").hexdigest(),
    "root_html": root.text,
    "js_status": js.status_code,
    "js_bytes": len(js.content or b""),
    "css_status": css.status_code,
    "css_bytes": len(css.content or b""),
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
    )
    if completed.returncode != 0:
        raise AssertionError(
            "workbench-agentkit probe failed:\n" + (completed.stderr or completed.stdout)
        )
    return json.loads(completed.stdout.strip().splitlines()[-1])


class WorkbenchAgentkitRouteTests(unittest.TestCase):
    def assert_agentkit_page(self, result: dict[str, object], prefix: str) -> None:
        html = str(result["agentkit_html"])
        self.assertEqual(result["agentkit_status"], 200)
        self.assertIn("text/html", str(result["agentkit_type"]))
        # The entry is a full page shell owned by the AgentKit workbench.
        self.assertIn('id="agentkit-root"', html)
        self.assertIn("data-agentkit-root", html)
        # Asset URLs are built from the single APP_ROOT_PATH token.
        self.assertIn(f'{prefix}/{AGENTKIT_JS}?v=', html)
        self.assertIn(f'{prefix}/{AGENTKIT_CSS}?v=', html)
        self.assertNotIn("@@APP_ROOT_PATH@@", html)
        self.assertRegex(html, r'data-app-version="ontology-v\d+\.\d+\.\d+"')
        self.assertNotIn("@@APP_VERSION@@", html)
        # Version tokens are resolved from file mtime, never left frozen.
        self.assertNotIn("@@AGENTKIT_JS_VERSION@@", html)
        self.assertNotIn("@@AGENTKIT_CSS_VERSION@@", html)
        self.assertRegex(html, r"workbench-agentkit\.js\?v=\d+")
        # A workbench page must not be cached across deployments.
        self.assertIn("no-store", str(result["agentkit_cache"]))
        # Both bundles exist and are served from the AgentKit asset directory.
        self.assertEqual(result["js_status"], 200)
        self.assertGreater(int(result["js_bytes"]), 1000)
        self.assertEqual(result["css_status"], 200)
        self.assertGreater(int(result["css_bytes"]), 500)

    def test_prefixed_entry_serves_agentkit_workbench(self) -> None:
        self.assert_agentkit_page(probe(PREFIX), PREFIX)

    def test_unprefixed_entry_serves_agentkit_workbench(self) -> None:
        self.assert_agentkit_page(probe(""), "")

    def test_default_entries_serve_agentkit_and_legacy_fallback_serves_old_page(self) -> None:
        result = probe(PREFIX)
        legacy = str(result["legacy_html"])
        root_html = str(result["root_html"])
        self.assertEqual(result["legacy_status"], 200)
        # /workbench-legacy is the restored demo2-era page (commit 07ac670):
        # its own bundle under antd-legacy, never the AgentKit one.
        self.assertIn("vendor/antd-legacy/workbench-legacy.js?v=162", legacy)
        self.assertIn("vendor/antd-legacy/workbench-legacy.css?v=127", legacy)
        self.assertIn("硕磐智能分析 Agent · 本体工作台", legacy)
        self.assertNotIn("vendor/agentkit/workbench-agentkit.js", legacy)
        self.assertEqual(result["legacy_js_status"], 200)
        self.assertEqual(result["legacy_css_status"], 200)
        # Byte-identical to what demo2 served (md5 of the 07ac670 build).
        self.assertEqual(result["legacy_js_md5"], "e0a0f53e2c5778c4d50f99527981b23f")
        self.assertEqual(result["legacy_css_md5"], "592a4a685841a6439c3edf2a28d747e9")
        self.assertEqual(result["workbench_status"], 200)
        self.assertIsNone(result["workbench_location"])
        self.assertEqual(root_html, result["agentkit_html"])
        self.assertEqual(result["workbench_html"], root_html)

    def test_route_is_registered_beside_the_legacy_entry(self) -> None:
        source = (ROOT / "bi_agent/web/app.py").read_text(encoding="utf-8")
        self.assertIn('@app.get("/workbench-agentkit")', source)
        # Keep the existing user-facing alias.
        self.assertIn('@app.get("/workbench")', source)
        self.assertIn('def workbench() -> HTMLResponse:', source)


if __name__ == "__main__":
    unittest.main()
