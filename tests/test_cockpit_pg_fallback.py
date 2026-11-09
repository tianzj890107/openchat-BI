"""Read-only PostgreSQL fallback for cockpit metrics that failed in AP.

The fallback may only answer queries whose metric, dimensions and filters are
reviewed; everything else must stay blocked with a reason code instead of
returning a guessed number or borrowing another metric.
"""
import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from bi_agent.cockpit import pg_fallback as fallback
from bi_agent.cockpit.dashboard_source import RELEASE, evidence_source, receipt_scope
from bi_agent.cockpit.store import Store

@pytest.fixture(autouse=True)
def explicit_pg_opt_in(monkeypatch):
    # Exercise the retained fallback mechanism only under explicit opt-in.
    monkeypatch.setenv('COCKPIT_PG_FALLBACK_ENABLED', '1')

DATE = {"identifierCode": "YWLN_D044", "operator": {"code": "BETWEEN", "type": "DATE"},
        "value": ["2025-01-01", "2025-12-31"], "valueType": "ABSOLUTE"}


def query_payload(code="YWLN_M0036", filters=None, dimensions=None):
    return {"analysisConfig": {"indicators": [{"alias": "指标", "identifierCode": code}],
                               "dimensions": dimensions or []},
            "commonConfig": {"filters": {"children": [DATE] if filters is None else filters,
                                         "logic": "AND"},
                             "pagination": {"pageNum": 1, "pageSize": 10}}}


def test_compiles_single_table_aggregate_with_bound_parameters():
    plan = fallback.compile_payload(query_payload())
    assert plan["sql"].count("SELECT") == 1
    assert '"ywln_crm"."v_ods_crm_new_ord_shipment_esb"' in plan["sql"]
    assert "2025-01-01" not in plan["sql"]
    assert plan["params"] == ["2025-01-01", "2026-01-01"]
    assert plan["columns"][0]["unit"] == "亿元"


def test_unreconciled_metric_stays_blocked():
    with pytest.raises(fallback.FallbackUnavailable) as error:
        fallback.compile_payload(query_payload("YWLN_M0024"))
    assert error.value.code == "RECONCILE_GAP"


def test_unmapped_dimension_filter_and_metric_are_blocked():
    with pytest.raises(fallback.FallbackUnavailable) as error:
        fallback.compile_payload(query_payload(dimensions=[{"identifierCode": "YWLN_D003"}]))
    assert error.value.code == "DIMENSION_UNMAPPED"
    with pytest.raises(fallback.FallbackUnavailable) as error:
        fallback.compile_payload(query_payload(filters=[{"identifierCode": "D007", "value": "x"}]))
    assert error.value.code == "FILTER_UNMAPPED"
    with pytest.raises(fallback.FallbackUnavailable) as error:
        fallback.compile_payload(query_payload("YWLN_M9999"))
    assert error.value.code == "METRIC_UNMAPPED"


def test_date_filter_must_be_a_valid_reviewed_range():
    bad = [dict(DATE, value=["2025-01-01"])]
    with pytest.raises(fallback.FallbackUnavailable) as error:
        fallback.compile_payload(query_payload(filters=bad))
    assert error.value.code == "FILTER_INVALID"
    reversed_range = [dict(DATE, value=["2025-12-31", "2025-01-01"])]
    with pytest.raises(fallback.FallbackUnavailable) as error:
        fallback.compile_payload(query_payload(filters=reversed_range))
    assert error.value.code == "FILTER_INVALID"


def test_empty_aggregate_is_not_turned_into_zero(monkeypatch):
    import bi_agent.process360.db as db

    class Reader:
        def run(self, sql, params, timeout_ms, max_rows):
            return SimpleNamespace(rows=[{"YWLN_M0036": None}])

    class Database:
        available = True

        @contextmanager
        def snapshot(self):
            yield Reader()

    monkeypatch.setattr(db, "PostgresDatabase", Database)
    value = fallback.query(query_payload())
    assert value["result"]["rows"][0]["YWLN_M0036"]["value"] is None


def test_supplement_saves_a_pg_receipt_and_reports_blocked_queries(tmp_path, monkeypatch):
    store = Store(tmp_path / "history.sqlite3")
    store.recover()
    result = {"resultType": "TABLE",
              "result": {"columns": [{"identifierCode": "YWLN_M0036", "label": "发货金额（亿元）",
                                      "type": "METRIC", "unit": "亿元", "decimals": 2}],
                         "rows": [{"YWLN_M0036": {"value": 79.16}}]},
              "pagination": {"pageNum": 1, "pageSize": 20, "total": 1}}
    real_query = fallback.query

    def fake_query(payload):
        fallback.compile_payload(payload)  # honour the reviewed registry before answering
        return result

    monkeypatch.setattr(fallback, "query", fake_query)
    context = {"id": 1, "unavailableQueries": [
        json.dumps(query_payload()), json.dumps(query_payload("YWLN_M0024"))]}
    entries, notes = fallback.supplement(context, store)
    assert len(entries) == 1
    entry = next(iter(entries.values()))
    assert entry["source"] == "pg" and entry["transport"] == "postgres"
    assert store.get_ap_result(entry["receiptId"], 1)["kind"] == "pg"
    assert [note["code"] for note in notes] == ["RECONCILE_GAP"]


def _ap_receipt(store, payload_value, response):
    return store.save_ap_result(1, "analysis", payload_value, response, 900,
                                "ap-connection", "auth-scope", "fixed-path")


def test_receipt_scope_merges_ap_and_pg_and_keeps_the_fingerprint_stable(tmp_path, monkeypatch):
    store = Store(tmp_path / "history.sqlite3")
    store.recover()
    ap_payload = query_payload(filters=[dict(DATE, value=["2025-01-01", "2025-01-31"])])
    ap_response = {"resultType": "TABLE", "result": {"columns": [], "rows": []}, "pagination": {}}
    ap_id = _ap_receipt(store, ap_payload, ap_response)["id"]
    failed = query_payload()
    monkeypatch.setattr(fallback, "query", _fake_query())
    context = {"id": 1, "chartSnapshotId": RELEASE, "stage": "shipment", "apReceiptIds": [ap_id],
               "pgReceiptIds": [], "chartQueries": [json.dumps(ap_payload)],
               "unavailableQueries": [json.dumps(failed)]}
    fingerprint, selected, pg_ids, notes = receipt_scope(context, store, resolve_fallback=True)
    assert notes == [] and len(pg_ids) == 1
    assert sorted(value["source"] for value in selected.values()) == ["ap", "pg"]
    assert evidence_source(selected) == ("cockpit-ap+pg", True)
    replay = dict(context, pgReceiptIds=pg_ids)
    assert receipt_scope(replay, store)[0] == fingerprint

    with pytest.raises(ValueError):
        receipt_scope(dict(replay, chartQueries=[]), store)

    with store.db() as db:
        db.execute("UPDATE ap_results SET expires=0 WHERE id=?", (pg_ids[0],))
    with pytest.raises(ValueError):
        receipt_scope(replay, store)
    assert receipt_scope(replay, store, allow_expired=True)[0] == fingerprint


def test_pg_receipt_from_an_older_mapping_version_is_rejected(tmp_path, monkeypatch):
    store = Store(tmp_path / "history.sqlite3")
    store.recover()
    failed = query_payload()
    monkeypatch.setattr(fallback, "query", lambda payload: {
        "resultType": "TABLE", "result": {"columns": [], "rows": []}, "pagination": {}})
    entries, _ = fallback.supplement({"id": 1, "unavailableQueries": [json.dumps(failed)]}, store)
    receipt_id = next(iter(entries.values()))["receiptId"]
    item = store.get_ap_result(receipt_id, 1)
    item["authScope"] = "old-mapping"
    with store.db() as db:
        db.execute("UPDATE ap_results SET body=? WHERE id=?", (json.dumps(item), receipt_id))
    with pytest.raises(ValueError, match="口径已更新"):
        receipt_scope({"id": 1, "chartSnapshotId": RELEASE, "apReceiptIds": [],
                       "pgReceiptIds": [receipt_id], "chartQueries": [],
                       "unavailableQueries": [json.dumps(failed)]}, store)


def test_evidence_discloses_the_database_supplement_and_blocked_reasons():
    from bi_agent.cockpit.main_service import session_evidence

    class Session:
        claims = []
        query_results = []
        cockpit_stage_filter = dict(stage="shipment", kept=1, excluded=0,
                                    fallback=["YWLN_M0036"], fallbackBlocked=["RECONCILE_GAP"])

    evidence = session_evidence(Session(), {"snapshotId": "ap-abc", "dataSource": "ap+pg",
                                            "stage": "shipment", "period": "", "department": ""})
    text = " ".join(evidence["limitations"])
    assert "PostgreSQL" in text and "YWLN_M0036" in text and "RECONCILE_GAP" in text
    assert all(len(item) <= 300 for item in evidence["limitations"])


PG_RESULT = {"resultType": "TABLE",
             "result": {"columns": [{"identifierCode": "YWLN_M0036", "label": "发货金额（亿元）",
                                     "type": "METRIC", "unit": "亿元", "decimals": 2}],
                        "rows": [{"YWLN_M0036": {"value": 79.16}}]},
             "pagination": {"pageNum": 1, "pageSize": 20, "total": 1}}


def _fake_query(calls=None):
    def run(payload):
        fallback.compile_payload(payload)
        if calls is not None:
            calls.append(payload)
        return PG_RESULT
    return run


def test_real_contract_supplements_only_queries_the_page_failed(tmp_path, monkeypatch):
    """chartQueries carries successful AP only; failed ones live in unavailableQueries."""
    store = Store(tmp_path / "history.sqlite3")
    store.recover()
    ap_payload = query_payload(filters=[dict(DATE, value=["2025-01-01", "2025-01-31"])])
    ap_id = _ap_receipt(store, ap_payload, {"resultType": "TABLE", "result": {"columns": [], "rows": []}})["id"]
    failed = query_payload()
    monkeypatch.setattr(fallback, "query", _fake_query())
    context = {"id": 1, "chartSnapshotId": RELEASE, "stage": "shipment",
               "apReceiptIds": [ap_id], "pgReceiptIds": [],
               "chartQueries": [json.dumps(ap_payload)],
               "unavailableQueries": [json.dumps(failed)]}
    fingerprint, selected, pg_ids, notes = receipt_scope(context, store, resolve_fallback=True)
    assert notes == [] and len(pg_ids) == 1
    assert sorted(value["source"] for value in selected.values()) == ["ap", "pg"]
    # The main-service turn replays the same context: this is where the real
    # request used to fail with "结果凭据与页面查询范围不一致".
    replay = dict(context, pgReceiptIds=pg_ids)
    assert receipt_scope(replay, store)[0] == fingerprint
    # A pg receipt may never pretend to be a successful page query.
    with pytest.raises(ValueError, match="同时列为成功和失败"):
        receipt_scope(dict(replay, chartQueries=[json.dumps(ap_payload), json.dumps(failed)]), store)
    # And a pg receipt cannot survive once the page no longer reports that
    # query as failed.
    with pytest.raises(ValueError, match="范围不一致"):
        receipt_scope(dict(replay, unavailableQueries=[]), store)


def test_all_ap_failed_can_still_be_answered_by_the_registered_fallback(tmp_path, monkeypatch):
    store = Store(tmp_path / "history.sqlite3")
    store.recover()
    monkeypatch.setattr(fallback, "query", _fake_query())
    context = {"id": 1, "chartSnapshotId": RELEASE, "stage": "shipment",
               "apReceiptIds": [], "pgReceiptIds": [], "chartQueries": [],
               "unavailableQueries": [json.dumps(query_payload())]}
    fingerprint, selected, pg_ids, notes = receipt_scope(context, store, resolve_fallback=True)
    assert notes == [] and len(pg_ids) == 1 and set(selected) == {"pg:" + pg_ids[0]}
    assert evidence_source(selected) == ("cockpit-pg", True)
    assert receipt_scope(dict(context, pgReceiptIds=pg_ids), store)[0] == fingerprint


def test_nothing_usable_after_fallback_is_a_clear_client_error(tmp_path):
    store = Store(tmp_path / "history.sqlite3")
    store.recover()
    context = {"id": 1, "chartSnapshotId": RELEASE, "stage": "shipment", "apReceiptIds": [],
               "pgReceiptIds": [], "chartQueries": [],
               "unavailableQueries": [json.dumps(query_payload("YWLN_M0024"))]}
    with pytest.raises(ValueError, match="没有任何已登记口径可供补查"):
        receipt_scope(context, store, resolve_fallback=True)
    with pytest.raises(ValueError, match="必须指定本次页面"):
        receipt_scope(dict(context, unavailableQueries=[]), store, resolve_fallback=True)


def test_date_operator_and_value_type_must_stay_the_reviewed_semantics():
    for operator in ({"code": "NOT_BETWEEN", "type": "DATE"}, {"code": "GT", "type": "DATE"},
                     {"code": "BETWEEN", "type": "DATETIME"}):
        with pytest.raises(fallback.FallbackUnavailable) as error:
            fallback.compile_payload(query_payload(filters=[dict(DATE, operator=operator)]))
        assert error.value.code in {"FILTER_UNSUPPORTED", "FILTER_INVALID"}
    with pytest.raises(fallback.FallbackUnavailable) as error:
        fallback.compile_payload(query_payload(filters=[dict(DATE, valueType="RELATIVE")]))
    assert error.value.code in {"FILTER_UNSUPPORTED", "FILTER_INVALID"}


def test_or_logic_nested_and_duplicate_date_filters_are_rejected():
    def raw(filters):
        payload = query_payload()
        payload["commonConfig"]["filters"] = filters
        return payload

    with pytest.raises(fallback.FallbackUnavailable) as error:
        fallback.compile_payload(raw({"logic": "OR", "children": [DATE]}))
    assert error.value.code == "FILTER_UNSUPPORTED"
    with pytest.raises(fallback.FallbackUnavailable) as error:
        fallback.compile_payload(raw({"logic": "AND", "children": [{"logic": "AND", "children": [DATE]}]}))
    assert error.value.code == "FILTER_UNSUPPORTED"
    with pytest.raises(fallback.FallbackUnavailable) as error:
        fallback.compile_payload(raw({"logic": "AND", "children": [DATE, dict(DATE)]}))
    assert error.value.code == "FILTER_UNSUPPORTED"


def test_unmapped_queries_never_consume_the_fallback_quota(tmp_path, monkeypatch):
    store = Store(tmp_path / "history.sqlite3")
    store.recover()
    calls = []
    monkeypatch.setattr(fallback, "query", _fake_query(calls))
    unavailable = [json.dumps(query_payload(code)) for code in
                   ("YWLN_M9996", "YWLN_M9997", "YWLN_M9998", "YWLN_M9999")]
    unavailable.append(json.dumps(query_payload()))
    entries, notes = fallback.supplement({"id": 1, "unavailableQueries": unavailable}, store, limit=1)
    assert len(entries) == 1 and len(calls) == 1
    assert {note["code"] for note in notes} == {"METRIC_UNMAPPED"}


def test_fallback_only_spends_quota_on_the_current_stage(tmp_path, monkeypatch):
    store = Store(tmp_path / "history.sqlite3")
    store.recover()
    calls = []
    monkeypatch.setattr(fallback, "query", _fake_query(calls))
    bid = {"analysisConfig": {"indicators": [{"alias": "中标金额", "identifierCode": "YWLN_M0027"}], "dimensions": []},
           "commonConfig": {"filters": {"children": [DATE], "logic": "AND"}, "pagination": {"pageNum": 1, "pageSize": 10}}}
    entries, notes = fallback.supplement({"id": 1, "stage": "shipment",
                                          "unavailableQueries": [json.dumps(bid), json.dumps(query_payload())]},
                                         store, limit=1)
    assert len(entries) == 1
    assert [payload["analysisConfig"]["indicators"][0]["identifierCode"] for payload in calls] == ["YWLN_M0036"]
    assert notes == []


def test_empty_and_filter_block_is_the_same_as_no_filter():
    payload = query_payload()
    payload["commonConfig"]["filters"] = {"logic": "AND"}
    plan = fallback.compile_payload(payload)
    assert plan["params"] == []
    payload["commonConfig"]["filters"] = {"logic": "AND", "children": []}
    assert fallback.compile_payload(payload)["params"] == []
