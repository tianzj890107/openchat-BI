import json
from copy import deepcopy

from bi_agent.cockpit.evidence_charts import chart_blocks
from bi_agent.cockpit.frozen import _evidence_html


def item(rows=None, metric='M1', unit='GWh'):
    scope={'source':'ap','receiptId':'receipt-a','request':{
        'analysisConfig':{'dimensions':[{'identifierCode':'D1','label':'月份'}],
                          'indicators':[{'identifierCode':metric,'label':'出货量','unit':unit}]},
        'commonConfig':{'filters':{'period':'2026'}}}}
    rows=rows if rows is not None else [('2026-02',0),('2026-01',3)]
    return {'id':'chart-proof','updatedAt':1,'result':{'summary':'证据分析'},
            'evidence':{'facts':[],'records':[{'id':f'r{i}','scope':scope,
                'data':{'月份[D1]':label,f'出货量[{metric}]':value}}
                for i,(label,value) in enumerate(rows)]}}


def test_charts_preserve_zero_sort_time_and_keep_provenance():
    value=item();before=deepcopy(value)
    block=chart_blocks(value)[0]
    assert block['params']['chart_type']=='line'
    assert block['params']['x_axis']==['2026-01','2026-02']
    assert block['params']['series'][0]['data']==[3,0]
    assert block['params']['unit']=='GWh'
    assert 'receipt-a' in block['params']['source_note'] and 'r0' in block['params']['source_note']
    assert value==before


def test_no_made_up_points_duplicates_or_cross_query_aggregation():
    assert chart_blocks(item([('A',3),('A',5)]))==[]
    assert chart_blocks(item([('A',None),('B',False),('C','-')]))==[]
    assert chart_blocks({'evidence':{'facts':[{'label':'amount','value':3}]}})==[]
    value=item([('A',3),('B',None),('C',2)])
    blocks=chart_blocks(value)
    assert blocks[0]['params']['series'][0]['data']==[3,2]
    assert '排除 1 条' in blocks[0]['params']['source_note']
    one=item([('A',3)])
    other=item([('B',5)])['evidence']['records'][0]
    other['scope']=deepcopy(other['scope']);other['scope']['receiptId']='other'
    one['evidence']['records'].append(other)
    assert chart_blocks(one)==[]


def test_html_contains_offline_charts_and_keeps_evidence_tables(monkeypatch,tmp_path):
    value=item()
    page=_evidence_html('shipment',value,{'period':'2026'})
    assert 'const CHARTS =' in page and '<canvas' not in page  # browser initializes canvas
    assert 'echarts.init' in page and '<table>' in page
    assert '<script src=' not in page
    assert 'receipt-a' in page
    from bi_agent.cockpit.frozen import _canvas_module
    monkeypatch.setattr(_canvas_module(),'ECHARTS_ASSET',tmp_path/'missing-echarts.js')
    fallback=_evidence_html('shipment',value,{'period':'2026'})
    assert '<script src=' not in fallback and '本地图表资源不可用' in fallback
    assert '<table>' in fallback
