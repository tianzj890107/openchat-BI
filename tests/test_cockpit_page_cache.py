"""Whole pages require authoritative receipts and matching, complete AI publications."""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from fastapi import HTTPException

from bi_agent.cockpit.ap_gateway import APConfig
from bi_agent.cockpit.cards import CONTRACT
from bi_agent.cockpit.page_cache import APReuse, PageRequest, build_page, compact_analysis, page_scope, transport_identity
from bi_agent.cockpit.publications import digest
from bi_agent.cockpit.store import Store
from scripts.build_cockpit_site import build_site


def fixture(tmp_path):
    p=tmp_path/'headers.json';p.touch(mode=0o600);p.write_text(json.dumps({'X-App-Id':'test','Cookie':'session-A'}))
    config=APConfig('http://ap.example/api/gateway2',str(p),2,2,60)
    store=Store(tmp_path/'history.sqlite3')
    q={'analysisConfig':{'indicators':[{'identifierCode':'M0001'}]},'commonConfig':{'filters':{'department':'A'}}}
    data={'result':{'rows':[{'M0001':{'value':42}}]}}
    receipt=store.save_ap_result(1,'analysis',q,data,60,config.identity(),transport_identity(config))
    graph=store.save_ap_result(1,'helmet',{'flowCode':'SALES_CALIBER'},{'nodes':[]},60,config.identity(),transport_identity(config))
    fp=digest([(json.dumps(q,sort_keys=True),data)])
    ids={}
    for stage in ['shipment','opportunity']:
        ctx=dict(id=1,page='analysis',stage=stage,engine='main',dataSource='ap',dataIdentity=config.identity(),dataFingerprint=fp,chartQueries=[json.dumps(q)])
        item=store.create_analysis('scope-'+stage,ctx)
        store.update_analysis(item['id'],status='limited',result=dict(summary='Validated card',causes=[],recommendations=[],cardContract=CONTRACT),evidence={'facts':[],'records':[],'evidence':[]})
        ids[stage]=item['id']
    req=PageRequest(id=1,page='analysis',apReceiptIds=[receipt['id'],graph['id']],analysisIds=ids)
    return store,config,req,receipt


def test_full_page_survives_restart_but_not_wrong_role_filter_source_or_config(tmp_path):
    store,cfg,req,receipt=fixture(tmp_path)
    page=build_page(req,store,cfg);key=page_scope(cfg,1,'analysis','default')
    assert store.publish_page(key,page)
    assert Store(store.path).published_page(key)['items']['shipment']['result']['cardContract']==CONTRACT
    for other in [page_scope(cfg,2,'analysis','default'),page_scope(cfg,1,'operations','default'),page_scope(cfg,1,'analysis','other-filter')]:
        assert store.published_page(other) is None
    with patch('bi_agent.cockpit.page_cache.config_version',return_value='new-components'):
        assert store.published_page(page_scope(cfg,1,'analysis','default')) is None
    Path(cfg.headers_file).write_text(json.dumps({'X-App-Id':'test','Cookie':'session-B'}))
    assert store.published_page(page_scope(cfg,1,'analysis','default')) is None
    with patch('bi_agent.cockpit.store.time.time',return_value=time.time()+120):
        assert store.published_page(key)['version']==page['version']
        with pytest.raises(HTTPException):
            build_page(req,store,cfg)
    assert store.get_ap_result(receipt['id'],1,allow_expired=True)


def test_full_page_declares_and_binds_the_ap_source(tmp_path):
    store,cfg,req,_=fixture(tmp_path)
    page=build_page(req,store,cfg)
    assert page['dataSource']=='ap'
    assert page['dataIdentity']==cfg.identity()
    assert page['dataFingerprint']
    assert {item['context']['dataSource'] for item in page['items'].values()}=={'ap'}
    assert page_scope(cfg,1,'analysis','default','ap')!=page_scope(cfg,1,'analysis','default','postgres')


def test_full_page_rejects_ai_results_from_a_different_data_source(tmp_path):
    store,cfg,req,_=fixture(tmp_path)
    item=store.get_analysis(req.analysisIds['shipment'])
    context=deepcopy(item['context'])
    context['dataSource']='postgres'
    changed=store.create_analysis('wrong-source',context)
    store.update_analysis(changed['id'],status='limited',result={'summary':'validated','cardContract':CONTRACT})
    values=req.model_dump()
    values['analysisIds']['shipment']=changed['id']
    with pytest.raises(HTTPException):
        build_page(PageRequest(**values),store,cfg)


def test_legacy_ap_cards_republish_only_with_explicit_ap_provenance(tmp_path):
    store,cfg,req,_=fixture(tmp_path)
    ids={}
    for stage,aid in req.analysisIds.items():
        item=store.get_analysis(aid);context=deepcopy(item['context']);context.pop('dataSource')
        context.update(snapshotId='ap-legacy-'+stage,sourceMode='service')
        legacy=store.create_analysis('legacy-'+stage,context)
        store.update_analysis(legacy['id'],status='limited',result=item['result'],evidence=item['evidence'])
        ids[stage]=legacy['id']
    values=req.model_dump();values['analysisIds']=ids
    page=build_page(PageRequest(**values),store,cfg)
    assert {item['context'].get('snapshotId') for item in page['items'].values()}=={'ap-legacy-opportunity','ap-legacy-shipment'}

    item=store.get_analysis(ids['shipment']);context=deepcopy(item['context']);context['snapshotId']='dashboard-legacy'
    ambiguous=store.create_analysis('ambiguous-shipment',context)
    store.update_analysis(ambiguous['id'],status='limited',result=item['result'],evidence=item['evidence'])
    values['analysisIds']['shipment']=ambiguous['id']
    with pytest.raises(HTTPException):
        build_page(PageRequest(**values),store,cfg)


@pytest.mark.parametrize('bad',['missing-slot','wrong-data','wrong-role','missing-graph','duplicate-receipt','incomplete-card','failed-card'])
def test_incomplete_or_mixed_pages_cannot_replace_the_last_good_version(tmp_path,bad):
    store,cfg,req,_=fixture(tmp_path);good=build_page(req,store,cfg);key=page_scope(cfg,1,'analysis','default');store.publish_page(key,good)
    values=req.model_dump()
    if bad=='missing-slot':values['analysisIds'].pop('opportunity')
    elif bad=='wrong-role':values['id']=2
    elif bad=='missing-graph':values['apReceiptIds']=values['apReceiptIds'][:1]
    elif bad=='duplicate-receipt':values['apReceiptIds'].append(values['apReceiptIds'][0])
    else:
        item=store.get_analysis(req.analysisIds['shipment']);ctx=deepcopy(item['context'])
        if bad=='wrong-data':ctx['dataFingerprint']='different'
        changed=store.create_analysis('bad',ctx)
        store.update_analysis(changed['id'],status='failed' if bad=='failed-card' else 'limited',result={'summary':'partial'} if bad=='incomplete-card' else {'cardContract':CONTRACT})
        values['analysisIds']['shipment']=changed['id']
    with pytest.raises(HTTPException):build_page(PageRequest(**values),store,cfg)
    assert store.published_page(key)['version']==good['version']


def test_late_page_cannot_move_pointer_backwards_and_history_is_preserved(tmp_path):
    store,cfg,req,_=fixture(tmp_path);page=build_page(req,store,cfg);key=page_scope(cfg,1,'analysis','default')
    assert store.publish_page(key,page)
    older=dict(page,dataAsOf=page['dataAsOf']-1,version='old')
    assert not store.publish_page(key,older)
    assert store.published_page(key)['version']==page['version']
    with store.db() as db:
        assert db.execute('SELECT count(*) FROM analyses').fetchone()[0]==2
        assert db.execute('SELECT count(*) FROM ap_results').fetchone()[0]==2


def test_compact_cards_keep_ui_evidence_without_narrative_or_query_provenance(tmp_path):
    store,_,req,_=fixture(tmp_path);item=store.get_analysis(req.analysisIds['shipment'])
    item['result']['narrative']='full report'*100
    item['evidence']['evidence']=[{'id':'E1','record':{'id':'R1'},'provenance':{'sql':'large query'}}]
    slim=compact_analysis(item)
    assert slim['evidence']['evidence']==[{'id':'E1','record':{'id':'R1'}}]
    assert 'narrative' not in slim['result'] and 'narrative' in item['result']


def test_compact_cards_carry_analysis_duration_for_the_card_header(tmp_path):
    store,_,req,_=fixture(tmp_path);item=store.get_analysis(req.analysisIds['shipment'])
    item['execution']={'engine':'main','durationSeconds':42.6,'modelRounds':3,
                       'stopReason':'max_tokens','usage':{'input_tokens':10},
                       'route':{'intent':'analysis'}}
    slim=compact_analysis(item)
    assert slim['execution']=={'engine':'main','durationSeconds':42.6,
                               'modelRounds':3,'stopReason':'max_tokens'}


def test_short_ap_cache_coalesces_concurrent_reads_without_extending_receipt_time():
    reuse=APReuse(ttl=15);calls=[]
    def load():
        calls.append(1);time.sleep(.025)
        return {'receiptId':'original','createdAt':10,'expiresAt':time.time()+60}
    with ThreadPoolExecutor(max_workers=5) as pool:
        values=list(pool.map(lambda _:reuse.read('same',load),range(5)))
    assert len(calls)==1 and all(v['createdAt']==10 for v in values)
    reuse.read('other-role',load);assert len(calls)==2
    reuse=APReuse(ttl=0);reuse.read('same',load);reuse.read('same',load);assert len(calls)==4


def test_failed_ap_reads_are_not_cached():
    reuse=APReuse();calls=[]
    def fail():calls.append(1);raise RuntimeError('AP unavailable')
    for _ in range(2):
        with pytest.raises(RuntimeError):reuse.read('same',fail)
    assert len(calls)==2


def test_shared_query_follower_waits_for_the_full_ap_budget():
    reuse=APReuse();pending=Mock();pending.result.return_value={'receiptId':'shared'}
    reuse.pending['same']=pending
    trace={}
    assert reuse.read('same',lambda:{},timeout=200,trace=trace)=={'receiptId':'shared'}
    pending.result.assert_called_once_with(timeout=200)
    assert trace=={'cacheHit':False,'follower':True}


def test_site_build_uses_real_immutable_paths_and_valid_precompressed_assets(tmp_path):
    import gzip,hashlib
    site=tmp_path/'site';result=build_site(site)
    release=json.loads((site/'release.json').read_text());prefix=release['assets']
    html=(site/'index.html').read_text()
    assert prefix in html and '@@' not in html
    sdk=site/prefix.lstrip('/')/'vendor/pro-bi-ui.min.js'
    assert gzip.decompress(sdk.with_name(sdk.name+'.gz').read_bytes())==sdk.read_bytes()
    assert sdk.with_name(sdk.name+'.gz').stat().st_size < sdk.stat().st_size*.4
    for line in (site/'manifest.sha256').read_text().splitlines():
        expected,name=line.split('  ',1);assert hashlib.sha256((site/name).read_bytes()).hexdigest()==expected
    with pytest.raises(ValueError):build_site(site)


@pytest.mark.parametrize('page,required,optional',[('analysis',['opportunity','shipment'],['order']),('operations',['bid'],['quotation','order'])])
def test_default_page_accepts_additional_valid_allowed_stages(tmp_path,page,required,optional):
    store,cfg,req,_=fixture(tmp_path)
    template=store.get_analysis(req.analysisIds['shipment'])
    ids={}
    for stage in required+optional:
        ctx={**template['context'],'page':page,'stage':stage}
        item=store.create_analysis('extra-'+stage,ctx)
        store.update_analysis(item['id'],status='limited',result=template['result'],evidence=template['evidence'])
        ids[stage]=item['id']
    value=build_page(PageRequest(**{**req.model_dump(),'page':page,'analysisIds':ids}),store,cfg)
    assert set(value['items'])==set(required+optional)
    ids.pop(required[0])
    with pytest.raises(HTTPException) as failure:
        build_page(PageRequest(**{**req.model_dump(),'page':page,'analysisIds':ids}),store,cfg)
    assert required[0] in json.loads(failure.value.diagnostic_message)['missingStages']
