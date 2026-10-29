"""The cockpit must render upstream helmet configs verbatim.

2026-10-29: upstream ontology repository 8 publishes YWLN_* helmet codes.
The old compatibility shim rewrote valid YWLN_D020/YWLN_M0022 (and removed
quotation/order/dispatch configs) to legacy D007/M00013, which made the
opportunity helmet show shipment amounts.  The shim is gone; this test keeps
the transport path from silently reintroducing a rewrite.
"""
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

import bi_agent.cockpit.router as router
from bi_agent.cockpit.router import build_cockpit_router

OPPORTUNITY = {
    "dimension": [{"identifierCode": "YWLN_D020"}],
    "measure": [{"identifierCode": "YWLN_M0022"}],
}
QUOTATION = {
    "dimension": [{"identifierCode": "YWLN_D021"}],
    "measure": [{"identifierCode": "YWLN_M0031"}],
}


def helmet(*nodes):
    return {"helmetGlobalConfig": None, "nodes": list(nodes), "edges": []}


def node(code, config):
    return {"id": code, "code": code, "name": code, "type": "ACTIVITY",
            "meta": {"helmetConfig": {"dataConfig": json.dumps(config, ensure_ascii=False),
                                      "statusMappings": [{"statusCode": "normal-error"}]}}}


class Gateway:
    def __init__(self, payload):
        self.payload = payload
        from types import SimpleNamespace
        self.config = SimpleNamespace(
            base_url="http://ap.example", batch_mode="individual", receipt_ttl=60,
            headers=lambda: {"X-App-Id": "test"}, identity=lambda: "identity-test",
        )

    def query(self, kind, payload):
        return json.loads(json.dumps(self.payload))


def fetch(payload, monkeypatch, tmp_path):
    monkeypatch.setenv("COCKPIT_DATA_MODE", "ap")
    monkeypatch.setattr(router, "get_gateway", lambda: Gateway(payload))
    app = FastAPI()
    app.include_router(build_cockpit_router(lambda: tmp_path, main_context=lambda c: {}))
    response = TestClient(app).post(
        "/api/cockpit/data/query",
        json=dict(id=1, kind="helmet", payload={"flowCode": "FULL_PROCESS_OPERATIONS_MANAGEMENT"}),
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_upstream_ywln_helmet_configs_are_not_rewritten(monkeypatch, tmp_path):
    payload = helmet(node("BUSINESS_OPPORTUNITY_ACQUISITION", OPPORTUNITY),
                     node("QUOTATION", QUOTATION))
    result = fetch(payload, monkeypatch, tmp_path)
    opportunity = json.loads(result["nodes"][0]["meta"]["helmetConfig"]["dataConfig"])
    assert opportunity["dimension"][0]["identifierCode"] == "YWLN_D020"
    assert opportunity["measure"][0]["identifierCode"] == "YWLN_M0022"
    quotation = json.loads(result["nodes"][1]["meta"]["helmetConfig"]["dataConfig"])
    assert quotation["dimension"][0]["identifierCode"] == "YWLN_D021"
    assert quotation["measure"][0]["identifierCode"] == "YWLN_M0031"


def test_legacy_only_helmet_payloads_are_also_left_alone(monkeypatch, tmp_path):
    legacy = {"dimension": [{"identifierCode": "D007"}],
              "measure": [{"identifierCode": "M00013"}]}
    payload = helmet(node("BUSINESS_OPPORTUNITY_ACQUISITION", legacy))
    result = fetch(payload, monkeypatch, tmp_path)
    config = json.loads(result["nodes"][0]["meta"]["helmetConfig"]["dataConfig"])
    assert config["dimension"][0]["identifierCode"] == "D007"
    assert config["measure"][0]["identifierCode"] == "M00013"
