import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from bi_agent.cockpit.cards import TOOL, REPAIR_TOOL, apply_card_patch, install_delivery
from bi_agent.reliability import QueryResult
from tests.test_cockpit_card_delivery import candidate


def test_local_patch_preserves_other_fields_and_original_candidate():
    value=candidate();before=deepcopy(value)
    patched=apply_card_patch(value,[{'op':'replace','path':'/summary','value':'新摘要'}])
    assert patched['summary']=='新摘要'
    assert patched['recommendations']==value['recommendations']
    assert value==before
    for path in ['/__class__/x','/context/id','/recommendations/999/action']:
        with pytest.raises(ValueError):apply_card_patch(value,[{'op':'replace','path':path,'value':'x'}])


def test_repair_is_bound_to_candidate_and_evidence_and_revalidates():
    context=dict(stage='shipment',period='2026',department='全部产品部',snapshotId='ap-test')
    session=SimpleNamespace(query_results=[QueryResult(data={'rows':[{'amount':42.5}]})],
        claims=[dict(id='f1',statement='amount=42.5')],_tool_executors={})
    install_delivery(session,context)
    value=candidate(ref='f1');value['summary']='## invalid summary'
    rejected=json.loads(session._tool_executors[TOOL](value,''))
    assert not rejected['accepted'] and session.model_tools_override==[REPAIR_TOOL]
    patch={'draftHash':rejected['draftHash'],'patches':[{'op':'replace','path':'/summary','value':'当前指标有返回，原因仍需核实。'}]}
    wrong=json.loads(session._tool_executors[REPAIR_TOOL]({**patch,'draftHash':'foreign'},''))
    assert not wrong['accepted']
    accepted=json.loads(session._tool_executors[REPAIR_TOOL](patch,''))
    assert accepted['accepted'] and session.cockpit_card_delivery[1]['recommendations']
    session.query_results.append(QueryResult(data={'rows':[]}))
    assert not json.loads(session._tool_executors[REPAIR_TOOL](patch,''))['accepted']


def test_first_rejection_reports_missing_actions_alongside_schema_errors():
    context=dict(stage='shipment',period='2026',department='全部产品部',snapshotId='ap-test')
    session=SimpleNamespace(query_results=[QueryResult(data={'rows':[{'amount':42.5}]})],
        claims=[dict(id='f1',statement='amount=42.5')],_tool_executors={})
    install_delivery(session,context)
    value=candidate(ref='f1');value['summary']='长'*241
    value.pop('limitations');value['recommendations']=[]
    response=json.loads(session._tool_executors[TOOL](value,''))
    paths=[issue['loc'] for issue in response['issues']]
    assert not response['accepted']
    assert ['summary'] in paths and ['limitations'] in paths and ['recommendations'] in paths


def test_standard_json_patch_can_append_at_dash_or_end_index():
    value=candidate();value['findings']=[]
    appended=apply_card_patch(value,[dict(op='add',path='/findings/-',value={'id':'one'})])
    assert appended['findings']==[{'id':'one'}]
    assert apply_card_patch(appended,[dict(op='add',path='/findings/1',value={'id':'two'})])['findings'][-1]['id']=='two'


def test_empty_truncated_candidate_uses_full_schema_for_the_only_retry():
    context=dict(stage='shipment',period='2026',department='全部产品部',snapshotId='ap-test')
    session=SimpleNamespace(query_results=[QueryResult(data={'rows':[{'amount':42.5}]})],
        claims=[dict(id='f1',statement='amount=42.5')],_tool_executors={})
    install_delivery(session,context)
    response=json.loads(session._tool_executors[TOOL]({},''))
    assert not response['accepted'] and session.model_tools_override==[TOOL]
    assert '完整卡片' in response['instruction']
