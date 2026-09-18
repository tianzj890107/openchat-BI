"""TDD RED: environment-scoped ontology gateway and one unused draft."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import unittest
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
SQL_TOOLS = (ROOT / "bi_agent/tools/sql_tools.py").read_text(encoding="utf-8")
RUNTIME = (ROOT / "frontend/src/runtime.js").read_text(encoding="utf-8")
DEPLOYMENT = (ROOT / "DEPLOYMENT.md").read_text(encoding="utf-8")
POLICY_MODULE = ROOT / "frontend/src/conversationDraftPolicy.js"


class EnvironmentScopedOntologyGatewayTests(unittest.TestCase):
    def test_image_does_not_pin_cross_environment_ontology_service(self) -> None:
        self.assertNotIn("172.16.5.181:30834", DOCKERFILE)
        self.assertNotIn("172.16.5.181:30834", SQL_TOOLS)
        self.assertNotIn("ONTOLOGY_ALLOWED_REPOSITORY_IDS", DOCKERFILE)
        self.assertNotIn("ONTOLOGY_ALLOWED_REPOSITORY_IDS", SQL_TOOLS)

    def test_deployment_documents_both_environment_gateway_pairs(self) -> None:
        expected = (
            "http://pdt-dev.eimos.com/api/gateway2/ontology",
            "http://demo2.eimos.com/api/gateway2/ontology",
            "http://pdt-dev.eimos.com/api/gateway2/ontology/agent/doris/query",
            "http://demo2.eimos.com/api/gateway2/ontology/agent/doris/query",
        )
        for value in expected:
            with self.subTest(value=value):
                self.assertIn(value, DEPLOYMENT)

    def test_remote_client_remains_driven_by_explicit_environment(self) -> None:
        source = (ROOT / "bi_agent/ontology/remote.py").read_text(encoding="utf-8")
        self.assertRegex(source, r'os\.environ\.get\("ONTOLOGY_BASE_URL"')
        self.assertRegex(source, r'os\.environ\.get\("ONTOLOGY_REPOSITORY_ID"')

    @unittest.skipUnless(
        os.getenv("RUN_DEMO2_ONTOLOGY_ENV_TESTS") == "1",
        "set RUN_DEMO2_ONTOLOGY_ENV_TESTS=1 for live demo2 verification",
    )
    def test_live_demo2_uses_demo2_gateway_and_only_ecore_source(self) -> None:
        url = "http://demo2.eimos.com/api/ontology-agentic-analytics/api/sources"
        with urlopen(url, timeout=10) as response:
            payload = json.load(response)
        production = payload["ontology"]["production"]
        self.assertEqual(
            production["base_url"],
            "http://demo2.eimos.com/api/gateway2/ontology",
        )
        repositories = payload["ontology"]["remote_repositories"]
        self.assertEqual(len(repositories), 1)
        self.assertEqual(str(repositories[0]["id"]), "3")
        self.assertIn("ECore", repositories[0]["name"])
        self.assertEqual(
            payload["database"]["options"],
            [repositories[0]["databaseValue"]],
        )


@unittest.skipUnless(shutil.which("node"), "node not available")
class UnusedConversationDraftPolicyTests(unittest.TestCase):
    def run_policy(self) -> dict[str, object]:
        script = r'''
import("./frontend/src/conversationDraftPolicy.js").then((m) => {
  const oldDraft = {id:"d1", mode:"data", title:"未命名对话", first_user_question:"", turn_count:0, updated_at:"2026-09-09T01:00:00Z"};
  const newDraft = {id:"d2", mode:"data", title:"未命名对话", first_user_question:"", turn_count:0, updated_at:"2026-09-10T01:00:00Z"};
  const used = {id:"u1", mode:"data", title:"真实问题", first_user_question:"真实问题", turn_count:1, updated_at:"2026-09-08T01:00:00Z"};
  const reportDraft = {...oldDraft, id:"r1", mode:"report"};
  console.log(JSON.stringify({
    reuse: m.shouldReuseUnusedDraft({convId:"d2", hasContent:false, firstUserQuestion:"", turnCount:0}),
    noReuseWithoutId: m.shouldReuseUnusedDraft({convId:null, hasContent:false, firstUserQuestion:"", turnCount:0}),
    noReuseUsed: m.shouldReuseUnusedDraft({convId:"u1", hasContent:true, firstUserQuestion:"真实问题", turnCount:1}),
    collapsed: m.collapseUnusedDrafts([oldDraft, used, newDraft, reportDraft]).map((x) => x.id),
  }));
}).catch((error) => { console.error(error); process.exit(1); });
'''
        completed = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
        return json.loads(completed.stdout.strip().splitlines()[-1])

    def test_policy_module_has_required_behavior(self) -> None:
        result = self.run_policy()
        self.assertTrue(result["reuse"])
        self.assertFalse(result["noReuseWithoutId"])
        self.assertFalse(result["noReuseUsed"])
        # Keep every real conversation and only the newest unused draft per mode.
        self.assertEqual(result["collapsed"], ["u1", "d2", "r1"])

    def test_runtime_uses_policy_before_creating_an_empty_draft(self) -> None:
        self.assertTrue(POLICY_MODULE.is_file())
        self.assertIn('from "./conversationDraftPolicy.js"', RUNTIME)
        reset_match = re.search(
            r"async function resetConversation\(opts\) \{(?P<body>[\s\S]*?)\n  \}\n\n  if \(el\.btnReset\)",
            RUNTIME,
        )
        self.assertIsNotNone(reset_match)
        body = reset_match.group("body")
        self.assertIn("shouldReuseUnusedDraft", body)
        self.assertLess(
            body.index("shouldReuseUnusedDraft"),
            body.index("saveCurrentConversation({ allowEmpty: true })"),
        )
        self.assertIn("collapseUnusedDrafts", RUNTIME)


if __name__ == "__main__":
    unittest.main()

