"""Build a cross-stage analysis exclusively from saved, same-period AP receipts."""
import json
from .dashboard_source import RELEASE, filter_stage_selected

STAGES = ('opportunity', 'order', 'shipment')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def date_scope(query):
    """Require explicit identical date ranges; do not infer dates from page labels."""
    dates = []
    def walk(value):
        if isinstance(value, dict):
            if (value.get('operator') or {}).get('type') == 'DATE':
                dates.append(canonical({k: value.get(k) for k in ('operator', 'value', 'valueType')}))
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(query)
    return tuple(sorted(dates))


def cached_combined_request(store, identity, cards):
    anchor = cards.get('shipment') or {}
    anchor_context = anchor.get('context') or {}
    raw = anchor_context.get('chartQueries') or []
    if not raw:
        raise ValueError('缺少发货查询口径，不能合并跨环节证据')
    period = date_scope(json.loads(raw[0]))
    if not period:
        raise ValueError('发货查询没有明确日期范围，不能自动合并')
    wanted = set()
    unavailable = set()
    for stage in STAGES:
        context = (cards.get(stage) or {}).get('context') or {}
        if context.get('id') != identity or context.get('filters'):
            continue
        if context.get('department') != anchor_context.get('department'):
            continue
        for key, target in [('chartQueries', wanted), ('unavailableQueries', unavailable)]:
            for encoded in context.get(key) or []:
                query = json.loads(encoded)
                if date_scope(query) == period:
                    target.add(canonical(query))
    found = {}
    # Read persisted receipts without extending their observation time or TTL.
    with store.db() as db:
        rows = db.execute('SELECT body FROM ap_results WHERE identity=? ORDER BY created DESC',
                          (identity,)).fetchall()
    connection = anchor_context.get('dataIdentity')
    for row in rows:
        receipt = json.loads(row[0])
        if receipt.get('kind') != 'analysis' or receipt.get('connectionId') != connection:
            continue
        key = canonical(receipt.get('request'))
        if key in wanted and key not in found:
            found[key] = receipt
    if not found:
        raise ValueError('没有可复用的同口径AP凭据，未触发数据库取数')
    if len(found) > 80:
        raise ValueError('共同分析凭据超出上限')
    coverage = []
    for stage in STAGES:
        kept, _ = filter_stage_selected({k: {'request': v['request']} for k, v in found.items()}, stage)
        if kept:
            coverage.append(stage)
    if len(coverage) < 2:
        raise ValueError('共同分析至少需要两个环节的同口径证据')
    missing = (unavailable | (wanted - set(found))) - set(found)
    return dict(id=identity, engine='main', source='service', page='analysis', stage='combined',
                period=anchor_context.get('period') or '2025-10',
                department=anchor_context.get('department') or '全部产品部', defaultView=True,
                chartSnapshotId=RELEASE, apReceiptIds=[v['id'] for v in found.values()],
                chartQueries=sorted(found), unavailableQueries=sorted(missing),
                clarifications={'coverage': ','.join(coverage),
                                'instruction': '仅复用已保存AP凭据；逐条披露观察时间，不把不同业务状态混算；跨环节仅做关联分析'})
