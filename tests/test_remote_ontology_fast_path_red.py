"""Regression tests for the remote ontology fast path.

These are red tests for the two failures observed against demo2:

* Python ``urllib`` inherited a local ``HTTP_PROXY`` while ``curl`` did not;
* semantic lookup pulled every candidate type instead of using the documented
  metadata LIKE query and stopping once the authoritative Indicator matched.
"""

from __future__ import annotations

from typing import Any
from urllib.request import ProxyHandler

from bi_agent.ontology import remote as remote_module
from bi_agent.tools import remote_ontology_tools as tools


class _MetaClient:
    def __init__(self) -> None:
        self.meta_calls: list[tuple[str, str]] = []
        self.list_calls: list[str] = []

    def metadata_query(self, analysis: dict[str, Any], common: dict[str, Any]) -> dict[str, Any]:
        type_name = analysis["vertex"][0]["type"]
        prop = common["filters"]["property"]
        self.meta_calls.append((type_name, prop))
        if type_name == "Indicator" and prop == "label":
            return {
                "result": {
                    "columns": [{"identifierCode": "code"}, {"identifierCode": "label"}],
                    "rows": [{"code": "M0001", "label": "采购金额"}],
                },
            }
        return {"result": {"columns": [], "rows": []}}

    def list_objects(self, type_name: str, limit: int = 2000) -> list[dict[str, Any]]:
        self.list_calls.append(type_name)
        return []


def test_search_type_uses_metadata_like_before_full_pull() -> None:
    client = _MetaClient()
    rows = tools._search_type(client, "Indicator", "采购金额", limit=5)  # type: ignore[arg-type]
    assert rows and rows[0]["code"] == "M0001"
    assert client.list_calls == []
    assert ("Indicator", "label") in client.meta_calls


def test_candidate_scan_stops_at_indicator() -> None:
    client = _MetaClient()
    found, degraded = tools._candidate_results(client, "采购金额")  # type: ignore[arg-type]
    assert degraded is False
    assert found and found[0][0] == "Indicator"
    # Dimension is probed before Indicator; Rule/Activity/Process must never be
    # reached once the authoritative Indicator has a hit.
    probed = [type_name for type_name, _prop in client.meta_calls]
    assert "Rule" not in probed
    assert "Activity" not in probed
    assert "Indicator" not in client.list_calls


def test_ontology_transport_builds_a_proxy_free_opener() -> None:
    # ``build_opener(ProxyHandler({}))`` intentionally produces an opener with
    # no proxy handler at all; this is what makes urllib ignore HTTP_PROXY.
    assert not any(isinstance(handler, ProxyHandler)
                   for handler in remote_module._ONTOLOGY_OPENER.handlers)
