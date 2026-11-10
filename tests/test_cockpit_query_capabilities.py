from copy import deepcopy
from bi_agent.cockpit.query_capabilities import registry,implemented_stage_requests,project_requests,is_registered


def test_export_manifest_has_enabled_implementations_without_executable_sql():
    source=registry()
    assert source['source']=='bp_local_analysis_query_202611101416'
    assert len(source['queries'])==154
    assert sum(e['query_type']=='METRIC' for e in source['queries'])==108
    assert all('sql_text' not in e for e in source['queries'])


def test_all_stage_queries_use_registered_combination_and_actual_business_date():
    for stage in ('opportunity','order','shipment','quotation','bid'):
        plans=implemented_stage_requests(stage,'2026-02')
        assert plans and all(is_registered(q) for q in plans)
        for q in plans:
            conditions=q['commonConfig']['filters']['children']
            assert len(conditions)==1 and conditions[0]['value']==['2026-02-01','2026-02-28']
    shipment=implemented_stage_requests('shipment','2026')
    assert any(q['commonConfig']['filters']['children'][0]['identifierCode']!='YWLN_D044' for q in shipment)


def test_partial_registered_metric_keeps_scope_and_rejects_missing_filter_mapping():
    q=implemented_stage_requests('quotation','2026')[0];before=deepcopy(q)
    q['analysisConfig']['indicators'].append(dict(identifierCode='YWLN_NOT_IMPLEMENTED'))
    accepted,excluded=project_requests([q])
    assert len(accepted)==1 and len(excluded)==1
    assert accepted[0]==before
    q=deepcopy(before)
    q['commonConfig']['filters']['children'].append(dict(identifierCode='UNKNOWN_FILTER',operator={'code':'IN'},value=['A']))
    assert project_requests([q])==([], [q])
    assert not is_registered(q)


def test_refresh_does_not_send_unimplemented_queries_to_ap(tmp_path):
    from tests.test_cockpit_refresh import Config
    from bi_agent.cockpit.refresh import RefreshManager
    from bi_agent.cockpit.store import Store
    calls=[]
    manager=RefreshManager(Store(tmp_path/'history.sqlite3'),Config(),lambda *args:calls.append(args) or {'value':1},lambda *_:None)
    manager.implemented_only=True
    q=implemented_stage_requests('quotation','2026')[0]
    q['analysisConfig']['indicators'].append(dict(identifierCode='UNKNOWN_METRIC'))
    records,failures=manager._query_requests(1,[q])
    assert len(records)==1 and len(failures)==1 and len(calls)==1
    assert all(x['identifierCode']!='UNKNOWN_METRIC' for x in calls[0][2]['analysisConfig']['indicators'])


def test_fixed_annual_never_supplements_unsupported_ap_with_sql(tmp_path):
    from tests.test_cockpit_refresh import Config
    from bi_agent.cockpit.refresh import RefreshManager
    from bi_agent.cockpit.store import Store
    manager=RefreshManager(Store(tmp_path/'history.sqlite3'),Config(),lambda *_:None,lambda *_:None)
    manager.implemented_only=True
    assert manager._supplement(1,['{}'],['shipment'])==({},[dict(query='{}',code='AP_ONLY_NO_SQL')])


def test_combined_can_read_registered_actual_sales_and_target_without_polluting_nodes():
    combined=implemented_stage_requests('combined','2026')
    codes={x['identifierCode'] for q in combined for x in q['analysisConfig']['indicators']}
    assert {'YWLN_M0001','YWLN_M0002'}<=codes
    for stage in ('opportunity','order','shipment','quotation','bid'):
        stage_codes={x['identifierCode'] for q in implemented_stage_requests(stage,'2026') for x in q['analysisConfig']['indicators']}
        assert 'YWLN_M0001' not in stage_codes


def test_duplicate_dimensions_are_rejected_before_ap_not_silently_rewritten():
    q=next(q for q in implemented_stage_requests('shipment','2026') if q['analysisConfig']['dimensions'])
    q['analysisConfig']['dimensions'].append(deepcopy(q['analysisConfig']['dimensions'][0]))
    assert not is_registered(q)
    assert project_requests([q])==([],[q])


def test_invalid_period_cannot_expand_to_all_time():
    assert implemented_stage_requests('shipment','invalid')==[]
