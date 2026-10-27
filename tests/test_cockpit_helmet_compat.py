import json

from bi_agent.cockpit.helmet_compat import normalize_helmet

OPPORTUNITY = {
    "dimension": [{"fieldType": "dimension", "identifierCode": "D020",
                   "label": "商机获取办理状态", "valueType": "STRING"}],
    "measure": [{"fieldType": "measure", "identifierCode": "M0023",
                 "label": "商机获取金额", "name": "Opportunity_Amount"}],
}
QUOTATION = {
    "dimension": [{"fieldType": "dimension", "identifierCode": "D021",
                   "label": "报价办理状态", "valueType": "STRING"}],
    "measure": [{"fieldType": "measure", "identifierCode": "M0031",
                 "label": "报价电量"}],
}


def helmet(*nodes):
    return {"helmetGlobalConfig": None, "nodes": list(nodes), "edges": []}


def node(code, config):
    return {"id": code, "code": code, "name": code, "type": "ACTIVITY",
            "meta": {"helmetConfig": {"dataConfig": json.dumps(config, ensure_ascii=False),
                                      "statusMappings": [{"statusCode": "normal-error"}]}}}


def test_legacy_opportunity_config_is_replaced_with_validated_codes():
    payload = helmet(node("BUSINESS_OPPORTUNITY_ACQUISITION", OPPORTUNITY))
    result = normalize_helmet(payload)
    config = json.loads(result["nodes"][0]["meta"]["helmetConfig"]["dataConfig"])
    assert config["dimension"][0]["identifierCode"] == "D007"
    assert config["measure"][0]["identifierCode"] == "M00013"
    assert config["measure"][0]["label"] == "发货金额"
    assert result["nodes"][0]["meta"]["helmetConfig"]["statusMappings"] == [
        {"statusCode": "normal-error"}]
    assert payload["nodes"][0]["meta"]["helmetConfig"]["dataConfig"] == json.dumps(
        OPPORTUNITY, ensure_ascii=False)


def test_legacy_quotation_config_is_removed_like_reference_release():
    payload = helmet(node("QUOTATION", QUOTATION))
    result = normalize_helmet(payload)
    assert "helmetConfig" not in result["nodes"][0]["meta"]
    assert payload["nodes"][0]["meta"]["helmetConfig"]


def test_valid_or_unrelated_configs_are_untouched():
    valid = {"dimension": [{"identifierCode": "D007"}],
             "measure": [{"identifierCode": "M00013"}]}
    payload = helmet(node("BUSINESS_OPPORTUNITY_ACQUISITION", valid),
                     node("UNKNOWN_NODE", OPPORTUNITY))
    assert normalize_helmet(payload) is payload


def test_non_helmet_payloads_are_returned_unchanged():
    assert normalize_helmet(None) is None
    assert normalize_helmet({"nodes": "bad"}) == {"nodes": "bad"}
    assert normalize_helmet({"nodes": [{"code": "QUOTATION", "meta": {}}]}) == {
        "nodes": [{"code": "QUOTATION", "meta": {}}]}
