"""Build a cross-stage analysis exclusively from saved, same-period AP receipts."""
import json
from .cards import CONTRACT
from .dashboard_source import RELEASE, filter_stage_selected
from . import periods

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


def published_period_stage_cards(store, identity, period, *, data_identity=None):
    """Load the same-period, default-filter stage cards used by combined analysis."""
    period = periods.normalise(period)
    if not period:
        return {}
    cards = {}
    for stage in STAGES:
        hit = store.published_period(identity, period, stage, {},
                                     data_identity=data_identity)
        if not hit:
            continue
        item = store.get_analysis(hit['analysis_id'])
        context = (item or {}).get('context') or {}
        if (not item or item.get('status') not in {'completed', 'limited'}
                or (item.get('result') or {}).get('cardContract') != CONTRACT
                or int(context.get('id') or 0) != int(identity)
                or context.get('stage') != stage
                or periods.normalise(context.get('period')) != period):
            continue
        cards[stage] = item
    return cards


def cached_combined_request(store, identity, cards, period=None):
    requested_period = periods.normalise(period or '')
    # Use any stage that still has a saved query plan as the period anchor.
    # The combined card is a partial-data analysis: one missing stage must not
    # discard the stages that were actually retrieved.  At least two stages
    # are still required below so this cannot become a single-stage card.
    candidates = []
    for stage in ('shipment', 'order', 'opportunity'):
        item = cards.get(stage) or {}
        context = item.get('context') or {}
        if requested_period and periods.normalise(context.get('period')) != requested_period:
            continue
        candidates.append(item)
    anchor = next((item for item in candidates
                   if (item.get('context') or {}).get('chartQueries')), {})
    anchor_context = anchor.get('context') or {}
    raw = anchor_context.get('chartQueries') or []
    if not raw:
        raise ValueError('缺少可用的环节查询口径，不能合并跨环节证据')
    date_range = date_scope(json.loads(raw[0]))
    if not date_range:
        raise ValueError('环节查询没有明确日期范围，不能自动合并')
    wanted = set()
    unavailable = set()
    for stage in STAGES:
        context = (cards.get(stage) or {}).get('context') or {}
        if context.get('id') != identity or context.get('filters'):
            continue
        context_period = periods.normalise(context.get('period'))
        if requested_period and context_period != requested_period:
            continue
        if requested_period and not context_period:
            continue
        if context.get('department') != anchor_context.get('department'):
            continue
        for key, target in [('chartQueries', wanted), ('unavailableQueries', unavailable)]:
            for encoded in context.get(key) or []:
                query = json.loads(encoded)
                if date_scope(query) == date_range:
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
                period=requested_period or anchor_context.get('period') or periods.default_period(),
                department=anchor_context.get('department') or '全部产品部', defaultView=True,
                chartSnapshotId=RELEASE, apReceiptIds=[v['id'] for v in found.values()],
                chartQueries=sorted(found), unavailableQueries=sorted(missing),
                clarifications={'coverage': ','.join(coverage),
                                'instruction': '仅复用已保存AP凭据；逐条披露观察时间，不把不同业务状态混算；跨环节仅做关联分析'})


def cached_quotation_request(store, identity, card):
    """Use the helmet's quotation-state receipt, not the overview risk KPIs."""
    context = card.get('context') or {}
    queries = context.get('chartQueries') or []
    if context.get('id') != identity or not queries:
        raise ValueError('缺少当前角色报价分析口径')
    period = date_scope(json.loads(queries[0]))
    if not period:
        raise ValueError('报价日期口径不明确')
    with store.db() as db:
        rows = db.execute('SELECT body FROM ap_results WHERE identity=? ORDER BY created DESC',
                          (identity,)).fetchall()
    receipt = None
    for row in rows:
        item = json.loads(row[0]);query = item.get('request')
        if item.get('kind') != 'analysis' or item.get('connectionId') != context.get('dataIdentity'):
            continue
        config = (query or {}).get('analysisConfig') or {}
        dimensions = {v.get('identifierCode') for v in config.get('dimensions') or []}
        metrics = {v.get('identifierCode') for v in config.get('indicators') or []}
        if dimensions == {'YWLN_D021'} and metrics == {'YWLN_M0031'} and date_scope(query) == period:
            receipt = item
            break
    if receipt is None:
        raise ValueError('未保存同期间报价办理状态结果，未额外查询AP')
    return dict(id=identity, engine='main', source='service', page='operations', stage='quotation',
                period=context.get('period') or periods.default_period(),
                department=context.get('department') or '全部产品部', defaultView=True,
                chartSnapshotId=RELEASE, apReceiptIds=[receipt['id']],
                chartQueries=[canonical(receipt['request'])], unavailableQueries=[],
                clarifications={'instruction': '只分析运营头盔图报价节点的报价办理状态YWLN_D021及报价电量YWLN_M0031，'
                    '区分正常完成、逾期完成、逾期未完成、临期未完成、正常未完成；未返回状态不补造0。'
                    '不要引用经营看板红区报价单数或电芯占比。历史凭据的原始取数时间保持不变。'})


def cached_stage_request(store, identity, stage, card):
    """Explicit policy refresh using saved stage receipts without AP requests."""
    if stage not in ('opportunity', 'order', 'shipment'):
        raise ValueError('不支持的定向预热环节')
    context = card.get('context') or {}
    if context.get('id') != identity:
        raise ValueError('缺少当前角色的环节口径')
    wanted = {canonical(json.loads(q)) for q in context.get('chartQueries') or []}
    wanted = set(filter_stage_selected({q:{'request':json.loads(q)} for q in wanted},stage)[0])
    if not wanted:
        raise ValueError('没有该环节已保存的成功查询')
    found = {}
    with store.db() as db:
        rows = db.execute('SELECT body FROM ap_results WHERE identity=? ORDER BY created DESC',(identity,)).fetchall()
    for row in rows:
        item = json.loads(row[0])
        if item.get('kind') != 'analysis' or item.get('connectionId') != context.get('dataIdentity'):
            continue
        key = canonical(item.get('request'))
        if key in wanted:
            found.setdefault(key,item)
    if not found or len(found)>80:
        raise ValueError('缺少可复用的环节凭据，未触发外部取数')
    missing = (wanted-set(found)) | {canonical(json.loads(q)) for q in context.get('unavailableQueries') or []}
    missing -= set(found)
    return dict(id=identity, engine='main',source='service',page=context.get('page') or 'analysis',
                stage=stage,period=context.get('period') or periods.default_period(),
                department=context.get('department') or '全部产品部',defaultView=True,
                chartSnapshotId=RELEASE,apReceiptIds=[v['id'] for v in found.values()],
                chartQueries=sorted(found),unavailableQueries=sorted(missing),
                clarifications={'deliveryPolicy':'investigation-v1',
                    'instruction':'按新交付策略更新：有事实时给出有证据、有对象、有验收的核查建议；原因未确认不编造。复用历史凭据，观察时间保持原样。'})
