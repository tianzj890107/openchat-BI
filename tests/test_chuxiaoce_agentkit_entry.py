"""The cockpit assistant reuses /workbench, without a second customer route."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from bi_agent.web.customer import CustomerSurface

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "/api/ontology-agentic-analytics"


async def ready(request):
    return JSONResponse({"ok": True})


def test_customer_surface_keeps_the_single_workbench_entry() -> None:
    app = Starlette(routes=[
        Route("/healthz", ready),
        Route("/workbench", ready),
        Route("/static/vendor/agentkit/workbench-agentkit-embed.js", ready),
        Route("/workbench-agentkit", ready),
        Route("/api/chat", ready),
        Route("/api/conversations", ready),
    ])
    client = TestClient(CustomerSurface(app))
    assert client.get("/workbench").status_code == 200
    assert client.get("/static/vendor/agentkit/workbench-agentkit-embed.js").status_code == 200
    # No second assistant route: /workbench-agentkit is not a customer entry.
    assert client.get("/workbench-agentkit").status_code == 404
    assert client.get("/api/chat").status_code == 404
    assert client.get("/api/conversations").status_code == 404
    prefixed = TestClient(CustomerSurface(app, PREFIX))
    assert prefixed.get(PREFIX + "/workbench").status_code == 200
    assert prefixed.get(PREFIX + "/workbench-agentkit").status_code == 404
    assert prefixed.get(PREFIX + "/api/chat").status_code == 404


def _probe(root_path: str, assistant_ui: str = "") -> dict:
    code = r'''
import json
from fastapi.testclient import TestClient
from bi_agent.web.app import app

client = TestClient(app, follow_redirects=False)
prefix = app.root_path or ""
def url(path):
    return prefix + path if prefix else path
assistant = client.get(url("/workbench?a360=assistant&view=chat"))
display = client.get(url("/workbench"))
asset = client.get(url("/static/vendor/agentkit/workbench-agentkit-embed.js"))
legacy = client.get(url("/workbench?a360=old-handoff"))
print(json.dumps({
    "root": prefix,
    "assistant_status": assistant.status_code,
    "assistant_html": assistant.text,
    "display_status": display.status_code,
    "display_html": display.text,
    "asset_status": asset.status_code,
    "asset_bytes": len(asset.content),
    "legacy_status": legacy.status_code,
}))
'''
    env = os.environ.copy()
    env["APP_ROOT_PATH"] = root_path
    if assistant_ui:
        env["WORKBENCH_ASSISTANT_UI"] = assistant_ui
    completed = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                               capture_output=True, text=True, timeout=180)
    assert completed.returncode == 0, completed.stderr[-2000:]
    return json.loads(completed.stdout.strip().splitlines()[-1])


class AssistantEntryTests(unittest.TestCase):
    def test_workbench_serves_the_assistant_only_for_a360_assistant(self) -> None:
        for root_path in ("", PREFIX):
            result = _probe(root_path)
            self.assertEqual(result["assistant_status"], 200, result)
            self.assertIn("workbench-agentkit-embed.js", result["assistant_html"])
            self.assertIn("data-a360", result["assistant_html"])
            self.assertEqual(result["display_status"], 200, result)
            self.assertIn("vendor/antd/workbench.js", result["display_html"])
            self.assertNotIn("workbench-agentkit-embed.js", result["display_html"])
            self.assertEqual(result["legacy_status"], 200, result)
            self.assertEqual(result["asset_status"], 200, result)
            self.assertGreater(result["asset_bytes"], 1000)

    def test_server_switch_serves_the_old_page_at_the_same_url(self) -> None:
        result = _probe("", assistant_ui="legacy")
        self.assertEqual(result["assistant_status"], 200)
        self.assertIn("vendor/antd/workbench.js", result["assistant_html"])
        self.assertNotIn("workbench-agentkit-embed.js", result["assistant_html"])


if __name__ == "__main__":
    unittest.main()
