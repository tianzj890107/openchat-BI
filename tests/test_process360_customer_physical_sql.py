from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from bi_agent.process360.catalog import Process360Catalog
from bi_agent.process360.db import DatabaseQueryError
from bi_agent.process360.models import Scope
from bi_agent.process360.queries import (
    SC01_AGGREGATE,
    _render_sql,
    _table,
    query_sc04,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / "dataset" / "process360" / "ywln-v3.1" / "catalog.json"


def _payload() -> dict:
    payload = json.loads(DEFAULT.read_text(encoding="utf-8"))
    for row in payload["sheets"]["entity_mappings"]:
        row["客户接入状态"] = "DDL结构匹配；实库、权限及业务口径未验收"
        row["关联物理表"] = f"ded_public.p_{row['code'].lower()}"
    for row in payload["sheets"]["attribute_mappings"]:
        row["客户接入状态"] = "DDL结构匹配；实库、权限及业务口径未验收"
        row["来源字段"] = f"col_{row['code'].lower()}"
    entity = next(
        row
        for row in payload["sheets"]["entity_mappings"]
        if row["逻辑实体编码"] == "LE000011"
    )
    entity["关联物理表"] = "ded_public.p_fm_edw_v_ods_crm_salesorderdetail_esb"
    attribute = next(
        row
        for row in payload["sheets"]["attribute_mappings"]
        if row["业务属性编码"] == "AT0001235"
    )
    attribute["来源字段"] = "requestdeliveryby"
    for code in ("AT9200041", "AT9200042", "AT9200102"):
        row = next(
            row
            for row in payload["sheets"]["attribute_mappings"]
            if row["业务属性编码"] == code
        )
        row["客户接入状态"] = "blocked：兼容视图仅以NULL占位"
    return payload


def _catalog() -> Process360Catalog:
    return Process360Catalog(_payload())


def _db():
    return SimpleNamespace(config=SimpleNamespace(schema="ywln_crm"))


def test_customer_catalog_maps_logical_entities_and_attributes() -> None:
    catalog = _catalog()
    assert catalog.uses_customer_physical_tables is True
    assert catalog.physical_table("LE000011") == (
        "ded_public.p_fm_edw_v_ods_crm_salesorderdetail_esb"
    )
    assert catalog.physical_field("AT0001235") == "requestdeliveryby"
    assert catalog.physical_field("AT9200042") == ""


def test_customer_catalog_renders_no_ontology_column_tokens() -> None:
    catalog = _catalog()
    sql = _render_sql(
        catalog,
        SC01_AGGREGATE.format(
            plan=_table(catalog, _db(), "LE000013"),
            month=_table(catalog, _db(), "LE000014"),
            line=_table(catalog, _db(), "LE000011"),
            order=_table(catalog, _db(), "LE000010"),
            product=_table(catalog, _db(), "LE000029"),
            account=_table(catalog, _db(), "LE000027"),
            filters='AND o."AT0001089" = ANY(%(customer_ids)s)',
        ),
    )
    assert '"ded_public"."p_fm_edw_v_ods_crm_salesorderdetail_esb"' in sql
    assert '"requestdeliveryby"' in sql
    assert '"AT' not in sql
    assert '"LE0000' not in sql


def test_legacy_catalog_keeps_schema_and_attribute_tokens() -> None:
    catalog = Process360Catalog.from_project(ROOT)
    assert catalog.uses_customer_physical_tables is False
    sql = _render_sql(
        catalog,
        SC01_AGGREGATE.format(
            plan=_table(catalog, _db(), "LE000013"),
            month=_table(catalog, _db(), "LE000014"),
            line=_table(catalog, _db(), "LE000011"),
            order=_table(catalog, _db(), "LE000010"),
            product=_table(catalog, _db(), "LE000029"),
            account=_table(catalog, _db(), "LE000027"),
            filters="",
        ),
    )
    assert '"ywln_crm"."LE000013"' in sql
    assert '"AT0001303"' in sql


def test_missing_customer_attribute_is_explicitly_blocked() -> None:
    payload = _payload()
    row = next(
        row
        for row in payload["sheets"]["attribute_mappings"]
        if row["业务属性编码"] == "AT0001303"
    )
    row["客户接入状态"] = "blocked：客户物理表缺少该字段"
    with pytest.raises(DatabaseQueryError, match="AT0001303"):
        _render_sql(Process360Catalog(payload), 'SELECT "AT0001303" FROM t')


class _NoQueryDB:
    config = SimpleNamespace(schema="ywln_crm")

    def __init__(self) -> None:
        self.calls = 0

    def run(self, *args, **kwargs):  # pragma: no cover - must not be reached
        self.calls += 1
        raise AssertionError("SC04 must not run SQL without required physical fields")


def test_sc04_is_blocked_before_sql_when_customer_fields_are_blocked() -> None:
    db = _NoQueryDB()
    result = query_sc04(_catalog(), Scope.from_payload({}), db)
    assert result["status"] == "blocked"
    assert {item["code"] for item in result["metrics"]} == {"M0179", "M0142", "M36004"}
    assert all(item["status"] == "blocked" for item in result["metrics"])
    assert "CUSTOMER_PHYSICAL_MAPPING" in {item["code"] for item in result["gaps"]}
    assert db.calls == 0
