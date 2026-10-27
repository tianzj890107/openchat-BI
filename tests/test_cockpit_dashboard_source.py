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
