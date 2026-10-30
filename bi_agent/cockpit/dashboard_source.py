"""Read-only evidence bound to the exact results displayed by the cockpit."""
import hashlib
import json
import re
from pathlib import Path

SNAPSHOT = Path(__file__).parents[1] / "web/static/cockpit/metadata/pdt-release-2109836674373566465/data-snapshots.json"
RELEASE = "pdt-release-2109836674373566465"
TOOL = "Cockpit-DashboardQuery"
SCHEMA = {"name": TOOL, "description": "读取本轮看板实际展示的 AP 查询、字段口径和原始结果。只读本轮绑定的看板结果，可能为实时AP响应或显式交付快照，来源以工具返回为准。先读目录，再按 queryId 读取。禁止把采购字段解释为销售指标。", "input_schema": {"type": "object", "properties": {"queryId": {"type": "string"}}, "additionalProperties": False}}


# Metric/dimension codes that belong to one business stage.  Codes are only
# used when the AP payload carries an explicit YWLN_ identifier; legacy M/D
# codes are never normalised into YWLN_ codes because they mean different
# things (legacy M0001 is procurement, YWLN_M0001 is actual sales).
STAGE_METRICS = {
    'opportunity': {
        'YWLN_M0022', 'YWLN_M0023', 'YWLN_M0024', 'YWLN_M0038', 'YWLN_M0039',
        'YWLN_M0140', 'YWLN_M0075', 'YWLN_M_CUSTOMER_TARGET_ENERGY',
        'YWLN_M_CUSTOMER_ACTUAL_ENERGY', 'YWLN_D015', 'YWLN_D020',
    },
    'guidance': {'YWLN_D017', 'YWLN_M0028'},
    'quotation': {
        'YWLN_M0031', 'YWLN_M0050', 'YWLN_M0051', 'YWLN_M0131', 'YWLN_M0137',
        'YWLN_D021',
    },
    'technical': {'YWLN_D018'},
    'bid': {
        'YWLN_M0027', 'YWLN_M0030', 'YWLN_M0034', 'YWLN_M0047', 'YWLN_M0048',
        'YWLN_M0168', 'YWLN_M0169', 'YWLN_M0170', 'YWLN_M0171', 'YWLN_M0172',
        'YWLN_M0174', 'YWLN_M0175', 'YWLN_M0176', 'YWLN_M0177', 'YWLN_M0178',
        'YWLN_M0206', 'YWLN_M0256', 'YWLN_M0257', 'YWLN_D022',
    },
    'order': {
        'YWLN_M0032', 'YWLN_M0033', 'YWLN_M0142', 'YWLN_M0179', 'YWLN_M0194',
        'YWLN_M0198', 'YWLN_M0053', 'YWLN_M0054', 'YWLN_D016', 'YWLN_D023',
    },
    'shipment': {
        'YWLN_M0006', 'YWLN_M0007', 'YWLN_M0008', 'YWLN_M0010', 'YWLN_M0011',
        'YWLN_M0012', 'YWLN_M0035', 'YWLN_M0036', 'YWLN_M0037', 'YWLN_M0056',
        'YWLN_M0057', 'YWLN_M0134', 'YWLN_M0143', 'YWLN_M0144', 'YWLN_M0145',
        'YWLN_M0148', 'YWLN_M0149', 'YWLN_M0150', 'YWLN_M0151', 'YWLN_D024',
    },
}
STAGE_LABELS = {
    'opportunity': ('商机',),
    'guidance': ('方案引导', '方案'),
    'quotation': ('报价',),
    'technical': ('技术方案', '技术'),
    'bid': ('投标', '中标', '丢标', '弃标'),
    'order': ('订单接收', '订单', '签单', '接收'),
    'shipment': ('发货', '出货', '履约', '超期未发'),
}
STAGE_METRICS['combined'] = set().union(*(STAGE_METRICS[s] for s in ('opportunity', 'order', 'shipment')))
STAGE_LABELS['combined'] = tuple(label for s in ('opportunity', 'order', 'shipment') for label in STAGE_LABELS[s])
_CODE_RE = re.compile(r'YWLN_[DM]\d+')
_LABEL_KEYS = ('alias', 'label', 'name', 'identifierCode', 'title')


def request_text(request):
    return json.dumps(request, ensure_ascii=False)


def request_labels(request):
    """Human labels carried by an AP payload, for diagnostics and stage checks."""
    labels = []
    stack = [request]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            for key, child in value.items():
                if key in _LABEL_KEYS and isinstance(child, str) and child.strip():
                    labels.append(child.strip())
                stack.append(child)
        elif isinstance(value, list):
            stack.extend(value)
    return list(dict.fromkeys(labels))


def filter_stage_selected(selected, stage):
    """Keep only the evidence that belongs to the requested stage.

    A page can hold several delivered templates; the AI slot for one stage must
    never consume another stage's procurement/shipment numbers.
    """
    metrics = STAGE_METRICS.get(stage)
    labels = STAGE_LABELS.get(stage)
    if metrics is None or labels is None:
        raise ValueError('不支持的环节，不能选择看板证据')
    kept, excluded = {}, []
    for key, value in selected.items():
        text = request_text(value.get('request'))
        tokens = request_labels(value.get('request'))
        codes = set(_CODE_RE.findall(text)) | {token for token in tokens if token.startswith('YWLN_')}
        if codes & metrics or any(label in token for label in labels for token in tokens):
            kept[key] = value
        else:
            excluded.append(key)
    return kept, excluded


def unavailable_stage_evidence(context, stage):
    """Count failed AP queries that belong to this stage without using them as evidence."""
    items = {}
    for index, raw in enumerate(context.get('unavailableQueries') or []):
        if not isinstance(raw, str) or len(raw) > 20000:
            raise ValueError('无效的AP失败查询')
        try:
            request = json.loads(raw)
        except ValueError:
            raise ValueError('无效的AP失败查询') from None
        if not isinstance(request, (dict, list)):
            raise ValueError('无效的AP失败查询')
        items[str(index)] = {'request': request}
    kept, excluded = filter_stage_selected(items, stage)
    labels = []
    for value in kept.values():
        for token in request_labels(value['request']):
            if token in labels or token.startswith('YWLN_') or _CODE_RE.fullmatch(token):
                continue
            labels.append(token)
    return dict(failed=len(kept), excluded=len(excluded), labels=labels)


def stage_gap_result(context):
    """Server-owned limited card when a stage has no matching dashboard data."""
    from .cards import CONTRACT
    from .data import NAMES
    stage = context.get('stage')
    name = NAMES.get(stage, stage)
    gap = context.get('stageEvidence') or {}
    failed = int(gap.get('failed') or 0)
    failed_labels = [str(value) for value in gap.get('failedLabels') or [] if str(value).strip()]
    label_text = ('、'.join(failed_labels[:6]) + ('等' if len(failed_labels) > 6 else '')) if failed_labels else '指标'
    failure_note = (f'本环节有{failed}条指标查询失败（{label_text}），未纳入本轮证据。' if failed else '')
    limitations = [
        f'本次页面没有与{name}环节匹配的可用看板指标；已排除{gap.get("excluded", 0)}条无关查询，未用采购、发货等其他环节数据代替。',
        '没有同源业务明细或指标映射，不能生成原因与建议，也不代表该环节经营正常。',
        '上游数据不可用时不补造结论；请待指标恢复或补齐数据配置后重新分析。',
    ]
    if failure_note:
        limitations.insert(1, failure_note)
    summary = f'本次分析未取得{name}环节对应的看板指标，未生成原因与建议。' + (failure_note if failure_note else '')
    evidence = dict(
        sourceMode='service', dataSource=context.get('dataSource', ''),
        snapshotId=context.get('snapshotId', ''), stage=stage, stageName=name,
        period='以AP原始请求为准', department='以AP原始请求为准',
        facts=[], records=[], causes=[], evidence=[], limitations=limitations,
    )
    return dict(
        summary=summary, causes=[], recommendations=[], limitations=limitations,
        cardContract=CONTRACT, narrative=summary,
        sections=dict(summary=summary, causes='', recommendations=''),
        engine='main', policy=None, clarification=None,
        _status='limited', _evidence=evidence,
        _execution=dict(engine='main', durationSeconds=0.0, modelRounds=0,
            usage={}, toolCalls=0, route=None, stopReason='stage_no_evidence', claims=0),
    )


def material(context):
    if context.get('chartSnapshotId') != RELEASE:
        raise ValueError('缺少或不支持的看板快照标识，请从当前看板重新发起')
    queries = context.get('chartQueries') or []
    if not queries or len(queries) > 80:
        raise ValueError('必须指定当前看板已经展示的 AP 查询')
    snapshot = json.loads(SNAPSHOT.read_text())
    selected = {}
    for key in sorted(set(queries)):
        request = json.loads(key)
        canonical = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        section = 'batch' if isinstance(request, list) else 'analysis'
        hit = next((value for raw, value in snapshot[section].items()
                    if json.dumps(json.loads(raw), ensure_ascii=False, sort_keys=True, separators=(',', ':')) == canonical), None)
        if not hit or not hit.get('success') or not hit.get('data'):
            raise ValueError('查询没有对应的成功看板快照，不能换源补数')
        entries = list(zip(request,hit['data'])) if section=='batch' else [(request,hit)]
        if section=='batch' and len(request)!=len(hit['data']):raise ValueError('批量AP结果不完整')
        for index,(query,response) in enumerate(entries):
            if not response.get('success') or not response.get('data'):raise ValueError('批量AP子查询失败')
            query_id=hashlib.sha256((canonical+':'+str(index)).encode()).hexdigest()[:20]
            selected[query_id] = {'request': query, 'response': response['data']}
    fingerprint = hashlib.sha256(json.dumps(selected, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:20]
    return fingerprint, selected


def _receipt_id(value):
    return isinstance(value, str) and len(value) == 32 and all(c in '0123456789abcdef' for c in value)


def _query_keys(values):
    """Canonical page query set; the browser sends compact JSON strings."""
    keys = set()
    for raw in values or []:
        if not isinstance(raw, str) or len(raw) > 20000:
            raise ValueError('无效的页面查询')
        try:
            request = json.loads(raw)
        except ValueError:
            raise ValueError('无效的页面查询') from None
        if not isinstance(request, (dict, list)):
            raise ValueError('无效的页面查询')
        keys.add(json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(',', ':')))
    return keys


def receipt_scope(context, store, *, allow_expired=False, resolve_fallback=False):
    """Resolve receipts into evidence and optionally supplement failed queries from PG.

    Returns ``(fingerprint, selected, pg_receipt_ids, fallback_notes)``.  The page
    reports two disjoint sets: ``chartQueries`` are the queries it displayed
    successfully, ``unavailableQueries`` are the ones that failed.  AP receipts
    must cover exactly the first set; PostgreSQL supplements may only cover the
    second, so the merged evidence range stays auditable without pretending the
    failed query was an AP success.  Every supplement keeps ``source='pg'``.
    """
    if context.get('chartSnapshotId', RELEASE) != RELEASE:
        raise ValueError('看板发布标识不匹配')
    ids = context.get('apReceiptIds') or []
    pg_ids = context.get('pgReceiptIds') or []
    for group in (ids, pg_ids):
        if not isinstance(group, list) or len(group) > 80 or len(group) != len(set(group)):
            raise ValueError('无效的结果凭据列表')
    chart = _query_keys(context.get('chartQueries'))
    unavailable = _query_keys(context.get('unavailableQueries'))
    if chart & unavailable:
        raise ValueError('同一条查询不能同时列为成功和失败')
    if not chart and not unavailable:
        raise ValueError('必须指定本次页面成功展示或失败待补查的AP查询')
    selected = {}
    ap_requests = []
    pg_requests = []
    for receipt_id in sorted(ids):
        if not _receipt_id(receipt_id):
            raise ValueError('无效的AP结果凭据')
        item = store.get_ap_result(receipt_id, context['id'], allow_expired=allow_expired)
        if not item or item['kind'] not in {'analysis', 'batch'}:
            raise ValueError('AP结果凭据不存在、身份不匹配或已过期，请刷新图表取数')
        ap_requests.append(item['request'])
        entries = list(zip(item['request'], item['response'])) if item['kind'] == 'batch' else [(item['request'], {'data': item['response']})]
        for index, (request, response) in enumerate(entries):
            key = receipt_id + ':' + str(index)
            selected[key] = {'request': request, 'response': response['data'], 'receivedAt': item['createdAt'],
                             'source': 'ap', 'receiptId': receipt_id, 'connectionId': item.get('connectionId', ''),
                             'transport': item.get('transport', '')}
    for receipt_id in sorted(pg_ids):
        if not _receipt_id(receipt_id):
            raise ValueError('无效的数据库补查凭据')
        item = store.get_ap_result(receipt_id, context['id'], allow_expired=allow_expired)
        if not item or item['kind'] != 'pg':
            raise ValueError('数据库补查凭据不存在、身份不匹配或已过期，请重新分析')
        if item.get('authScope') and item['authScope'] != _fallback_version():
            raise ValueError('数据库补查口径已更新，请重新分析')
        pg_requests.append(item['request'])
        selected['pg:' + receipt_id] = {'request': item['request'], 'response': item['response'],
                                        'receivedAt': item['createdAt'], 'source': 'pg', 'receiptId': receipt_id,
                                        'connectionId': item.get('connectionId', ''), 'transport': item.get('transport', '')}
    notes = []
    if resolve_fallback:
        from . import pg_fallback
        extra, notes = pg_fallback.supplement(context, store, stage=context.get('stage'))
        for key, value in extra.items():
            if key not in selected:
                selected[key] = value
                pg_requests.append(value['request'])
    canonical = lambda v: json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    ap_scope = {canonical(value) for value in ap_requests}
    pg_scope = {canonical(value) for value in pg_requests}
    if ap_scope != chart:
        raise ValueError('结果凭据与页面查询范围不一致，拒绝回填')
    if not pg_scope <= unavailable:
        raise ValueError('数据库补查凭据与页面失败查询范围不一致，拒绝回填')
    if pg_scope & chart:
        raise ValueError('数据库补查凭据与页面成功查询范围重叠，拒绝回填')
    if not selected:
        raise ValueError('页面取数全部失败，且没有任何已登记口径可供补查，不能生成分析')
    fingerprint = hashlib.sha256(json.dumps(selected, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:20]
    pg_used = sorted({value['receiptId'] for value in selected.values() if value.get('source') == 'pg'})
    return fingerprint, selected, pg_used, notes


def _fallback_version():
    from . import pg_fallback
    return pg_fallback.version()


def receipt_material(context, store, *, allow_expired=False, resolve_fallback=False):
    """Resolve server receipts, never refetch or accept client-provided facts."""
    fingerprint, selected, _pg, _notes = receipt_scope(
        context, store, allow_expired=allow_expired, resolve_fallback=resolve_fallback)
    return fingerprint, selected


def evidence_source(selected):
    sources = {str(v.get('source') or '') for v in selected.values()}
    if sources == {'ap'}:
        return 'cockpit-ap', True
    if sources == {'pg'}:
        return 'cockpit-pg', True
    if sources == {'ap', 'pg'}:
        return 'cockpit-ap+pg', True
    return RELEASE, False


def fallback_notes_for_stage(notes, stage):
    """Reason codes for failed queries that belong to one stage."""
    items = {}
    for index, note in enumerate(notes or []):
        try:
            request = json.loads(note.get('query') or '')
        except (TypeError, ValueError):
            continue
        items[str(index)] = {'request': request, 'code': str(note.get('code') or '')}
    if not items:
        return []
    try:
        kept, _excluded = filter_stage_selected(items, stage)
    except ValueError:
        return []
    return list(dict.fromkeys(value['code'] for value in kept.values() if value['code']))


def _failure_queries(values):
    """Parse the browser-declared failed queries without accepting ambiguous shapes."""
    parsed = []
    for raw in values or []:
        if not isinstance(raw, str) or len(raw) > 20000:
            raise ValueError('无效的AP失败查询')
        try:
            request = json.loads(raw)
        except ValueError:
            raise ValueError('无效的AP失败查询') from None
        if not isinstance(request, (dict, list)):
            raise ValueError('无效的AP失败查询')
        parsed.append((raw, request))
    return parsed


def supplement_failed_queries(context, store, stages, *, limit=8):
    """Resolve the union of stage-relevant failed queries from PostgreSQL once.

    A whole-page refresh analyses several stages at once.  Running the fallback
    per stage would save different receipts and give each stage a different
    evidence fingerprint, so the page could never be assembled.  This resolves
    the union first; every stage then reuses the same ``pgReceiptIds``.
    """
    from . import pg_fallback
    failures = _failure_queries(context.get('unavailableQueries'))
    wanted = set()
    for stage in stages or ():
        keyed = {str(index): {'request': request} for index, (_raw, request) in enumerate(failures)}
        kept, _excluded = filter_stage_selected(keyed, stage)
        wanted.update(int(index) for index in kept)
    candidates, notes = [], []
    for index, (raw, request) in enumerate(failures):
        if index not in wanted:
            continue
        # Batch payloads are lists of single-table queries and have no reviewed
        # aggregate fallback; surface them instead of letting compile_payload
        # fail on the wrong shape.
        if not isinstance(request, dict):
            notes.append(dict(query=raw, code='BATCH_UNSUPPORTED'))
            continue
        candidates.append(raw)
    if not candidates:
        return {}, notes
    extra, blocked = pg_fallback.supplement(
        dict(context, stage=None, unavailableQueries=candidates), store, limit=limit)
    return extra, notes + blocked


def page_analysis_context(context, store, *, data_mode='ap', resolve_fallback=True,
                          fallback_notes=None, allow_expired=False):
    """Resolve one page-bound request into the main-service evidence snapshot.

    The HTTP route and the server-side refresh both call this function.  It is
    the only place that derives ``snapshotId``, the evidence fingerprint, the
    disclosed source mix and the per-stage coverage, so the two paths cannot
    drift apart (helmet graph data never enters business evidence).
    """
    from .publications import digest
    if context.get('repositoryId'):
        raise ValueError('看板快照分析不接受其他本体库绑定')
    if context.get('filters'):
        raise ValueError('筛选必须体现在已展示的AP请求中，不能声明未应用的自定义筛选')
    if data_mode != 'ap':
        if context.get('apReceiptIds') or context.get('pgReceiptIds'):
            raise ValueError('快照模式不能消费实时AP或补查凭据')
        fingerprint, selected = material(context)
        kept, excluded = filter_stage_selected(selected, context['stage'])
        failed = unavailable_stage_evidence(context, context['stage'])
        return dict(snapshotId='dashboard-' + fingerprint, repositoryId='', dataSource='snapshot',
                    dataIdentity='pdt-release-2109836674373566465', dataFingerprint=fingerprint,
                    dataBasis='当前看板已展示AP请求的服务端交付快照；实际筛选口径以原始AP请求为准，非实时数据库',
                    stageEvidence=dict(stage=context['stage'], kept=len(kept), excluded=len(excluded),
                                       available=len(selected), failed=failed['failed'],
                                       failedLabels=failed['labels']))
    from . import pg_fallback
    fingerprint, selected, pg_receipts, notes = receipt_scope(
        context, store, resolve_fallback=resolve_fallback, allow_expired=allow_expired)
    if fallback_notes is not None:
        notes = list(fallback_notes)
    identities = {value.get('connectionId', '') for value in selected.values() if value.get('source') == 'ap'}
    if len(identities) > 1:
        raise ValueError('AP材料来自不同连接，不能合并分析')
    kept, excluded = filter_stage_selected(selected, context['stage'])
    # Only queries that neither AP nor the registered fallback could answer
    # count as missing; covered ones are real evidence now.
    failed = unavailable_stage_evidence(
        {'unavailableQueries': [note['query'] for note in notes]}, context['stage'])
    fallback_metrics = sorted({
        str(column.get('identifierCode') or '')
        for value in kept.values() if value.get('source') == 'pg'
        for column in ((value.get('response') or {}).get('result') or {}).get('columns') or []
        if column.get('identifierCode')})
    blocked = fallback_notes_for_stage(notes, context['stage'])
    sources = {str(value.get('source') or '') for value in selected.values() if value.get('source')}
    data_source = '+'.join(sorted(sources)) if sources else 'ap'
    basis = '页面本次成功AP响应的服务端冻结结果；实际筛选以原始请求为准'
    if data_source == 'pg':
        basis = '页面本次AP取数全部失败；已按同一筛选口径从主库（PostgreSQL）补查，未混用AP结果'
    elif pg_receipts:
        basis += '；页面失败指标已按同一筛选口径从主库（PostgreSQL）补查，补查结果标注来源且与AP不可混算'
    return dict(
        snapshotId='ap-' + fingerprint, repositoryId='', dataSource=data_source,
        dataIdentity=(next(iter(identities)) if identities else 'postgres'), pgReceiptIds=pg_receipts,
        fallbackVersion=(pg_fallback.version() if pg_receipts else ''),
        fallback=dict(version=pg_fallback.version(), metrics=fallback_metrics, blocked=blocked,
                      attempted=len(notes) + len(pg_receipts)),
        dataFingerprint=digest(sorted(
            ((json.dumps(value['request'], sort_keys=True), value['response'])
             for value in selected.values()), key=lambda value: json.dumps(value, sort_keys=True))),
        dataBasis=basis,
        stageEvidence=dict(stage=context['stage'], kept=len(kept), excluded=len(excluded),
                           available=len(selected), failed=failed['failed'],
                           failedLabels=failed['labels'], fallbackMetrics=fallback_metrics,
                           fallbackBlocked=blocked,
                           receipts=sorted({value.get('receiptId', '') for value in kept.values()} - {''})))


def executor(selected, stage=None):
    source, live = evidence_source(selected)
    stage_metrics=STAGE_METRICS.get(stage) or set()
    stage_labels=STAGE_LABELS.get(stage) or ()

    def keep_column(column):
        if not stage:
            return True
        code=str(column.get('identifierCode') or '')
        if code in stage_metrics or code.startswith('YWLN_D') or re.fullmatch(r'D\d{4}', code):
            return True
        label=str(column.get('label') or '')
        return any(token in label for token in stage_labels)

    def project(result):
        if not stage or not isinstance(result, dict):
            return result
        columns=[column for column in result.get('columns', []) if keep_column(column)]
        codes={column.get('identifierCode') for column in columns}
        rows=[{key: cell for key, cell in row.items() if key in codes}
              for row in result.get('rows', []) if isinstance(row, dict)]
        return {**result, 'columns': columns, 'rows': [row for row in rows if row]}

    def read(params, cwd):
        query_id = params.get('queryId')
        if query_id:
            if query_id not in selected:
                raise ValueError('queryId不属于当前看板分析范围')
            entry = selected[query_id]
            result = project(entry['response'].get('result', {}))
            labels = {col['identifierCode']: col.get('label', col['identifierCode'])
                      for col in result.get('columns', []) if 'identifierCode' in col}
            rows = [{labels.get(code, code) + '[' + code + ']': cell.get('value') if isinstance(cell, dict) else cell
                     for code, cell in row.items()} for row in result.get('rows', []) if isinstance(row, dict)]
            return json.dumps({'queryId': query_id, **entry, 'source': source,
                'data': {'rows': rows}, 'scope': {'source': source, 'receiptId':entry.get('receiptId',''), 'request': entry['request']},
                'semantic': {'metric': query_id, 'definition': labels, 'live': live},
                'provenance': {'source': source, 'query': json.dumps(entry['request'], ensure_ascii=False)}}, ensure_ascii=False)
        return json.dumps({'source': source, 'live': live, 'queries': [
            {'queryId': key, 'request': value['request'],
             'columns': project(value['response'].get('result', {})).get('columns', [])}
            for key, value in selected.items()], 'limitations': '原始AP请求决定实际时间和部门口径；页面标题不构成字段定义。没有同源明细补查接口，不能认定根因。'}, ensure_ascii=False)
    return read
