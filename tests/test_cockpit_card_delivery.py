import json
import time
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from bi_agent.cockpit.cards import CONTRACT, TOOL, install_delivery
from bi_agent.cockpit.agent import validate_result
from bi_agent.cockpit.cards import Cards
from bi_agent.cockpit.dashboard_source import RELEASE
from bi_agent.reliability import QueryResult
from tests.test_cockpit_ap_gateway import QUERY, DATA, APGateway, Opener, config


def candidate(status='hypothesis',ref='Cockpit-DashboardQuery-1-0'):
    return dict(summary='指标有返回，归因尚待核实。',causes=[dict(id='c1',title='流程卡点待核实',description='需核对排程与质检记录，当前仅为假设。',status=status,evidenceIds=[ref])],
        recommendations=[dict(id='a1',causeIds=['c1'],action='核对排程与质检记录',ownerRole='业务分析员',deadlineDays=3,acceptance='取得同订单流程记录')],limitations=['缺少同源明细'])


def test_delivery_tool_rejects_missing_or_fabricated_causal_evidence():
    context=dict(stage='shipment',period='2025-10',department='全部产品部',snapshotId='ap-test')
    query=QueryResult(data={'rows':[{'amount':42.5}]})
    session=SimpleNamespace(query_results=[query],claims=[dict(id='f1',statement='amount=42.5')],_tool_executors={})
    install_delivery(session,context)
    for value in [candidate(ref='foreign'),candidate(status='supported',ref='f1')]:
        rejected=json.loads(session._tool_executors[TOOL](value,''))
        assert rejected['accepted'] is False and rejected['issues']
    assert session.cockpit_card_delivery is None
    session._tool_executors[TOOL](candidate(ref='f1'),'')
    assert session.cockpit_card_delivery[1]['causes'][0]['status']=='hypothesis'


def test_findings_require_queried_evidence_and_deduplicate_metric_codes():
    fact = dict(id='f1',label='amount',value=42.5,unit='')
    evidence = dict(facts=[fact], records=[], evidence=[fact], limitations=[])
    value = dict(summary='指标存在风险。', causes=[], recommendations=[], limitations=['测试限制'],
                 findings=[dict(id='risk-1',kind='risk_fact',title='销售额低于目标',
                                description='证据支持',metricCodes=['SALES_GAP'],
                                evidenceIds=['f1'],riskDomain='sales')])
    accepted = validate_result(value, evidence, {'f1'}, result_model=Cards)
    assert accepted['findings'][0]['kind'] == 'risk_fact'

    value['findings'][0]['evidenceIds'] = ['foreign']
    with pytest.raises(ValueError, match='风险发现引用'):
        validate_result(value, evidence, {'f1', 'foreign'}, result_model=Cards)

    value['findings'] = [dict(value['findings'][0], id='risk-1', evidenceIds=['f1']),
                         dict(value['findings'][0], id='risk-2', evidenceIds=['f1'])]
    with pytest.raises(ValueError, match='同一指标风险发现重复'):
        validate_result(value, evidence, {'f1'}, result_model=Cards)


@pytest.mark.parametrize('repair_first',[False,True])
def test_real_main_delivers_existing_card_contract_then_publishes_without_second_model(tmp_path,monkeypatch,repair_first):
    import bi_agent.web.app as web
    import bi_agent.cockpit.router as router
    from open_claude.agent_def import AgentDef
    from bi_agent.ontology.store import OntologyStore
    from bi_agent.concurrency import SessionSlotRegistry, AdmissionController, get_limits
    monkeypatch.setenv('COCKPIT_DATA_MODE','ap')
    for key,value in dict(cwd=str(tmp_path),agent_def=AgentDef('test',tools=['AskUser']),sessions={},ontology_store=OntologyStore(),source_contexts={},session_slots=SessionSlotRegistry(),admission=AdmissionController(get_limits())).items():
        monkeypatch.setattr(web.STATE,key,value)
    gateway=APGateway(config(tmp_path),Opener({'success':True,'data':DATA}));monkeypatch.setattr(router,'get_gateway',lambda:gateway)
    client=TestClient(web.app)
    receipt=client.post('/api/cockpit/data/query',json=dict(id=1,kind='analysis',payload=QUERY)).json()
    count=[]
    def provider(*args,**kwargs):
        count.append(1)
        if len(count)==1:yield dict(type='tool_use_end',id='q1',name='Cockpit-DashboardQuery',input={'queryId':receipt['receiptId']+':0'})
        elif len(count)==2 and repair_first:yield dict(type='tool_use_end',id='invalid-cards',name=TOOL,input=candidate(ref='unknown-evidence'))
        elif len(count)==(3 if repair_first else 2):yield dict(type='tool_use_end',id='cards',name=TOOL,input=candidate())
        else:
            yield dict(type='text_delta',text='结论\n当前指标有返回，缺少目标及对比口径，不能认定异常。\n根因分析\n【推断】流程卡点是待核实假设，缺少排程和质检明细，不能确认根因。\n行动建议\n建议由业务分析员在三个工作日内核对排程和质检记录，以取得同订单流程记录作为验收。')
        yield dict(type='message_end',stop_reason='tool_use' if len(count)<(4 if repair_first else 3) else 'end_turn',usage={})
    request=dict(id=1,engine='main',source='service',stage='shipment',page='analysis',defaultView=True,chartSnapshotId=RELEASE,
        chartQueries=[json.dumps(QUERY)],apReceiptIds=[receipt['receiptId']])
    with patch('bi_agent.web.session.stream_message',side_effect=provider),patch.object(web,'_source_for_session',side_effect=AssertionError('No original source')):
        first=client.post('/api/cockpit/analyses/refresh',json=request).json();aid=first['analysis']['id']
        for _ in range(150):
            item=client.get('/api/cockpit/analyses/'+aid).json()
            if item['status'] not in {'queued','running'}:break
            time.sleep(.01)
        assert item['status']=='limited',item
        assert item['result']['cardContract']==CONTRACT,item
        assert item['result']['summary']==candidate()['summary']
        assert len(item['result']['causes'])==len(item['result']['recommendations'])==1
        for _ in range(100):
            saved=client.get('/api/cockpit/analyses/published?id=1&page=analysis').json()['items']
            if saved:break
            time.sleep(.01)
        assert saved['shipment']['id']==aid
        # A new AP receipt for identical values does not invalidate the last success.
        again=client.post('/api/cockpit/data/query',json=dict(id=1,kind='analysis',payload=QUERY)).json()
        request['apReceiptIds']=[again['receiptId']]
        reopened=client.post('/api/cockpit/analyses/refresh',json=request).json()
        assert reopened['cached']['id']==aid and reopened['analysis'] is None
        assert len(count)==(4 if repair_first else 3) # Rejection repairs inside the same main tool loop.
