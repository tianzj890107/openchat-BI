"""Offline acceptance of reduced model work, AP-only evidence and task isolation."""
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from bi_agent.cockpit import pg_fallback
from bi_agent.cockpit.dashboard_source import executor
from bi_agent.cockpit.store import Store
from bi_agent.llm.runtime_config import get_config, request_config
from bi_agent.llm.provider_team import _thinking_extra_body
from bi_agent.reliability import QueryResult, claims_from_query_result


def test_paused_pg_never_compiles_or_connects(monkeypatch):
    monkeypatch.delenv('COCKPIT_PG_FALLBACK_ENABLED', raising=False)
    monkeypatch.setattr(pg_fallback, 'compile_payload', lambda *_: pytest.fail('compiled SQL'))
    monkeypatch.setattr(pg_fallback, 'query', lambda *_: pytest.fail('connected PG'))
    entries, notes = pg_fallback.supplement({'unavailableQueries':['{"query":1}']}, None)
    assert entries == {} and notes[0]['code'] == 'PG_FALLBACK_PAUSED'


def test_model_parameters_are_thread_scoped_and_restore(monkeypatch):
    original = get_config()
    before = original.to_dict()
    monkeypatch.setenv('TEAM_DEEPSEEK_ENABLE_THINKING', 'true')
    with request_config(thinking=False, max_tokens=4096):
        assert get_config().max_tokens == 4096
        assert _thinking_extra_body('DeepSeek-V4-Flash-0731', True) == {'thinking':{'type':'disabled'}}
        with ThreadPoolExecutor(1) as pool:
            assert pool.submit(lambda: get_config() is original).result()
    assert get_config() is original and original.to_dict() == before
    assert _thinking_extra_body('DeepSeek-V4-Flash-0731', False) == {'thinking':{'type':'enabled'}}
    with pytest.raises(RuntimeError):
        with request_config(thinking=False):
            raise RuntimeError('model failed')
    assert get_config() is original


def test_batched_evidence_keeps_query_identity_scope_and_numeric_claims():
    selected = {key:dict(request={'metric':key}, response={'result':{
        'columns':[{'identifierCode':'M1','label':'出货量'}],
        'rows':[{'M1':{'value':value}}]}},receiptId=key, source='ap')
        for key,value in [('first',10),('second',20)]}
    read = executor(selected, lean=True)
    output = read({'queryIds':['first','second']}, '')
    data = json.loads(output)
    assert len(data['data']['rows']) == 2
    assert data['scope']['queries']['first']['request'] == {'metric':'first'}
    claims = claims_from_query_result(QueryResult(data=output), 'batch')
    assert len(claims) == 2
    assert 'first ::' in claims[0].statement and 'second ::' in claims[1].statement
    for args in [{'queryIds':['first','first']}, {'queryIds':['foreign']}, {'queryId':'first','queryIds':['second']}]:
        with pytest.raises(ValueError):read(args, '')


def test_history_projection_is_small_and_does_not_remove_proof(tmp_path):
    store = Store(tmp_path/'history.sqlite3')
    body = dict(id='proof',scope='s',status='limited',context=dict(id=1,engine='main',period='2026',stage='shipment'),
                result={'summary':'有限证据'},evidence={'records':['x'*100000]},createdAt=1,updatedAt=2)
    with store.db() as db:
        db.execute('INSERT INTO analyses VALUES(?,?,?,?,?)',('proof','s',json.dumps(body), 'limited',2))
    result = store.analysis_summaries(1, engine='main', period='2026')
    assert len(result) == 1 and len(json.dumps(result)) < 1000
    assert not store.analysis_summaries(2)
    assert store.get_analysis('proof')['evidence'] == body['evidence']
