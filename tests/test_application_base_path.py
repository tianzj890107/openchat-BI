"""RED contract tests for configurable reverse-proxy application base path."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
PREFIX = "/api/ontology-agentic-analytics"


def run_probe(root_path: str) -> dict:
    """Import the application in a clean process so env configuration is real."""
    code = r'''
import json
from fastapi.testclient import TestClient
from bi_agent.web.app import app

client = TestClient(app, follow_redirects=False)
root = client.get("/?theme=light")
workbench = client.get("/workbench")
external_workbench = client.get(app.root_path + "/workbench")
external_health = client.get(app.root_path + "/healthz")
external_asset = client.get(
    app.root_path + "/static/vendor/antd/workbench.js",
)
print(json.dumps({
    "root_path": app.root_path,
    "root_status": root.status_code,
    "root_location": root.headers.get("location"),
    "root_content_type": root.headers.get("content-type", ""),
    "root_html": root.text,
    "workbench_status": workbench.status_code,
    "workbench_html": workbench.text,
    "external_workbench_status": external_workbench.status_code,
    "external_health_status": external_health.status_code,
    "asset_status": external_asset.status_code,
    "asset_bytes": len(external_asset.content),
}))
'''
    env = os.environ.copy()
    env["APP_ROOT_PATH"] = root_path
    completed = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=env,
        text=True, capture_output=True, check=True,
    )
    return json.loads(completed.stdout.strip().splitlines()[-1])


class ApplicationBasePathTests(unittest.TestCase):
    def test_configured_prefix_reaches_all_public_entrypoint_classes(self) -> None:
        result = run_probe(PREFIX)
        self.assertEqual(result["root_path"], PREFIX)
        # The root entry serves the workbench directly: the browser keeps the
        # prefixed address and no 3xx/Location is emitted.
        self.assertEqual(result["root_status"], 200)
        self.assertIsNone(result["root_location"])
        self.assertIn("text/html", result["root_content_type"])
        self.assertEqual(result["root_html"], result["workbench_html"])
        self.assertEqual(result["workbench_status"], 200)
        self.assertEqual(result["external_workbench_status"], 200)
        # Mounted static files must not double the "/static" segment when
        # path and root_path carry the same external prefix.
        self.assertEqual(result["asset_status"], 200)
        self.assertGreater(result["asset_bytes"], 100_000)
        # An unconfigured app may report not-ready (503); routing must still work.
        self.assertIn(result["external_health_status"], (200, 503))

        html = result["workbench_html"]
        resource_urls = re.findall(r'''(?:href|src)=["']([^"']+)["']''', html)
        self.assertTrue(resource_urls, "workbench must declare frontend assets")
        for url in resource_urls:
            if url.startswith(("http://", "https://", "data:")):
                continue
            self.assertTrue(
                url.startswith(PREFIX + "/"),
                f"workbench asset escapes APP_ROOT_PATH: {url}",
            )
        self.assertIn(PREFIX, html, "frontend runtime must receive the base path")

    def test_empty_configuration_preserves_root_deployment(self) -> None:
        result = run_probe("")
        self.assertEqual(result["root_path"], "")
        self.assertEqual(result["root_status"], 200)
        self.assertIsNone(result["root_location"])
        self.assertEqual(result["root_html"], result["workbench_html"])
        self.assertEqual(result["workbench_status"], 200)
        self.assertEqual(result["asset_status"], 200)
        self.assertIn(result["external_health_status"], (200, 503))

    def test_prefix_strip_keeps_path_and_root_path_consistent(self) -> None:
        """Both proxy modes must leave scope path/root_path consistent."""
        code = r'''
import asyncio
import json
from bi_agent.web.app import _AppRootPathStripMiddleware

PREFIX = "/api/ontology-agentic-analytics"

async def inspect(path: str, root_path: str) -> dict:
    captured: dict = {}

    async def inner(scope, receive, send) -> None:
        captured["path"] = scope["path"]
        captured["root_path"] = scope.get("root_path", "")

    middleware = _AppRootPathStripMiddleware(inner, prefix=PREFIX)
    scope = {
        "type": "http", "method": "GET", "headers": [],
        "path": path, "root_path": root_path,
    }
    await middleware(scope, lambda: None, lambda message: None)
    return captured

full_path = asyncio.run(inspect(
    PREFIX + "/static/vendor/antd/workbench.js", PREFIX,
))
stripped_path = asyncio.run(inspect(
    "/static/vendor/antd/workbench.js", PREFIX,
))
print(json.dumps({"full_path": full_path, "stripped_path": stripped_path}))
'''
        env = os.environ.copy()
        env["APP_ROOT_PATH"] = PREFIX
        completed = subprocess.run(
            [sys.executable, "-c", code], cwd=ROOT, env=env,
            text=True, capture_output=True, check=True,
        )
        result = json.loads(completed.stdout.strip().splitlines()[-1])
        for name in ("full_path", "stripped_path"):
            path = result[name]["path"]
            root_path = result[name]["root_path"]
            with self.subTest(mode=name):
                self.assertTrue(
                    root_path == "" or path.startswith(root_path + "/"),
                    f"{name}: path {path!r} does not contain root_path {root_path!r}",
                )
                self.assertTrue(path.startswith("/static/"), path)

    def test_configuration_is_normalized(self) -> None:
        self.assertEqual(run_probe("/")["root_path"], "")
        self.assertEqual(run_probe("api/ontology-agentic-analytics/")["root_path"], PREFIX)

    def test_invalid_configuration_fails_fast(self) -> None:
        code = "from bi_agent.web.app import app"
        for value in (
            "//api/x", "/api//x", "/api/../x", "/api/./x",
            "https://example.com/api", "/api/x?bad=1", "/api/x#bad",
        ):
            with self.subTest(value=value):
                env = os.environ.copy()
                env["APP_ROOT_PATH"] = value
                completed = subprocess.run(
                    [sys.executable, "-c", code], cwd=ROOT, env=env,
                    text=True, capture_output=True,
                )
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn("APP_ROOT_PATH", completed.stderr + completed.stdout)

    def test_frontend_uses_one_base_path_helper_for_runtime_urls(self) -> None:
        runtime = (ROOT / "frontend/src/runtime.js").read_text(encoding="utf-8")
        built = (ROOT / "bi_agent/web/static/vendor/antd/workbench.js").read_text(
            encoding="utf-8",
        )
        index = (ROOT / "bi_agent/web/static/index.html").read_text(encoding="utf-8")
        app_source = (ROOT / "bi_agent/web/app.py").read_text(encoding="utf-8")

        self.assertRegex(runtime, r"function\s+(?:appUrl|withBasePath)\s*\(")
        self.assertRegex(index + app_source, r"APP_ROOT_PATH|app-root-path")

        absolute_runtime_urls = re.findall(
            r'''["'`](/(?:api|static|charts|workbench)(?:[/?!][^"'`]*)?)["'`]''',
            runtime,
        )
        self.assertEqual(
            absolute_runtime_urls, [],
            "browser runtime still contains root-absolute application URLs: "
            + ", ".join(sorted(set(absolute_runtime_urls))[:12]),
        )
        absolute_built_urls = re.findall(
            r'''["'`](/(?:api|static|charts|workbench)(?:[/?!][^"'`]*)?)["'`]''',
            built,
        )
        self.assertEqual(
            absolute_built_urls, [],
            "built browser bundle still contains root-absolute application URLs: "
            + ", ".join(sorted(set(absolute_built_urls))[:12]),
        )

    def test_deployment_contract_documents_production_prefix(self) -> None:
        deployment = (ROOT / "DEPLOYMENT.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        combined = deployment + "\n" + readme
        for expected in (
            "APP_ROOT_PATH", PREFIX + "/workbench", PREFIX + "/static/",
            PREFIX + "/api/", PREFIX + "/healthz",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, combined, f"deployment docs omit {expected}")


if __name__ == "__main__":
    unittest.main()
