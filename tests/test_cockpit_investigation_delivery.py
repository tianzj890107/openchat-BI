import pytest
from bi_agent.cockpit.delivery import validate_reasoning, project_card
from bi_agent.cockpit.store import Store

EVIDENCE={'facts':[{'id':'e1','label':'实际出货量','value':19.02}], 'records':[],
          'evidence':[{'id':'e1'}], 'limitations':[]}

def result(actions=None):
    return {'summary':'当前年度实际出货低于目标，需要核查订单交期。','causes':[],
            'recommendations':actions or [],'limitations':[], 'cardContract':'cockpit-cards-v1'}

def action():
    return {'id':'a1','actionType':'investigation','causeIds':[],'evidenceIds':['e1'],
            'action':'核对当前年度订单计划交期与实际发货记录','ownerRole':'待确认',
            'deadlineDays':5,'acceptance':'形成订单计划交期与实际发货差异核查清单',
            'ownerConfirmed':False,'deadlineConfirmed':False}

@pytest.mark.parametrize('stage',['opportunity','order','shipment','combined'])
def test_business_facts_without_verified_cause_require_next_step(stage):
    with pytest.raises(ValueError,match='根因未确认'):
        validate_reasoning(result(),EVIDENCE,stage=stage)

def test_evidence_only_investigation_survives_projection_and_draft(tmp_path):
    value=result([action()]);validate_reasoning(value,EVIDENCE,stage='shipment')
    item={'id':'a','status':'limited','context':{'stage':'shipment','stageName':'发货'},
          'result':value,'evidence':EVIDENCE}
    projected=project_card(item,'shipment-risk-summary')
    assert len(projected['result']['recommendations'])==1
    task=Store(tmp_path/'history.sqlite3').draft(item)
    assert task['measures'][0]['actionType']=='investigation'
    assert task['measures'][0]['causeIds']==[]

def test_no_facts_or_status_only_does_not_force_invented_actions():
    validate_reasoning(result(),{'facts':[],'records':[],'evidence':[]},stage='order')
    validate_reasoning(result(),EVIDENCE,stage='quotation')

def test_hypothesis_cannot_turn_into_unverified_remediation():
    a=action();a.update(actionType='remediation', action='调整产能保证交付')
    with pytest.raises(ValueError):validate_reasoning(result([a]),EVIDENCE,stage='shipment')
