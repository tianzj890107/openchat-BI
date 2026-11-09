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
import uuid
from urllib.parse import parse_qs

from fastapi import HTTPException
from starlette.responses import JSONResponse

from .diagnostics import diagnostic_scope, record_failure
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
        self.lock = threading.RLock()
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS annual_releases(
                    version TEXT PRIMARY KEY, body TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS annual_head(id INTEGER PRIMARY KEY, version TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS annual_job(
                    id INTEGER PRIMARY KEY, status TEXT NOT NULL, error TEXT NOT NULL, updated REAL NOT NULL);
            ''')
            db.execute('CREATE TABLE IF NOT EXISTS annual_progress(id INTEGER PRIMARY KEY,body TEXT NOT NULL)')
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
            progress = db.execute('SELECT body FROM annual_progress WHERE id=1').fetchone()
        body = json.loads(progress[0]) if progress else {}
        return dict(body, status=row[0], error=row[1], updatedAt=row[2]) if row else dict(status='idle', error='', updatedAt=0)

    def progress(self, **body):
        with self.db() as db:
            db.execute('INSERT INTO annual_progress VALUES(1,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body',
                       (json.dumps(body, ensure_ascii=False),))
            db.execute('UPDATE annual_job SET updated=? WHERE id=1', (time.time(),))

    def publish_stage(self, stage, item):
        # Keep every other stage at its last successful generation.
        if stage not in STAGES:
            raise ValueError('Unknown analysis stage')
        with self.lock:
            release = self.read()
            release.pop('version', None)
            release['items'][stage] = deepcopy(item)
            release['createdAt'] = time.time()
            release['basis'] = 'Customer manual annual analysis; stages publish independently. Evidence times and limitations belong to each card.'
            return self.publish(release)

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
        self.queue_lock = threading.RLock()
        self.pending, self.completed, self.failures = [], [], []
        self.active = ''
        self.round_id = ''
        self.deferred_combined = False

    def priority_order(self, slot_id=None, page=None, visible_slots=None):
        registry = {s['slotId']: s for s in slot_registry()}
        if slot_id and (not isinstance(slot_id, str) or slot_id not in registry):
            raise HTTPException(422, 'Unknown AI slot')
        if page and (not isinstance(page, str) or page not in {'overview', 'operations', 'analysis'}):
            raise HTTPException(422, 'Unknown page')
        if visible_slots is None:
            visible_slots = []
        if not isinstance(visible_slots, list) or len(visible_slots)>15 or any(not isinstance(v, str) or v not in registry for v in visible_slots):
            raise HTTPException(422, 'Invalid visible slots')
        candidates = ([registry[slot_id]['stage']] if slot_id else [])
        candidates += [registry[v]['stage'] for v in visible_slots]
        candidates += [s['stage'] for s in registry.values() if s['page']==page]
        return list(dict.fromkeys(candidates + list(STAGES)))

    def _progress(self):
        self.store.progress(runId=self.round_id,activeStage=self.active, pendingStages=list(self.pending),
                            completedStages=list(self.completed), failedStages=list(self.failures))

    def prioritize(self, slot_id=None, page=None, visible_slots=None):
        order = self.priority_order(slot_id, page, visible_slots)
        with self.queue_lock:
            if self.store.job()['status']=='running' and self.pending:
                self.pending[:] = [s for s in order if s in self.pending]
                if self.deferred_combined and 'combined' in self.pending:
                    inputs=[s for s in self.pending if s in {'opportunity','order','shipment'}]
                    rest=[s for s in self.pending if s not in inputs and s!='combined']
                    self.pending[:]=inputs+['combined']+rest
                self._progress()
        return dict(status=self.store.job()['status'], queued=False)

    def refresh(self, slot_id=None, page=None, visible_slots=None):
        order = self.priority_order(slot_id, page, visible_slots)
        if not self.recompute:
            raise HTTPException(503, 'Manual analysis executor unavailable')
        with self.queue_lock:
            if not self.store.claim():
                return self.prioritize(slot_id, page, visible_slots)
            self.pending, self.completed, self.failures = order, [], []
            self.round_id=uuid.uuid4().hex
            self.deferred_combined = False
            self.active = ''
            self._progress()
        def work():
            round_started=time.monotonic()
            try:
                if hasattr(self.recompute, 'run_stage'):
                    if hasattr(self.recompute, 'begin_round'):
                        self.recompute.begin_round(self.store.read()['period'])
                    deferred_combined = False
                    while True:
                        with self.queue_lock:
                            if not self.pending:
                                self.active = ''
                                self._progress()
                                self.store.finish(('partial' if self.completed else 'failed') if self.failures else 'published')
                                return
                            stage = self.pending.pop(0)
                            self.active = stage
                            self._progress()
                        started=time.monotonic()
                        phase='stage_execution'
                        try:
                            with diagnostic_scope(runId=self.round_id,stage=stage):
                                item = self.recompute.run_stage(self.store.read()['period'], stage)
                            phase='publication'
                            self.store.publish_stage(stage, item)
                            with self.queue_lock:
                                self.completed.append(stage)
                        except StageNotReady:
                            with self.queue_lock:
                                if stage=='combined' and self.pending and not deferred_combined:
                                    inputs=[s for s in self.pending if s in {'opportunity','order','shipment'}]
                                    rest=[s for s in self.pending if s not in inputs]
                                    self.pending[:]=inputs+[stage]+rest
                                    deferred_combined = True
                                    self.deferred_combined = True
                                else:
                                    from .store import Store
                                    diagnostic=record_failure(Store(self.store.path.parent/'history.sqlite3'),
                                        RuntimeError('Combined analysis requires two successful same-round source stages'),
                                        phase='dependency',stage=stage,run_id=self.round_id,duration=time.monotonic()-started)
                                    self.failures.append(dict(stage=stage,code='DEPENDENCY_NOT_READY',diagnosticId=diagnostic['diagnosticId']))
                        except Exception as exc:
                            from .store import Store
                            diagnostic=record_failure(Store(self.store.path.parent/'history.sqlite3'),exc,
                                phase=phase,stage=stage,run_id=self.round_id,duration=time.monotonic()-started)
                            with self.queue_lock:
                                self.failures.append(dict(stage=stage,code=type(exc).__name__,diagnosticId=diagnostic['diagnosticId']))
                        with self.queue_lock:
                            self.active = ''
                            self._progress()
                else:
                    # Compatibility with the old complete-release executor.
                    self.store.publish(self.recompute(self.store.read()['period']))
                    self.store.finish('published')
            except Exception as exc:
                from .store import Store
                diagnostic=record_failure(Store(self.store.path.parent/'history.sqlite3'),exc,
                    phase='refresh_coordinator',stage=self.active,run_id=self.round_id,duration=time.monotonic()-round_started)
                self.store.finish('failed', 'Background update did not finish; diagnosticId='+diagnostic['diagnosticId'])
        threading.Thread(target=work, name='cockpit-explicit-annual-analysis', daemon=True).start()
        return dict(queued=True, status='running')


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
        risk_counts = summarize_risk_counts(slots)
        # A presentation shortlist; preserve the full analysis and original total.
        for domain in ('sales', 'shipment'):
            entry = risk_counts.get(domain) or {}
            findings = (entry.get('findings') or [])[:3]
            entry.update(totalCount=entry.get('count', 0), count=len(findings),
                         findings=findings, findingKeys=[f.get('riskKey') or f.get('id') for f in findings],
                         displayLimited=True)
            risk_counts[domain] = entry
        return dict(scopeKey=ui_scope, requestedScope=ui_scope, requestedPeriod=release['period'],
            scopeMatch=True, displayScope='fixed-annual', publicationMode='fixed-annual',
            appliesToPageFilters=False, basis=release.get('basis', ''), manualUpdate=self.store.job(),
            registryVersion=REGISTRY_VERSION, contractVersion=CONTRACT, version=release['version'],
            expectedCount=len(slots), targetCount=len(slots), readyCount=len(slots),
            renderableCount=len(slots), publishedCount=len(slots), missingCount=0,
            completeCount=complete, limitedCount=len(slots)-complete, incompleteCount=len(slots)-complete,
            updatingCount=0, generatedAt=release['createdAt'], dataAsOf=release['createdAt'],
            riskCounts=risk_counts, update=dict(status='published', nextCheckAt=0, error=''), slots=slots)


class StageNotReady(RuntimeError):
    pass


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
            if path == '/api/cockpit/publications/priority' and scope['method']=='POST':
                from starlette.requests import Request
                body = await Request(scope, receive).json()
                return await JSONResponse(self.service.prioritize(body.get('slotId'),body.get('page'),body.get('visibleSlots')))(scope, receive, send)
            if scope['method'] == 'POST' and (path in {'/api/cockpit/analyses', '/api/cockpit/analyses/refresh',
                    '/api/cockpit/publications/refresh'} or path.endswith('/preheat')):
                from starlette.requests import Request
                body = await Request(scope, receive).json()
                # Background clients and old scope-change hooks cannot silently
                # spend a model call. Only the dedicated button sends manual.
                if body.get('manual') is True:
                    return await JSONResponse(self.service.refresh(body.get('slotId'),body.get('page'),body.get('visibleSlots')))(scope, receive, send)
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
        return asyncio.run(invoke('/api/cockpit/data/query', dict(id=identity,kind=kind,payload=payload)))['data']
    def start(body, resolved):
        response = asyncio.run(invoke('/api/cockpit/analyses/refresh', dict(body, refresh=True)))
        return response.get('analysis') or response.get('cached')
    store = Store(Path(cwd)/'dataset/cockpit/history.sqlite3')
    manager = RefreshManager(store, get_gateway().config, query, start)
    class Runner:
        def begin_round(self, period):
            self.fresh=set()
            manager.combined_fresh_stages=self.fresh

        def run_stage(self, period, stage):
            if stage=='combined' and len(self.fresh)<2:
                raise StageNotReady(stage)
            page = target_page(stage) or 'analysis'
            store.request_refresh(period_target_scope(1, page, stage, period), now=time.time())
            result = manager.preheat_period(1, page, stage, period, force=True)
            hit = store.published_period(1, period, stage, {}, data_identity=get_gateway().config.identity())
            if result.get('status') not in {'published', 'frozen'} or not hit:
                if stage=='combined' and result.get('status') in {'waiting-for-stages','awaiting-plan'}:
                    raise StageNotReady(stage)
                raise RuntimeError('Annual stage not ready: '+stage)
            item=store.get_analysis(hit['analysis_id'])
            if stage in {'opportunity','order','shipment'}:
                self.fresh.add(stage)
            return item
    return Runner()
