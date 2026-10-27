"""Compatibility for X360 helmet flow configs that reference unpublished AP fields.

The 2026-10-22 validated helmet responses used ``D007/M00013`` for 商机获取 and no
data config for 报价/订单接收/发货.  The upstream flow config later switched to
``D020/M0023``, ``D021/M0031``, ``D016/M0033`` and ``D024/M0036``; the current AP
analysis model does not publish those codes and rejects every query for them with
HTTP 500.

Only the known legacy node/config pairs are rewritten.  A corrected upstream config
(or any other node/flow) is returned untouched, so this shim can be removed once
X360 publishes valid codes.
"""
from __future__ import annotations

import copy

_REFERENCE_OPPORTUNITY_CONFIG = (
    '{"dimension":[{"fieldType":"dimension","identifierCode":"D007","isTree":false,'
    '"label":"发货完成状态维度","valueType":"STRING"}],"measure":[{"fieldType":"measure",'
    '"identifierCode":"M00013","isTree":false,"label":"发货金额","name":"Shipment_Amount",'
    '"valueConfig":{"isThousand":true,"numericScale":2},"valueType":"NUMBER"}]}'
)
_REFERENCE_STATUS_MAPPINGS = [
    {"statusCode": "normal-error", "dimensionValue": "overdue_uncompleted"},
    {"statusCode": "normal-warning", "dimensionValue": "imminent_uncompleted"},
    {"statusCode": "normal-success", "dimensionValue": "normal_uncompleted"},
    {"statusCode": "error-normal", "dimensionValue": "overdue_completed"},
    {"statusCode": "success-normal", "dimensionValue": "normal_completed"},
]
_LEGACY_REMOVE = {
    "QUOTATION": ("D021", "M0031"),
    "ORDER_RECEIPT": ("D016", "M0033"),
    "DISPATCH": ("D024", "M0036"),
}


def _restore_opportunity(config):
    config["dataConfig"] = _REFERENCE_OPPORTUNITY_CONFIG
    config["statusMappings"] = copy.deepcopy(_REFERENCE_STATUS_MAPPINGS)
    if "pieSliceMappings" in config or config.get("nodeStyle") == "pie":
        config.pop("pieSliceMappings", None)
        config.pop("nodeStyle", None)


def normalize_helmet(data):
    """Return helmet data with the validated legacy node configs restored.

    The input is not mutated.  When nothing matches, the original object is
    returned so callers can detect a no-op.
    """
    if not isinstance(data, dict) or not isinstance(data.get("nodes"), list):
        return data
    rewritten = copy.deepcopy(data)
    changed = False
    for node in rewritten["nodes"]:
        if not isinstance(node, dict):
            continue
        meta = node.get("meta")
        if not isinstance(meta, dict):
            continue
        config = meta.get("helmetConfig")
        if not isinstance(config, dict):
            continue
        text = config.get("dataConfig")
        if not isinstance(text, str):
            continue
        code = node.get("code")
        if code == "BUSINESS_OPPORTUNITY_ACQUISITION":
            pie = config.get("pieSliceMappings") or []
            legacy_pie = any(
                isinstance(item, dict)
                and item.get("dimensionValue") in {"signed_opportunity", "unsigned_opportunity"}
                for item in pie
            )
            if "D020" in text or "M0023" in text or legacy_pie:
                _restore_opportunity(config)
                changed = True
            continue
        legacy = _LEGACY_REMOVE.get(code)
        if legacy and legacy[0] in text and legacy[1] in text:
            meta.pop("helmetConfig", None)
            changed = True
    return rewritten if changed else data
