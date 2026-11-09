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
from starlette.responses import JSONResponse, Response

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

    def head_version(self):
        with self.db() as db:
            return db.execute("SELECT version FROM annual_head WHERE id=1").fetchone()[0]

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
        self.phase = 'idle'
        self.detail = {}
        self._publication_cache = {}
        self.publication_lock = threading.Lock()

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
                            completedStages=list(self.completed), failedStages=list(self.failures),
                            phase=self.phase, progress=self.detail, heartbeatAt=time.time())

    def report_progress(self, phase, **detail):
        with self.queue_lock:
            self.phase, self.detail = phase, {**detail, 'lastProgressAt':time.time()}
            self._progress()

    def _job_response(self, queued):
        job = self.store.job()
        return dict(queued=queued, status=job.get('status', 'idle'), manualUpdate=job)

    def _requeue(self, stage):
        if not stage or self.active == stage:
            return
        self.pending[:] = [item for item in self.pending if item != stage]
        self.completed[:] = [item for item in self.completed if item != stage]
        self.failures[:] = [item for item in self.failures if item.get('stage') != stage]
        self.pending.insert(0, stage)

    def prioritize(self, slot_id=None, page=None, visible_slots=None, requeue=False):
        order = self.priority_order(slot_id, page, visible_slots)
        with self.queue_lock:
            if self.store.job()['status']=='running':
                if requeue and slot_id:
                    self._requeue(order[0])
                self.pending[:] = [s for s in order if s in self.pending]
                self._progress()
        return self._job_response(False)

    def refresh(self, slot_id=None, page=None, visible_slots=None):
        order = self.priority_order(slot_id, page, visible_slots)
        if not self.recompute:
            raise HTTPException(503, 'Manual analysis executor unavailable')
        with self.queue_lock:
            if not self.store.claim():
                return self.prioritize(slot_id, page, visible_slots, requeue=True)
            self.pending, self.completed, self.failures = order, [], []
            self.round_id=uuid.uuid4().hex
            self.active = ''
            self.phase, self.detail = 'queued', {}
            self._progress()
        def work():
            round_started=time.monotonic()
            own_run=self.round_id
            stopped=threading.Event()
            def heartbeat():
                while not stopped.wait(5):
                    with self.queue_lock:
                        if self.round_id!=own_run:return
                        self._progress()
            threading.Thread(target=heartbeat,name='cockpit-round-heartbeat',daemon=True).start()
            try:
                if hasattr(self.recompute, 'run_stage'):
                    if hasattr(self.recompute, 'begin_round'):
                        self.recompute.begin_round(self.store.read()['period'])
                    if hasattr(self.recompute,'set_progress'):self.recompute.set_progress(self.report_progress)
                    while True:
                        with self.queue_lock:
                            if not self.pending:
                                self.active = ''
                                self._progress()
                                self.store.finish(('partial' if self.completed else 'failed') if self.failures else 'published')
                                return
                            stage = self.pending.pop(0)
                            self.active = stage
                            self.phase, self.detail = 'fetching', {'startedAt':time.time()}
                            self._progress()
                        started=time.monotonic()
                        phase='stage_execution'
                        try:
                            with diagnostic_scope(runId=self.round_id,stage=stage):
                                item = self.recompute.run_stage(self.store.read()['period'], stage)
                            if (item.get('execution') or {}).get('stopReason')=='stage_no_evidence':
                                raise RuntimeError('No matching evidence; retain previous published card')
                            phase='publication'
                            self.report_progress('publishing')
                            self.store.publish_stage(stage, item)
                            with self.queue_lock:
                                self.completed.append(stage)
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
            finally:
                stopped.set()
                with self.queue_lock:
                    if self.round_id==own_run:
                        self.active=''
                        self.phase='idle'
                        self._progress()
        threading.Thread(target=work, name='cockpit-explicit-annual-analysis', daemon=True).start()
        return self._job_response(True)


    def compact_publications(self, identity):
        version=self.store.head_version()
        with self.publication_lock:
            key=(identity,version)
            if key not in self._publication_cache:
                self._publication_cache={k:v for k,v in self._publication_cache.items() if k[1]==version}
                envelope=self.envelope(identity)
                grouped={}
                for sid,slot in envelope['slots'].items():
                    stage=slot['stage']
                    bundle=grouped.setdefault(stage,{'slots':{},'evidence':None})
                    payload=slot['payload']
                    if bundle['evidence'] is None:
                        bundle['evidence']=browser_evidence(payload.get('evidence') or {})
                    value={k:v for k,v in slot.items() if k not in {'lastSuccessfulPublication','payload'}}
                    value['payload']={k:v for k,v in payload.items() if k!='evidence'}
                    bundle['slots'][sid]=value
                from .publications import digest
                versions={}
                for stage,bundle in grouped.items():
                    stable=deepcopy(bundle)
                    for slot in stable['slots'].values():
                        (slot['payload'].get('context') or {}).pop('publicationBasis',None)
                    versions[stage]=digest(stable)
                manifest={k:v for k,v in envelope.items() if k not in {'slots','manualUpdate'}}
                manifest['transport']='stage-manifest-v1'
                manifest['stageVersions']=versions
                manifest['slots']={sid:{k:v for k,v in slot.items() if k not in {'payload','lastSuccessfulPublication'}} for sid,slot in envelope['slots'].items()}
                self._publication_cache[key]=(manifest,grouped)
            return self._publication_cache[key]

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


def browser_evidence(evidence):
    """Keep rendering facts and references; full proof stays in analysis history."""
    value={k:deepcopy(v) for k,v in evidence.items() if k not in {'facts','records','evidence'}}
    value['facts']=[{k:deepcopy(v) for k,v in fact.items() if k in {'id','label','value','unit','definition'}} for fact in evidence.get('facts') or []]
    value['records']=deepcopy(evidence.get('records') or [])
    records={str(v.get('id')):v for v in value['records']}
    value['evidence']=[{'id':entry['id'],**({'record':records[str(entry['id'])]} if str(entry.get('id')) in records else {})} for entry in evidence.get('evidence') or [] if entry.get('id')]
    return value


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
            if path == '/api/cockpit/ai-publications' and scope['method']=='GET' and query.get('format')==['manifest']:
                manifest,_=await asyncio.to_thread(self.service.compact_publications,identity)
                value={**manifest,'scopeKey':ui_scope,'requestedScope':ui_scope,'manualUpdate':self.service.store.job()}
                return await JSONResponse(value,headers={'Cache-Control':'no-store'})(scope,receive,send)
            if path.startswith('/api/cockpit/ai-publications/stages/') and scope['method']=='GET':
                parts=path[len('/api/cockpit/ai-publications/stages/'):].split('/')
                stage=parts[0]
                if stage not in STAGES or len(parts)>2 or (len(parts)==2 and parts[1]!='evidence'):raise HTTPException(422,'无效分析环节')
                if len(parts)==2:
                    release=await asyncio.to_thread(self.service.store.read)
                    item=release['items'][stage]
                    expected=query.get('analysisId',[''])[0]
                    if expected and expected!=item['id']:raise HTTPException(409,'该环节分析已更新，请重新打开证据')
                    response=await asyncio.to_thread(lambda:JSONResponse(dict(analysisId=item['id'],stage=stage,period=release['period'],dataAsOf=item.get('updatedAt'),evidence=item.get('evidence') or {}),headers={'Cache-Control':'private, no-store'}))
                    return await response(scope,receive,send)
                manifest,groups=await asyncio.to_thread(self.service.compact_publications,identity)
                version=manifest['stageVersions'][stage]
                headers=dict(scope.get('headers') or [])
                if headers.get(b'if-none-match',b'').decode()==('"'+version+'"'):
                    return await Response(status_code=304,headers={'ETag':'"'+version+'"','Cache-Control':'private, no-cache'})(scope,receive,send)
                value={'stage':stage,'version':version,**groups[stage]}
                return await JSONResponse(value,headers={'ETag':'"'+version+'"','Cache-Control':'private, no-cache'})(scope,receive,send)
            if path == '/api/cockpit/ai-publications' and scope['method'] == 'GET':
                response=await asyncio.to_thread(lambda:JSONResponse(self.service.envelope(identity,ui_scope)))
                return await response(scope,receive,send)
            if path in {'/api/cockpit/publications/cards','/api/cockpit/analyses/published'} and scope['method'] == 'GET':
                page = query.get('page', ['analysis'])[0]
                return await JSONResponse(dict(items=self.service.items(identity, page), cardContract=CONTRACT,
                    cardsVersion=self.service.store.read()['version']))(scope, receive, send)
            if path == '/api/cockpit/publications/status' and scope['method'] == 'GET':
                release = self.service.store.read()
                return await JSONResponse(dict(period=release['period'], periodMatch=True,
                    cardsVersion=release['version'], publicationVersion='', dataAsOf=release['createdAt'],
                    update=dict(status='published', nextCheckAt=0), manualUpdate=self.service.store.job()))(scope, receive, send)
            if path == '/api/cockpit/page' and scope['method']=='POST':
                # Old browser bundles may still attempt a whole-page merge.
                # Annual cards publish independently; never couple them to charts.
                return await JSONResponse(dict(accepted=False, skipped=True,
                    reason='fixed-annual-independent-publications', snapshot=None))(scope, receive, send)
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
    import os
    timeout=max(60,min(1800,int(os.getenv('COCKPIT_MANUAL_ANALYSIS_TIMEOUT_SECONDS','600'))))
    manager = RefreshManager(store, get_gateway().config, query, start, timeout=timeout)
    class Runner:
        def begin_round(self, period):
            manager.round_queries={}

        def set_progress(self, callback):
            manager.progress_callback=callback

        def run_stage(self, period, stage):
            page = target_page(stage) or 'analysis'
            store.request_refresh(period_target_scope(1, page, stage, period), now=time.time())
            result = manager.preheat_period(1, page, stage, period, force=True)
            hit = store.published_period(1, period, stage, {}, data_identity=get_gateway().config.identity())
            if result.get('status') not in {'published', 'frozen'} or not hit:
                raise RuntimeError('Annual stage not ready: '+stage)
            item=store.get_analysis(hit['analysis_id'])
            return item
    return Runner()
