"""Interactive card publication must also populate the period index."""

import json
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bi_agent.cockpit.cards import CONTRACT
from bi_agent.cockpit.refresh import record_period_publication
from bi_agent.cockpit.router import build_cockpit_router
from bi_agent.cockpit.store import Store


def _completed_analysis(store, context):
    item = store.create_analysis('interactive-period', context)
    store.update_analysis(
        item['id'], status='limited',
        result=dict(summary='card', causes=[], recommendations=[],
                    limitations=[], cardContract=CONTRACT),
        evidence={'facts': [], 'records': [], 'evidence': []},
    )
    return store.get_analysis(item['id'])


def test_completed_default_analysis_is_bound_to_the_period_index(tmp_path):
    store = Store(tmp_path / 'db.sqlite3')
    context = dict(id=1, engine='main', page='analysis', stage='shipment',
                   period='2025-10', defaultView=True, filters={},
                   dataIdentity='conn')
    item = _completed_analysis(store, context)

    key = record_period_publication(store, item['context'], item['id'], 'view-1')

    assert key
    hit = store.published_period(1, '2025-10', 'shipment', {},
                                 data_identity='conn')
    assert hit['analysis_id'] == item['id']
    assert (1, 'shipment', '2025-10') in store.published_stage_periods(
        data_identity='conn')


def test_custom_filter_analysis_does_not_claim_the_default_period(tmp_path):
    store = Store(tmp_path / 'db.sqlite3')
    context = dict(id=1, engine='main', page='analysis', stage='shipment',
                   period='2025-10', defaultView=True,
                   filters={'customer': 'S1'}, dataIdentity='conn')
    item = _completed_analysis(store, context)

    assert record_period_publication(store, item['context'], item['id'], 'view-2') == ''
    assert store.published_period(1, '2025-10', 'shipment', {}) is None


def test_completed_router_analysis_is_visible_to_period_readers(tmp_path):
    def run(_context, _cancel, _progress):
        return dict(summary='card', causes=[], recommendations=[],
                    limitations=[], cardContract=CONTRACT), []

    def context(_context):
        return dict(snapshotId='ap-interactive', dataSource='ap',
                    dataIdentity='conn', dataFingerprint='fp',
                    repositoryId='repo', stageEvidence={})

    app = FastAPI()
    app.include_router(build_cockpit_router(lambda: str(tmp_path),
                                            main_runner=run,
                                            main_context=context))
    client = TestClient(app)
    query = {'analysisConfig': {'indicators': [{'identifierCode': 'YWLN_M0035'}]}}
    task = client.post('/api/cockpit/analyses', json=dict(
        id=1, engine='main', source='service', stage='shipment',
        period='2025-10', defaultView=True, chartSnapshotId='release',
        chartQueries=[json.dumps(query)], apReceiptIds=['receipt-1'], filters={},
    )).json()
    for _ in range(100):
        done = client.get('/api/cockpit/analyses/' + task['id']).json()
        if done['status'] not in {'queued', 'running'}:
            break
        time.sleep(0.01)
    assert done['status'] == 'completed', done
    store = Store(tmp_path / 'dataset' / 'cockpit' / 'history.sqlite3')
    hit = store.published_period(1, '2025-10', 'shipment', {},
                                 data_identity='conn')
    assert hit and hit['analysis_id'] == task['id']
