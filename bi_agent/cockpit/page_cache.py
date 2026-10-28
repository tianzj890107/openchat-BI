"""Server-validated, append-preserving whole-page publications and bounded AP reuse."""
from __future__ import annotations

from concurrent.futures import Future
from copy import deepcopy
import json
import threading
import time

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from .cards import CONTRACT
from .publications import config_version, digest


class PageLookup(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: int = Field(ge=1, le=2)
    page: Literal['overview', 'operations', 'analysis']
    uiScope: str = Field(default='default', min_length=1, max_length=16000)


class PageRequest(PageLookup):
    apReceiptIds: list[str] = Field(min_length=1, max_length=80)
    analysisIds: dict[str, str] = Field(default_factory=dict, max_length=5)


def transport_identity(config):
    # Rotating credentials invalidates response reuse; never store the credentials in SQLite.
    return digest({'base': config.base_url, 'headers': config.headers(), 'batchMode': config.batch_mode})


def page_scope(config, identity, page, ui_scope, data_source='ap'):
    return digest(dict(connection=transport_identity(config), id=identity, page=page,
                       uiScope=ui_scope, dataSource=data_source,
                       config=config_version(), contract=CONTRACT))


def legacy_page_scope(config, identity, page, ui_scope):
    """Read-only key for AP pages published before dataSource entered the scope."""
    return digest(dict(connection=transport_identity(config), id=identity, page=page,
                       uiScope=ui_scope, config=config_version(), contract=CONTRACT))


def analysis_source_matches(context, data_source):
    if context.get('dataSource') == data_source:
        return True
    # AP analyses stored before dataSource was introduced retain an AP snapshot
    # and the main-service source mode. They may rejoin another AP publication,
    # never a PostgreSQL or demo page.
    return (data_source == 'ap' and not context.get('dataSource')
            and context.get('sourceMode') == 'service'
            and str(context.get('snapshotId') or '').startswith('ap-'))


def compact_analysis(item):
    if not item:
        return None
    value = {k: deepcopy(item[k]) for k in ('id', 'status', 'context', 'createdAt', 'updatedAt',
                                           'progress', 'error') if k in item}
    result = item.get('result')
    value['result'] = ({k: deepcopy(result[k]) for k in
                       ('summary', 'causes', 'recommendations', 'limitations', 'cardContract') if k in result}
                      if result else None)
    evidence = item.get('evidence') or {}
    def record(value):
        if not isinstance(value,dict):return deepcopy(value)
        return {k:deepcopy(value[k]) for k in ('id','status','amount','unit','overdueDays','customer',
            'evidence','cause','causeSupport','product','department','quantity','value','name') if k in value}
    value['evidence'] = dict(limitations=deepcopy(evidence.get('limitations', [])),
        records=[record(v) for v in evidence.get('records', [])],
        facts=[{k:deepcopy(v[k]) for k in ('id','label','value','unit','definition','claim') if k in v}
               for v in evidence.get('facts', [])])
    # Cards use evidence IDs and linked records. Full query/provenance stays in history/report.
    value['evidence']['evidence'] = [
        {k: record(e[k]) if k=='record' else deepcopy(e[k]) for k in ('id', 'record') if k in e} for e in evidence.get('evidence', [])]
    value.get('context',{}).pop('apReceiptIds',None)
    return value


def build_page(req, store, config, *, data_source='ap'):
    if data_source not in {'ap', 'snapshot', 'postgres', 'demo'}:
        raise HTTPException(422, '整页数据来源无效')
    if len(set(req.apReceiptIds)) != len(req.apReceiptIds):
        raise HTTPException(422, '页面数据凭据重复')
    records = [store.get_ap_result(r, req.id) for r in req.apReceiptIds]
    connection = config.identity()
    auth = transport_identity(config)
    if any(not r or r.get('connectionId') != connection or r.get('authScope') != auth for r in records):
        raise HTTPException(422, '页面凭据已过期或不属于当前AP连接与身份')
    if req.page != 'overview' and not any(r['kind'] == 'helmet' for r in records):
        raise HTTPException(422, '整页缺少头盔图数据，保留上次完整版本')
    allowed = {'overview': set(), 'operations': {'bid', 'quotation', 'order'},
               'analysis': {'opportunity', 'order', 'shipment'}}[req.page]
    required = {'overview': set(), 'operations': {'bid'},
                'analysis': {'opportunity', 'shipment'}}[req.page]
    stages = set(req.analysisIds)
    if stages - allowed or (req.uiScope == 'default' and stages != required) or (
            req.page == 'analysis' and 'shipment' not in stages) or (req.page == 'operations' and not stages):
        raise HTTPException(422, 'AI插槽未完整交付，保留上次完整版本')
    business = [r for r in records if r['kind'] != 'helmet']
    if not business:
        raise HTTPException(422, '整页没有业务数据')
    canonical = lambda v: json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    queries = sorted({canonical(r['request']) for r in business})
    selected = []
    for r in business:
        if r['kind'] == 'batch':
            selected.extend((q, v['data']) for q, v in zip(r['request'], r['response']))
        else:
            selected.append((r['request'], r['response']))
    fingerprint = digest(sorted(((json.dumps(q, sort_keys=True), v) for q, v in selected),
                                key=lambda v: json.dumps(v, sort_keys=True)))
    items = {}
    for stage, aid in req.analysisIds.items():
        item = store.get_analysis(aid)
        c = (item or {}).get('context', {})
        if (not item or item['status'] not in {'completed', 'limited'}
                or (item.get('result') or {}).get('cardContract') != CONTRACT
                    or not analysis_source_matches(c, data_source)
                or any(c.get(k) != v for k, v in dict(id=req.id, page=req.page, stage=stage,
                                                     engine='main', dataIdentity=connection,
                                                     dataFingerprint=fingerprint,
                                                         ).items())
                or sorted({canonical(json.loads(q)) for q in c.get('chartQueries', [])}) != queries):
            raise HTTPException(422, '图表与AI的数据版本不一致，保留上次完整版本')
        items[stage] = compact_analysis(item)
    entries = [dict(kind=r['kind'], payload=r['request'], data=r['response'], receiptId=r['id'],
                    receivedAt=r['createdAt'], expiresAt=r['expiresAt']) for r in records]
    page = dict(id=req.id, page=req.page, uiScope=req.uiScope, entries=entries, items=items,
                dataSource=data_source, dataIdentity=connection, dataFingerprint=fingerprint,
                dataAsOf=min(r['createdAt'] for r in records), publishedAt=time.time(),
                configVersion=config_version(), cardContract=CONTRACT)
    page['version'] = digest({'entries': [(r['kind'], r['request'], r['response']) for r in records],
                              'analyses': req.analysisIds})[:24]
    if len(json.dumps(page, ensure_ascii=False).encode()) > 16 * 1024 * 1024:
        raise HTTPException(413, '整页数据过大，请缩小查询范围')
    return page


class APReuse:
    """Only successful receipts are reused; identical concurrent reads share one call."""
    def __init__(self, ttl=15, limit=256, byte_limit=32*1024*1024):
        self.ttl = ttl
        self.limit = limit
        self.lock = threading.Lock()
        self.values = {}
        self.pending = {}
        self.byte_limit = byte_limit
        self.sizes = {}
        self.bytes = 0

    def read(self, key, load):
        with self.lock:
            cached = self.values.get(key)
            if cached and time.time() < min(cached[0], cached[1]['expiresAt']):
                return deepcopy(cached[1])
            future = self.pending.get(key)
            leader = future is None
            if leader:
                future = self.pending[key] = Future()
        if not leader:
            return deepcopy(future.result(timeout=35))
        try:
            value = load()
            size = len(json.dumps(value, ensure_ascii=False).encode())
            with self.lock:
                if size <= self.byte_limit:
                    self.bytes -= self.sizes.pop(key,0)
                    self.values.pop(key,None)
                    self.values[key] = (time.time() + self.ttl, value)
                    self.sizes[key] = size
                    self.bytes += size
                    while len(self.values) > self.limit or self.bytes > self.byte_limit:
                        oldest = next(iter(self.values))
                        self.values.pop(oldest)
                        self.bytes -= self.sizes.pop(oldest)
            future.set_result(value)
            return deepcopy(value)
        except BaseException as exc:
            future.set_exception(exc)
            raise
        finally:
            with self.lock:
                self.pending.pop(key, None)
