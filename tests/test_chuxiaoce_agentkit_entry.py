"""RED: the 储小策 assistant page is a first-class customer entry.

The cockpit opens /workbench-agentkit?a360=assistant.  It must be reachable
with and without APP_ROOT_PATH, serve its own built assets, and stay inside the
customer allowlist while generic chat/conversation APIs remain blocked.
"""
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


def test_customer_surface_allows_the_agentkit_assistant_entry() -> None:
    app = Starlette(routes=[
        Route("/healthz", ready),
        Route("/workbench-agentkit", ready),
        Route("/static/vendor/agentkit/workbench-agentkit-embed.js", ready),
        Route("/api/chat", ready),
        Route("/api/conversations", ready),
    ])
    client = TestClient(CustomerSurface(app))
    assert client.get("/workbench-agentkit").status_code == 200
    assert client.get("/static/vendor/agentkit/workbench-agentkit-embed.js").status_code == 200
    assert client.get("/api/chat").status_code == 404
    assert client.get("/api/conversations").status_code == 404
    prefixed = TestClient(CustomerSurface(app, PREFIX))
    assert prefixed.get(PREFIX + "/workbench-agentkit").status_code == 200
    assert prefixed.get(PREFIX + "/api/chat").status_code == 404


def _probe(root_path: str) -> dict:
    code = r'''
import json
from fastapi.testclient import TestClient
from bi_agent.web.app import app

client = TestClient(app, follow_redirects=False)
prefix = app.root_path or ""
def url(path):
    return prefix + path if prefix else path
page = client.get(url("/workbench-agentkit?a360=assistant"))
asset = client.get(url("/static/vendor/agentkit/workbench-agentkit-embed.js"))
legacy = client.get(url("/workbench"))
print(json.dumps({
    "root": prefix,
    "page_status": page.status_code,
    "html": page.text,
    "asset_status": asset.status_code,
    "asset_bytes": len(asset.content),
    "legacy_status": legacy.status_code,
}))
'''
    env = os.environ.copy()
    env["APP_ROOT_PATH"] = root_path
    completed = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                               capture_output=True, text=True, timeout=180)
    assert completed.returncode == 0, completed.stderr[-2000:]
    return json.loads(completed.stdout.strip().splitlines()[-1])


class AssistantEntryTests(unittest.TestCase):
    def test_route_serves_the_built_assistant_page_with_and_without_prefix(self) -> None:
        for root_path in ("", PREFIX):
            result = _probe(root_path)
            self.assertEqual(result["page_status"], 200, result)
            self.assertIn("workbench-agentkit-embed.js", result["html"])
            self.assertEqual(result["asset_status"], 200, result)
            self.assertGreater(result["asset_bytes"], 1000)
            self.assertEqual(result["legacy_status"], 200, result)
            self.assertIn("data-a360", result["html"])


if __name__ == "__main__":
    unittest.main()
