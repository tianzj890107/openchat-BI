"""Task-order v2: investigation/remediation separation and server-side selection."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bi_agent.cockpit.delivery import (
    draftable_actions, normalize_delivery_contract, project_card, recommendation_empty_state,
)
from bi_agent.cockpit.router import build_cockpit_router
from bi_agent.cockpit.store import Store


def evidence(ids=('e1',)):
    return {
        'facts': [dict(id=item, label='事实' + item) for item in ids],
        'records': [],
        'evidence': [dict(id=item, claim='记录' + item) for item in ids],
        'limitations': [],
    }


def cause(cid='c1', kind='hypothesis', status='hypothesis'):
    return dict(id=cid, kind=kind, title='交付阻塞待核实', description='处理记录提示存在阻塞，尚需核对',
                status=status, evidenceIds=['e1'], missingEvidence=['订单处理记录'])


def action(aid='a1', action_type='investigation', causes=('c1',), evidence_ids=('e1',), text=None,
           acceptance='提交包含订单、处理节点和阻塞项的核查清单'):
    return dict(id=aid, actionType=action_type, causeIds=list(causes), evidenceIds=list(evidence_ids),
                action=text or ('逐单核对逾期订单的当前处理节点' if action_type == 'investigation'
                                else '调整交付优先级并同步客户'),
                ownerRole='交付运营', ownerConfirmed=False, deadlineDays=5,
                deadlineConfirmed=False, acceptance=acceptance)


def card(actions=None, causes=None, summary='当前存在交付阻塞，需要核实。'):
    return dict(summary=summary, causes=causes if causes is not None else [cause()],
                recommendations=actions if actions is not None else [action()], limitations=[])


def test_hypothesis_can_create_an_investigation_task():
    selected, key = draftable_actions(card(), evidence(), ['a1'])
    assert [item['id'] for item in selected] == ['a1']
    assert selected[0]['actionType'] == 'investigation'
    assert key


def test_hypothesis_cannot_create_a_remediation_task():
    with pytest.raises(ValueError, match='尚未得到记录支持'):
        draftable_actions(card(actions=[action(action_type='remediation')]), evidence(), ['a1'])


def test_verified_cause_can_create_a_remediation_task():
    value = card(causes=[cause(kind='verified', status='supported')],
                 actions=[action(action_type='remediation')])
    selected, _ = draftable_actions(value, evidence(), ['a1'])
    assert selected[0]['actionType'] == 'remediation'


def test_verified_label_without_supported_status_cannot_upgrade_remediation():
    value = card(causes=[cause(kind='verified', status='hypothesis')],
                 actions=[action(action_type='remediation')])
    with pytest.raises(ValueError, match='尚未得到记录支持'):
        draftable_actions(value, evidence(), ['a1'])


def test_data_gap_investigation_can_cite_evidence_without_fabricating_a_cause():
    value = card(causes=[], actions=[action(causes=(), evidence_ids=('e1',))])
    selected, _ = draftable_actions(value, evidence(), ['a1'])
    assert selected[0]['causeIds'] == [] and selected[0]['evidenceIds'] == ['e1']


def test_dangling_cause_or_evidence_references_are_rejected():
    with pytest.raises(ValueError, match='不存在或已被过滤的原因'):
        draftable_actions(card(actions=[action(causes=('missing',))]), evidence(), ['a1'])
    with pytest.raises(ValueError, match='不存在的证据'):
        draftable_actions(card(actions=[action(evidence_ids=('missing',))]), evidence(), ['a1'])


def test_ambiguous_legacy_action_stays_pending_and_not_draftable():
    legacy = action(action_type=None, text='持续关注该事项', acceptance='完成相关工作')
    legacy.pop('actionType')
    normalized = normalize_delivery_contract(card(actions=[legacy]), evidence())
    assert normalized['recommendations'][0]['actionType'] == 'pending'
    with pytest.raises(ValueError, match='尚待确认'):
        draftable_actions(card(actions=[legacy]), evidence(), ['a1'])


def test_projection_keeps_data_gap_investigation_and_downgrades_invalid_remediation():
    value = card(
        causes=[cause('c1', 'verified', 'supported'), cause('c2', 'hypothesis', 'hypothesis')],
        actions=[action('a1', 'investigation', causes=(), evidence_ids=('e1',)),
                 action('a2', 'remediation', causes=('c2',), evidence_ids=('e1',))],
    )
    item = dict(id='fixture', status='limited', context=dict(stage='shipment'),
                result=value, evidence=evidence())
    projected = project_card(item, 'shipment-risk-summary')['result']
    actions = {item['id']: item for item in projected['recommendations']}
    assert actions['a1']['actionType'] == 'investigation'
    assert actions['a2']['actionType'] == 'pending'
    assert 'actionTypeIssue' in actions['a2']


@pytest.mark.parametrize('causes,recommendations,expected', [
    ([], [], '当前只能定位异常，缺少处理记录，尚未形成原因判断。'),
    ([cause()], [], '以下为待验证假设；当前无核查建议，暂不能生成任务草稿。'),
    ([cause()], [action()], '可先生成核查任务，改善措施待核实后补充。'),
])
def test_empty_state_copy_matches_the_actual_gap(causes, recommendations, expected):
    assert recommendation_empty_state(causes, recommendations) == expected


def _analysis(path, result):
    store = Store(path)
    item = store.create_analysis('task-order-scope', {'id': 1, 'stage': 'shipment', 'stageName': '发货'})
    return store, store.update_analysis(item['id'], status='completed', result=result, evidence=evidence())


def _client(tmp_path, dispatcher=None):
    app = FastAPI()
    app.include_router(build_cockpit_router(lambda: str(tmp_path), task_dispatcher=dispatcher))
    return TestClient(app)


def test_draft_endpoint_only_uses_selected_current_analysis_actions(tmp_path):
    _, analysis = _analysis(tmp_path / 'dataset/cockpit/history.sqlite3', card(
        actions=[action('a1'), action('a2', causes=(), text='补齐订单处理记录')]))
    client = _client(tmp_path)
    url = f"/api/cockpit/analyses/{analysis['id']}/draft"
    selected = client.post(url, json={'id': 1, 'recommendationIds': ['a1']})
    assert selected.status_code == 200, selected.text
    assert selected.json()['recommendationIds'] == ['a1']
    same = client.post(url, json={'id': 1, 'recommendationIds': ['a1']})
    assert same.json()['id'] == selected.json()['id']
    other = client.post(url, json={'id': 1, 'recommendationIds': ['a2']})
    assert other.status_code == 200 and other.json()['id'] != selected.json()['id']
    assert client.get('/api/cockpit/tasks/' + selected.json()['id']).status_code == 200


def test_draft_endpoint_rejects_unknown_closed_cross_identity_and_browser_text(tmp_path):
    _, analysis = _analysis(tmp_path / 'dataset/cockpit/history.sqlite3', card())
    client = _client(tmp_path)
    url = f"/api/cockpit/analyses/{analysis['id']}/draft"
    assert client.post(url, json={'id': 1, 'recommendationIds': ['closed']}).status_code == 409
    assert client.post(url, json={'id': 2, 'recommendationIds': ['a1']}).status_code == 403
    assert client.post(url, json={'id': 1, 'recommendationIds': ['a1'], 'title': '篡改正文'}).status_code == 422


def test_dispatch_requires_confirmation_and_blocks_duplicate_send(tmp_path):
    calls = []

    def dispatcher(*, actions, recipients, identity):
        calls.append((actions, recipients, identity))
        return [dict(accepted=True, status='ok', message='已提交', actionId=item['id']) for item in actions]

    _, analysis = _analysis(tmp_path / 'dataset/cockpit/history.sqlite3', card())
    client = _client(tmp_path, dispatcher)
    task = client.post(f"/api/cockpit/analyses/{analysis['id']}/draft", json={'id': 1, 'recommendationIds': ['a1']}).json()
    measure = dict(id=task['measures'][0]['id'], action=task['measures'][0]['action'], owner='交付运营',
                   deadline='5 个工作日', acceptance=task['measures'][0]['acceptance'])
    url = '/api/cockpit/tasks/' + task['id']
    draft = client.post(url, json={'id': 1, 'revision': task['revision'], 'action': 'save',
                                   'title': task['title'], 'goal': task['goal'], 'measures': [measure]})
    assert draft.status_code == 200
    blocked = client.post(url + '/dispatch', json={'id': 1, 'retry': False})
    assert blocked.status_code == 409 and '确认责任角色和期限' in blocked.json()['detail']

    confirmed = dict(measure, ownerConfirmed=True, deadlineConfirmed=True)
    saved = client.post(url, json={'id': 1, 'revision': draft.json()['revision'], 'action': 'save',
                                   'title': task['title'], 'goal': task['goal'], 'measures': [confirmed]})
    assert saved.status_code == 200
    sent = client.post(url + '/dispatch', json={'id': 1, 'retry': False})
    assert sent.status_code == 200 and sent.json()['accepted'] is True
    assert calls and calls[0][0][0]['content'].find('关联证据：e1') >= 0
    assert client.post(url + '/dispatch', json={'id': 1, 'retry': False}).status_code == 409


def test_store_draft_uses_full_analysis_not_display_slot_projection(tmp_path):
    store = Store(tmp_path / 'history.sqlite3')
    result = card(causes=[cause(kind='verified', status='supported')],
                  actions=[action(action_type='remediation')])
    analysis = dict(id='analysis-v2', context=dict(stage='shipment', stageName='发货'),
                    result=result, evidence=evidence())
    task = store.draft(analysis, ['a1'])
    assert task['recommendationIds'] == ['a1']
    assert task['measures'][0]['actionType'] == 'remediation'
