"""Read-only evidence extracted from the supplied V3 HTML, with no invented rows."""
import hashlib
import json
import re
from pathlib import Path
from .data import NAMES


FIXTURE=Path(__file__).parent/'fixtures/v3-prototype.json'


def prototype():return json.loads(FIXTURE.read_text())
def text(value):return re.sub('<[^>]+>','',str(value)).replace('&nbsp;',' ')
def ring_for(p,stage,risk=False):
    if risk:return p[{'opportunity':'PROJ_RING','bid':'SALES_BID_RING','order':'SALES_ORDER_RING','shipment':'SALES_SHIP_RING'}[stage]]
    return p[{'opportunity':'S1_OPP_RING','order':'S1_ORDER_RING','shipment':'S1_SHIP_RING'}[stage]] if stage in {'opportunity','order','shipment'} else p['S1_STAGE_RINGS'][NAMES[stage]]
def ring_rows(ring):
    out=[]
    for group in ring['groups']:
        for seg in group.get('segs',[]):out.append(dict(name=group['n']+' · '+seg['g'] if group['n']!=seg['g'] else seg['g'],value=seg.get('v',0),group=group['n']))
    return out

class PrototypeSource:
    def snapshot(self, period='2025-10', department='全部产品部'):
        if period!='2025-10' or department!='全部产品部':
            raise ValueError('原型仅提供固定全产品部快照，缺少其他期间／产品部快照')
        p=prototype()
        return dict(snapshotId='prototype-'+hashlib.sha256(FIXTURE.read_bytes()+b'prototype-evidence-v1').hexdigest()[:20],sourceMode='prototype',period=period,department=department,
            asOf='原型固定快照（含跨年记录）',metrics=dict(actual=191.4,target=319,attainment=60,forecast=280,overdue=24.3),
            stages=[dict(id=k,name=v) for k,v in NAMES.items()],definitions=['图表与证据来自 V3 原型固定演示数据，非生产数据。',
                '原型包含2025／2026日期及39.6／44.6／45亿元订未发不同口径，不能合并对账。',
                '未来月份为原型已有业务预测，不是实时实绩。没有其他期间和产品部的完整独立快照。'])

    def evidence(self, snapshot, stage):
        p=prototype();rows=[]
        if stage=='shipment':
            for r in p['SHIP_EXEC_ROWS']:
                rows.append(dict(id=r['so'],customer=r['cust'],department=r['biz'],amount=r['amt'],overdueDays=r['days'],
                    cause=r['cause'],status='超期未发',commitment=r['promise'],evidence=r['detail']))
        elif stage=='opportunity':
            for r in p['OPP_ROWS']:
                rows.append(dict(id=text(r[0]),customer=text(r[1]),department=text(r[3]),amount=float(r[5]),
                    product=None,overdueDays=None,status=text(r[9]),cause=text(r[11]),evidence='原型商机台账；客户分级：'+text(r[2])))
        elif stage=='order':
            for r in p['SALES_ORDER_RISK_ROWS']:
                rows.append(dict(id=r['id'],customer=r['customer'],department='原型未提供',amount=r['amt'],product=r['product'],
                    overdueDays=None,status=r['type'],cause=r['cause'],evidence=r['action']))
        else:
            deep=p['S1_STAGE_DEEP'].get(NAMES[stage],{})
            for r in deep.get('exceptions',[]):
                rows.append(dict(id=text(r[0]),customer=text(r[1]),department=text(r[2]),amount=None,volume=r[3],
                    overdueDays=None,status='原型异常项目',cause=text(r[4]),evidence=text(r[5])))
        ring=ring_for(p,stage,stage in {'opportunity','bid','order','shipment'})
        facts=[dict(id=f'{stage}:state:{i}',label=r['name'],value=r['value'],unit='亿元' if stage in {'opportunity','bid'} else 'GWh',
            definition='原型环图分类值；各环节独立口径，不能跨环节相加') for i,r in enumerate(ring_rows(ring))]
        if stage=='shipment':facts.append(dict(id='shipment:overdue',label='超期未发金额',value=24.3,unit='亿元',definition='原型超期订单逐单金额合计'))
        amounts={}
        if stage=='shipment':
            for r in rows:amounts[r['cause']]=round(amounts.get(r['cause'],0)+r['amount'],3)
        evidence=facts+[dict(id=r['id'],label=r['customer'],value=r['amount'],unit='亿元' if r['amount'] is not None else '',definition=r['cause']+'；'+r['evidence'],record=r) for r in rows]
        return dict(snapshotId=snapshot['snapshotId'],sourceMode='prototype',stage=stage,stageName=NAMES[stage],period=snapshot['period'],department=snapshot['department'],
            facts=facts,records=rows,evidence=evidence,causes=[dict(name=k,amount=v) for k,v in amounts.items()],
            limitations=snapshot['definitions']+['原型未提供的记录、根因和字段均不能推断；分类数据不能证明因果关系。'])
