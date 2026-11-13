"""Implemented AP contracts only. This module never stores or executes SQL."""
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path


@lru_cache(maxsize=1)
def registry():
    return json.loads((Path(__file__).parent/'assets/ap-query-capabilities.json').read_text(encoding='utf-8'))


def _signature(payload):
    config=payload.get('analysisConfig') or {}
    return (frozenset(x['identifierCode'] for x in config.get('indicators') or []),
            frozenset(x['identifierCode'] for x in config.get('dimensions') or []))


def _entry_signature(entry):
    return (frozenset(x['identifierCode'] for x in entry['columns'] if x['type']=='METRIC'),
            frozenset(x['identifierCode'] for x in entry['columns'] if x['type']=='DIMENSION'))


def _filters_match(payload, entry):
    contract=entry['filter_contract'];present=set()
    def check(node):
        if not isinstance(node,dict):return False
        if 'identifierCode' in node:
            code=node['identifierCode'];rule=contract.get(code);present.add(code)
            operator=node.get('operator') or {}
            op=operator.get('code') if isinstance(operator,dict) else operator
            return bool(rule and str(op).upper()==str(rule.get('op')).upper())
        return str(node.get('logic','AND')).upper() in {'AND','OR'} and all(check(c) for c in node.get('children') or [])
    return check((payload.get('commonConfig') or {}).get('filters') or {}) and all(
        rule.get('optional',False) or code in present for code,rule in contract.items())


def supported_entries(payload):
    if not isinstance(payload,dict):return []
    config=payload.get('analysisConfig') or {}
    for field in ('indicators','dimensions'):
        values=config.get(field) or []
        if not isinstance(values,list) or any(not isinstance(x,dict) or not x.get('identifierCode') for x in values):return []
        if len({x['identifierCode'] for x in values})!=len(values):return []
    wanted,dimensions=_signature(payload)
    return [entry for entry in registry()['queries'] if entry['query_type']=='METRIC'
            and entry.get('signingBasis')!='order_derived'
            and entry['query_key'].endswith('|_') and _entry_signature(entry)[1]==dimensions
            and _entry_signature(entry)[0]<=wanted and _filters_match(payload,entry)]


def is_registered(payload):
    return any(_entry_signature(e)==_signature(payload) for e in supported_entries(payload))


def project_requests(requests):
    """Partition on registered combinations; never remove filters or dimensions."""
    accepted=[];excluded=[]
    for request in requests:
        if isinstance(request,list):
            yes,no=project_requests(request);accepted.extend(yes);excluded.extend(no);continue
        entries=supported_entries(request)
        remaining=set(_signature(request)[0]);covered=set()
        for entry in sorted(entries,key=lambda e:(-len(_entry_signature(e)[0]),e['query_key'])):
            codes=set(_entry_signature(entry)[0])
            if not codes or not codes & remaining:continue
            value=deepcopy(request)
            value['analysisConfig']['indicators']=[x for x in value['analysisConfig']['indicators'] if x['identifierCode'] in codes]
            accepted.append(value);remaining-=codes;covered|=codes
        if remaining or not covered:excluded.append(deepcopy(request))
    return accepted,excluded


def implemented_stage_requests(stage, period):
    from .dashboard_source import filter_stage_selected, STAGE_METRICS
    from .periods import period_range
    bounds=period_range(period) if period else None
    if period and not bounds:return []
    requests=[]
    for entry in registry()['queries']:
        if entry['query_type']!='METRIC' or not entry['query_key'].endswith('|_') or entry.get('signingBasis')=='order_derived':continue
        columns=entry['columns'];contract=entry['filter_contract']
        codes=_entry_signature(entry)[0]
        known=set().union(*(STAGE_METRICS[x] for x in ('opportunity','order','shipment','quotation','bid')))
        if codes & known and not codes & STAGE_METRICS[stage]:continue
        dates=[code for code,rule in contract.items() if rule.get('type')=='DATE' and rule.get('op')=='BETWEEN']
        # Annual cards cannot silently use an all-time query or guess which
        # of several different business dates controls the metric.
        if bounds and len(dates)!=1:continue
        if any(not rule.get('optional',False) and code not in dates for code,rule in contract.items()):continue
        filters=[]
        if bounds:filters=[dict(identifierCode=dates[0],operator={'code':'BETWEEN','type':'DATE'},valueType='ABSOLUTE',value=list(bounds))]
        payload=dict(analysisConfig={
            'indicators':[{**{k:v for k,v in x.items() if k!='type'},'fieldType':'Indicator'} for x in columns if x['type']=='METRIC'],
            'dimensions':[{**{k:v for k,v in x.items() if k!='type'},'fieldType':'Dimension'} for x in columns if x['type']=='DIMENSION']},
            commonConfig=dict(filters={'logic':'AND','children':filters},pagination={'pageNum':1,'pageSize':500}))
        if entry.get('signingBasis')=='contract_confirmation':
            for field in payload['analysisConfig']['indicators']+payload['analysisConfig']['dimensions']:
                label=field.get('label','')
                label=label.replace('已签单','合同已签订').replace('未签单','合同签订未确认').replace('中标未签','中标合同签订未确认').replace('商机签单','合同签订确认状态')
                field['label']=label;field['alias']=label
        if filter_stage_selected({'candidate':{'request':payload}},stage)[0]:requests.append(payload)
    # Stable aggregate/status-first ordering; bounded model pre-read is unchanged.
    selected=[]
    for q in sorted(requests,key=lambda q:(-len(q['analysisConfig']['indicators']),json.dumps(q,sort_keys=True))):
        codes,dimensions=_signature(q)
        if any(dimensions==_signature(other)[1] and codes<=_signature(other)[0] and q['commonConfig']==other['commonConfig'] for other in selected):continue
        selected.append(q)
    aggregate=sorted([q for q in selected if not q['analysisConfig']['dimensions']],key=lambda q:not any('合同已签订' in x.get('label','') for x in q['analysisConfig']['indicators']))
    slices=[q for q in selected if q['analysisConfig']['dimensions']]
    ordered=[]
    while aggregate or slices:
        ordered.extend(aggregate[:2]);aggregate=aggregate[2:]
        ordered.extend(slices[:2]);slices=slices[2:]
    return ordered
