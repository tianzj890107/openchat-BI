"""Compatibility for X360 helmet flow configs that reference unpublished AP fields.

The 2026-10-22 validated ``FULL_PROCESS_OPERATIONS_MANAGEMENT`` response used
``D007/M00013`` for the 商机获取 node and no data config for 报价.  The upstream flow
config later switched to ``D020/M0023`` and ``D021/M0031``; the current AP analysis
model does not publish those codes and rejects every query for them with HTTP 500.

Only the two known legacy node/config pairs are rewritten.  A corrected upstream
config (or any other node/flow) is returned untouched, so this shim can be removed
once X360 publishes valid codes.
"""
from __future__ import annotations

import copy

_REFERENCE_OPPORTUNITY_CONFIG = (
    '{"dimension":[{"fieldType":"dimension","identifierCode":"D007","isTree":false,'
    '"label":"发货完成状态维度","valueType":"STRING"}],"measure":[{"fieldType":"measure",'
    '"identifierCode":"M00013","isTree":false,"label":"发货金额","name":"Shipment_Amount",'
    '"valueConfig":{"isThousand":true,"numericScale":2},"valueType":"NUMBER"}]}'
)


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
        if node.get("code") == "BUSINESS_OPPORTUNITY_ACQUISITION" and (
            "D020" in text or "M0023" in text
        ):
            config["dataConfig"] = _REFERENCE_OPPORTUNITY_CONFIG
            changed = True
        elif node.get("code") == "QUOTATION" and ("D021" in text or "M0031" in text):
            meta.pop("helmetConfig", None)
            changed = True
    return rewritten if changed else data
