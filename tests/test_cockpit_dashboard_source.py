"""Dashboard authority, source isolation and main-service evidence normalization."""
import json
import threading
import pytest
from bi_agent.cockpit.dashboard_source import SNAPSHOT, RELEASE, TOOL, SCHEMA, material, executor
from bi_agent.web.session import WebSession
from open_claude.agent_def import AgentDef
from open_claude.tools import register_tool


def context():
    queries=json.loads(SNAPSHOT.read_text())['analysis']
    key=next(k for k,v in queries.items() if v.get('success') and any('采购' in c.get('label','') for c in v.get('data',{}).get('result',{}).get('columns',[])))
    return dict(chartSnapshotId=RELEASE,chartQueries=[key])


def test_server_owned_snapshot_and_scope_are_content_bound():
    c=context();fingerprint,selected=material(c)
    assert material(c)[0]==fingerprint
    key=next(iter(selected));read=executor(selected)
    catalog=json.loads(read({},''))
    assert catalog['live'] is False and catalog['queries'][0]['queryId']==key
    result=json.loads(read({'queryId':key},''))
    assert result['response']==selected[key]['response']
    assert result['scope']['request']==json.loads(c['chartQueries'][0])
    assert '采购' in json.dumps(result['semantic'],ensure_ascii=False)
    with pytest.raises(ValueError):read({'queryId':'foreign'},'')
    for changes in ({'chartSnapshotId':'foreign'},{'chartQueries':[]},{'chartQueries':['{"unknown":true}']}):
        with pytest.raises(ValueError):material({**c,**changes})


def test_main_boundary_blocks_other_tools_even_if_model_requests_them(tmp_path):
    _,selected=material(context())
    register_tool(SCHEMA,lambda p,c:pytest.fail('unbound registry executor used'))
    session=WebSession(cwd=str(tmp_path),agent_def=AgentDef('test',tools=[]),ontology_store=None,
        tools_override=[TOOL,'AskUser'],tool_executors={TOOL:executor(selected)})
    result=session._run_tool_boundary('Ontology-FactQuery','foreign',{'query':'SELECT 1'},None)
    assert result.status=='FAILED'
    result=session._run_tool_boundary(TOOL,'catalog',{},None)
    assert result.status=='SUCCEEDED'


def test_ap_cells_become_original_labeled_main_evidence(tmp_path):
    snapshot=json.loads(SNAPSHOT.read_text())['analysis']
    for raw in snapshot:
        _,selected=material(dict(chartSnapshotId=RELEASE,chartQueries=[raw]))
        key=next(iter(selected));output=executor(selected)({'queryId':key},'')
        session=WebSession(cwd=str(tmp_path),agent_def=AgentDef('test',tools=[]),ontology_store=None,tools_override=[])
        query=session.record_query_result(TOOL,{'queryId':key},output)
        assert query.provenance.source==RELEASE
        assert query.scope['request']==json.loads(raw)
        if session.claims:
            assert all(claim.provenance.source==RELEASE for claim in session.claims)
            assert any('[' in claim.statement for claim in session.claims)
            break
    else:pytest.fail('no numeric dashboard observations normalized')


def test_batch_queries_preserve_each_subquery_scope():
    snapshot=json.loads(SNAPSHOT.read_text())
    raw=next(iter(snapshot['batch']))
    _,selected=material(dict(chartSnapshotId=RELEASE,chartQueries=[raw]))
    assert len(selected)==len(json.loads(raw))
    for key,entry in selected.items():
        output=json.loads(executor(selected)({'queryId':key},''))
        assert output['scope']['request'] in json.loads(raw)
        assert output['response']==entry['response']


def test_dashboard_capability_routes_to_bound_snapshot_without_doris():
    from bi_agent.tools.analysis_policy import build_cognitive_policy_decision
    policy=build_cognitive_policy_decision('请分析发货环节经营异常，调查原因并提出建议',[TOOL,'AskUser'])
    assert policy['mode']=='DIAGNOSTIC_ANALYSIS'
    assert policy['required_tools']==[TOOL]
    assert policy['next_step']=='QUERY_DASHBOARD'
    assert policy['evidence_required'] is True


def _entry(request):
    return {"request": request, "response": {"result": {"columns": [], "rows": []}}}


def test_stage_filter_keeps_only_matching_business_evidence():
    from bi_agent.cockpit.dashboard_source import filter_stage_selected
    selected = {
        "opportunity": _entry({"analysisConfig": {"indicators": [
            {"identifierCode": "YWLN_M0022", "alias": "商机获取电量"},
            {"identifierCode": "YWLN_M0023", "alias": "商机获取金额"}]}}),
        "shipment": _entry({"analysisConfig": {"indicators": [
            {"identifierCode": "YWLN_M0035", "alias": "发货量"}]}}),
        "legacy_procurement": _entry({"analysisConfig": {"indicators": [
            {"identifierCode": "M0001", "alias": "采购金额"}]}}),
        "legacy_shipment": _entry({"analysisConfig": {"indicators": [
            {"identifierCode": "M00013", "alias": "发货金额"}]}}),
    }
    kept, excluded = filter_stage_selected(selected, "opportunity")
    assert set(kept) == {"opportunity"}
    assert set(excluded) == {"shipment", "legacy_procurement", "legacy_shipment"}
    kept, _ = filter_stage_selected(selected, "shipment")
    assert set(kept) == {"shipment", "legacy_shipment"}
    kept, _ = filter_stage_selected(selected, "order")
    assert kept == {}


def test_stage_gap_result_is_a_limited_publishable_card():
    from bi_agent.cockpit.dashboard_source import stage_gap_result
    result = stage_gap_result(dict(stage="opportunity", dataSource="ap", snapshotId="ap-x",
                                   stageEvidence=dict(kept=0, excluded=4)))
    assert result["_status"] == "limited"
    assert result["cardContract"] == "cockpit-cards-v1"
    assert result["causes"] == [] and result["recommendations"] == []
    assert any("未取得商机获取环节" in item for item in [result["summary"]])
    assert any("已排除4条" in limit for limit in result["limitations"])


def test_stage_projection_hides_other_stage_columns_in_mixed_query():
    from bi_agent.cockpit.dashboard_source import executor
    request = {"analysisConfig": {"indicators": [
        {"identifierCode": "YWLN_M0022"}, {"identifierCode": "YWLN_M0035"}]}}
    response = {"result": {"columns": [
        {"identifierCode": "YWLN_D003", "label": "产品类型", "type": "DIMENSION"},
        {"identifierCode": "YWLN_M0022", "label": "商机获取电量", "type": "METRIC"},
        {"identifierCode": "YWLN_M0035", "label": "发货量", "type": "METRIC"}],
        "rows": [{"YWLN_D003": {"value": "PACK"},
                  "YWLN_M0022": {"value": 1.45},
                  "YWLN_M0035": {"value": 3.73}}]}}
    selected = {"q1": {"request": request, "response": response}}
    output = json.loads(executor(selected, "opportunity")({"queryId": "q1"}, ""))
    assert output["data"]["rows"] == [{"产品类型[YWLN_D003]": "PACK",
                                       "商机获取电量[YWLN_M0022]": 1.45}]


def test_failed_queries_are_reported_for_the_matching_stage_only():
    from bi_agent.cockpit.dashboard_source import unavailable_stage_evidence
    failed = {"unavailableQueries": [
        json.dumps({"analysisConfig": {"indicators": [
            {"identifierCode": "YWLN_M0023", "alias": "商机获取金额"}]}}),
        json.dumps({"analysisConfig": {"indicators": [
            {"identifierCode": "YWLN_M0036", "alias": "发货金额"}]}}),
    ]}
    got = unavailable_stage_evidence(failed, "opportunity")
    assert got["failed"] == 1 and got["excluded"] == 1
    assert "商机获取金额" in got["labels"]
    assert unavailable_stage_evidence({}, "opportunity")["failed"] == 0
    with pytest.raises(ValueError):
        unavailable_stage_evidence({"unavailableQueries": ["{not json"]}, "opportunity")


def test_customer_planning_metrics_count_as_opportunity_evidence():
    from bi_agent.cockpit.dashboard_source import filter_stage_selected, unavailable_stage_evidence
    planning = {"analysisConfig": {"indicators": [
        {"identifierCode": "YWLN_M0075", "alias": "目标电量"},
        {"identifierCode": "YWLN_M_CUSTOMER_TARGET_ENERGY", "alias": "规划电量"},
        {"identifierCode": "YWLN_M_CUSTOMER_ACTUAL_ENERGY", "alias": "实际电量"}]}}
    kept, excluded = filter_stage_selected({"plan": _entry(planning)}, "opportunity")
    assert set(kept) == {"plan"} and excluded == []
    failed = unavailable_stage_evidence({"unavailableQueries": [json.dumps(planning)]}, "opportunity")
    assert failed["failed"] == 1
    assert set(failed["labels"]) == {"目标电量", "规划电量", "实际电量"}


def test_lean_model_evidence_is_bounded_and_raw_snapshot_stays_intact():
    from copy import deepcopy
    selected={'q':{'request':{'analysisConfig':{}},'response':{'result':{
        'columns':[{'identifierCode':'YWLN_M0036','label':'发货金额'}],
        'rows':[{'YWLN_M0036':{'value':n}} for n in range(500)]}},'receiptId':'receipt'}}
    before=deepcopy(selected)
    output=json.loads(executor(selected,'shipment',lean=True)({'queryId':'q'},''))
    assert len(output['data']['rows'])==24
    assert output['coverage']=={'returnedRows':500,'providedRows':24,'sampleOnly':True}
    assert 'response' not in output and output['scope']['receiptId']=='receipt'
    assert selected==before
