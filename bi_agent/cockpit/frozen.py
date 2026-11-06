"""Customer annual delivery: immutable first paint, explicit atomic replacement.

The preset is a delivery artifact, never a repository fixture or a claim that
customer live data has already been queried. Reads never start work.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import asyncio
import json
from pathlib import Path
import sqlite3
import threading
import time
from urllib.parse import parse_qs

from fastapi import HTTPException
from starlette.responses import JSONResponse

from .cards import CONTRACT, card_delivery_state, valid_card
from .delivery import project_card, publication_payload
from .page_cache import compact_analysis
from .risk import summarize_risk_counts
from .targets import REGISTRY_VERSION, slot_registry

STAGES = ('opportunity', 'order', 'shipment', 'quotation', 'bid', 'combined')


def validate_release(body):
    if not isinstance(body, dict) or not str(body.get('period', '')).isdigit() or len(str(body['period'])) != 4:
        raise ValueError('年度发布版必须有明确的四位年度')
    items = body.get('items') or {}
    for stage in STAGES:
        item = items.get(stage)
        context = (item or {}).get('context') or {}
        if (not valid_card(item) or item.get('status') not in {'completed', 'limited'}
                or context.get('stage') != stage or context.get('period') != body['period']):
            raise ValueError('年度发布版缺少可交付的同年度环节：' + stage)
    if any(not card_delivery_state(publication_payload(project_card(items[s['stage']], s['slotId'])),
                                    s['slotId'])['renderable'] for s in slot_registry()):
        raise ValueError('年度发布版未覆盖全部AI插槽')
    return body


class FrozenAnnualStore:
    def __init__(self, path, seed):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS annual_releases(
                    version TEXT PRIMARY KEY, body TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS annual_head(id INTEGER PRIMARY KEY, version TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS annual_job(
                    id INTEGER PRIMARY KEY, status TEXT NOT NULL, error TEXT NOT NULL, updated REAL NOT NULL);
            ''')
            db.execute("UPDATE annual_job SET status='failed',error='服务重启，本次更新未发布，继续使用上次版本',updated=? WHERE status='running'", (time.time(),))
        with self.db() as db:
            initialized = db.execute('SELECT 1 FROM annual_head WHERE id=1').fetchone()
        if not initialized:
            self.publish(json.loads(Path(seed).read_text(encoding='utf-8')))

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.execute('PRAGMA busy_timeout=30000')
        try:
            with db:
                yield db
        finally:
            db.close()

    def publish(self, body):
        body = deepcopy(validate_release(body))
        raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        version = hashlib.sha256(raw.encode()).hexdigest()
        with self.lock, self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT OR IGNORE INTO annual_releases VALUES(?,?,?)', (version, raw, time.time()))
            db.execute('INSERT INTO annual_head VALUES(1,?) ON CONFLICT(id) DO UPDATE SET version=excluded.version', (version,))
        return version

    def read(self):
        with self.db() as db:
            row = db.execute('SELECT r.version,r.body FROM annual_head h JOIN annual_releases r ON r.version=h.version WHERE h.id=1').fetchone()
        if not row:
            raise RuntimeError('缺少交付年度发布版；禁止以空白内容开放服务')
        return dict(json.loads(row[1]), version=row[0])

    def job(self):
        with self.db() as db:
            row = db.execute('SELECT status,error,updated FROM annual_job WHERE id=1').fetchone()
        return dict(status=row[0], error=row[1], updatedAt=row[2]) if row else dict(status='idle', error='', updatedAt=0)

    def claim(self):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT status FROM annual_job WHERE id=1').fetchone()
            if row and row[0] == 'running':
                return False
            db.execute("INSERT INTO annual_job VALUES(1,'running','',?) ON CONFLICT(id) DO UPDATE SET status='running',error='',updated=excluded.updated", (time.time(),))
        return True

    def finish(self, status, error=''):
        with self.db() as db:
            db.execute('UPDATE annual_job SET status=?,error=?,updated=? WHERE id=1', (status, error, time.time()))


class FrozenAnnualService:
    def __init__(self, store, recompute=None):
        self.store, self.recompute = store, recompute

    def refresh(self):
        if not self.recompute:
            raise HTTPException(503, '当前环境未配置手动分析执行器，继续使用发布版')
        if not self.store.claim():
            return dict(queued=False, status='running', message='后台正在重新分析，继续展示已发布版本')
        def work():
            try:
                candidate = self.recompute(self.store.read()['period'])
                self.store.publish(candidate)
                self.store.finish('published')
            except Exception:
                # Source errors may include credential-bearing URLs; keep the
                # public job message generic and never erase the release.
                self.store.finish('failed', '本次后台分析未完成，继续展示上次发布版')
        threading.Thread(target=work, name='cockpit-explicit-annual-analysis', daemon=True).start()
        return dict(queued=True, status='running', message='后台正在重新分析，继续展示已发布版本')

    def items(self, identity, page=None, release=None):
        release = release or self.store.read()
        stages = {s['stage'] for s in slot_registry() if page is None or s['page'] == page}
        items = {}
        for stage, raw in release['items'].items():
            if stage not in stages:
                continue
            item = compact_analysis(raw)
            item['context']['id'] = identity
            item['context']['publicationBasis'] = release.get('basis', '')
            items[stage] = item
        return items

    def envelope(self, identity, ui_scope='default'):
        release = self.store.read()
        items = self.items(identity, release=release)
        slots = {}
        for spec in slot_registry():
            item = items[spec['stage']]
            payload = publication_payload(project_card(item, spec['slotId']))
            delivery = card_delivery_state(payload, spec['slotId'])
            stamp = float(item.get('updatedAt') or release['createdAt'])
            slots[spec['slotId']] = dict(**spec, status='ready', contentStatus=delivery['status'],
                contentComplete=delivery['complete'], contentGaps=delivery['gaps'],
                evidenceCount=delivery['evidenceCount'], riskFindingCount=delivery['riskFindingCount'],
                generatedAt=stamp, dataAsOf=stamp, lastSuccessfulPublication=payload,
                lastSuccessfulAt=stamp, scopeMatch=True, periodMatch=True, displayScope='fixed-annual',
                refreshStatus='published', lastRefreshError='',
                update=dict(status='published', active=False, nextCheckAt=0), payload=payload)
        complete = sum(s['contentComplete'] for s in slots.values())
        return dict(scopeKey=ui_scope, requestedScope=ui_scope, requestedPeriod=release['period'],
            scopeMatch=True, displayScope='fixed-annual', publicationMode='fixed-annual',
            appliesToPageFilters=False, basis=release.get('basis', ''), manualUpdate=self.store.job(),
            registryVersion=REGISTRY_VERSION, contractVersion=CONTRACT, version=release['version'],
            expectedCount=len(slots), targetCount=len(slots), readyCount=len(slots),
            renderableCount=len(slots), publishedCount=len(slots), missingCount=0,
            completeCount=complete, limitedCount=len(slots)-complete, incompleteCount=len(slots)-complete,
            updatingCount=0, generatedAt=release['createdAt'], dataAsOf=release['createdAt'],
            riskCounts=summarize_risk_counts(slots), update=dict(status='published', nextCheckAt=0, error=''), slots=slots)


class FrozenCockpitSurface:
    """Customer-only boundary: only an explicit user action starts AI work."""
    def __init__(self, app, service, prefix=''):
        self.app, self.service, self.prefix = app, service, prefix.rstrip('/')

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        path = scope['path']
        if self.prefix and path.startswith(self.prefix + '/'):
            path = path[len(self.prefix):]
        query = parse_qs(scope.get('query_string', b'').decode())
        try:
            identity = int(query.get('id', ['1'])[0])
            if identity not in (1, 2):
                raise HTTPException(422, '无效身份')
            ui_scope = query.get('uiScope', ['default'])[0]
            if path == '/api/cockpit/ai-publications' and scope['method'] == 'GET':
                return await JSONResponse(self.service.envelope(identity, ui_scope))(scope, receive, send)
            if path in {'/api/cockpit/publications/cards','/api/cockpit/analyses/published'} and scope['method'] == 'GET':
                page = query.get('page', ['analysis'])[0]
                return await JSONResponse(dict(items=self.service.items(identity, page), cardContract=CONTRACT,
                    cardsVersion=self.service.store.read()['version']))(scope, receive, send)
            if path == '/api/cockpit/publications/status' and scope['method'] == 'GET':
                release = self.service.store.read()
                return await JSONResponse(dict(period=release['period'], periodMatch=True,
                    cardsVersion=release['version'], publicationVersion='', dataAsOf=release['createdAt'],
                    update=dict(status='published', nextCheckAt=0), manualUpdate=self.service.store.job()))(scope, receive, send)
            if scope['method'] == 'POST' and (path in {'/api/cockpit/analyses', '/api/cockpit/analyses/refresh',
                    '/api/cockpit/publications/refresh'} or path.endswith('/preheat')):
                from starlette.requests import Request
                body = await Request(scope, receive).json()
                # Background clients and old scope-change hooks cannot silently
                # spend a model call. Only the dedicated button sends manual.
                if body.get('manual') is True:
                    return await JSONResponse(self.service.refresh())(scope, receive, send)
                stage = body.get('stage') or 'combined'
                item = self.service.items(identity).get(stage)
                return await JSONResponse(dict(cached=item, analysis=None, refreshing=False,
                    dataFingerprint=(item or {}).get('context', {}).get('dataFingerprint'),
                    publicationMode='fixed-annual'))(scope, receive, send)
        except HTTPException as exc:
            return await JSONResponse({'detail': exc.detail}, status_code=exc.status_code)(scope, receive, send)
        # Startup/cards must also use the frozen release, so a late default
        # history response cannot replace first paint with another period.
        modify_json = path in {'/api/cockpit/startup', '/api/cockpit/bootstrap'}
        modify_html = path.startswith('/cockpit/')
        if not modify_json and not modify_html:
            return await self.app(scope, receive, send)
        messages = []
        async def capture(message):
            messages.append(message)
        inner_scope = dict(scope, headers=[(k,v) for k,v in scope.get("headers", []) if k.lower() != b"accept-encoding"])
        await self.app(inner_scope, receive, capture)
        start = next((m for m in messages if m['type'] == 'http.response.start'), None)
        if not start or start['status'] != 200:
            for m in messages:
                await send(m)
            return
        raw = b''.join(m.get('body', b'') for m in messages if m['type'] == 'http.response.body')
        # Strip Accept-Encoding before a future wrapper adds gzip; this wrapper
        # runs inside the original app's response boundary in the customer image.
        if modify_html:
            raw = raw.replace(b'</head>', b'<script>window.COCKPIT_FIXED_ANNUAL=true;</script></head>')
        else:
            data = json.loads(raw)
            data['publicationMode'] = 'fixed-annual'
            data['frozenAnnual'] = self.service.store.read()['period']
            if path.endswith('/startup'):
                page = query.get('page', ['analysis'])[0]
                data.update(cards=self.service.items(identity, page),
                    cardsByPage={p:self.service.items(identity,p) for p in ['overview','operations','analysis']},
                    cardsVersion=self.service.store.read()['version'])
            raw = json.dumps(data, ensure_ascii=False).encode()
        start = dict(start, headers=[(k,v) for k,v in start['headers'] if k.lower() not in {b'content-length', b'etag'}])
        start['headers'].append((b'content-length', str(len(raw)).encode()))
        await send(start)
        await send({'type':'http.response.body','body':raw})


def recompute_from_router(app, cwd):
    """Reuse the registered main-service executor; never add another LLM route."""
    from .ap_gateway import get_gateway
    from .refresh import RefreshManager
    from .store import Store
    from .targets import target_page
    from .refresh import period_target_scope
    import httpx
    async def invoke(path, body):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://internal') as client:
            response = await client.post(path, json=body)
            response.raise_for_status()
            return response.json()
    def query(identity, kind, payload):
        return asyncio.run(invoke('/api/cockpit/data/query', dict(id=identity,kind=kind,payload=payload)))['response']
    def start(body, resolved):
        response = asyncio.run(invoke('/api/cockpit/analyses/refresh', dict(body, refresh=True)))
        return response.get('analysis') or response.get('cached')
    store = Store(Path(cwd)/'dataset/cockpit/history.sqlite3')
    manager = RefreshManager(store, get_gateway().config, query, start)
    def recompute(period):
        items = {}
        for stage in STAGES:
            store.request_refresh(period_target_scope(1, target_page(stage) or "analysis", stage, period), now=time.time())
            result = manager.preheat_period(1, target_page(stage) or 'analysis', stage, period)
            hit = store.published_period(1, period, stage, {}, data_identity=get_gateway().config.identity())
            if result.get('status') not in {'published', 'frozen'} or not hit:
                raise RuntimeError('annual candidate not ready: '+stage)
            items[stage] = store.get_analysis(hit['analysis_id'])
        return dict(period=period, createdAt=time.time(), basis='客户环境手动生成的年度发布版；具体证据和限制见各卡片。', items=items)
    return recompute
