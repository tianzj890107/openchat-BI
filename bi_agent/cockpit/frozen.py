"""Customer annual delivery: immutable first paint, explicit atomic replacement.

The preset is a delivery artifact, never a repository fixture or a claim that
customer live data has already been queried. Reads never start work.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
import uuid
from urllib.parse import parse_qs

from fastapi import HTTPException
from starlette.responses import HTMLResponse, JSONResponse, Response

from .diagnostics import diagnostic_scope, record_failure, record_query_failure
from .cards import CONTRACT, card_delivery_state, valid_card
from .delivery import project_card, publication_payload
from .page_cache import compact_analysis
from .risk import summarize_risk_counts
from .targets import REGISTRY_VERSION, slot_registry

STAGES = ('opportunity', 'order', 'shipment', 'quotation', 'bid', 'combined')
# Publication keys behind the three 销售额口径明细 node cards (商机获取 risk
# card, 订单接收, 发货): their sections get model summaries of displayed items.
SECTION_SUMMARY_STAGES = ('opportunity-risk', 'order', 'shipment')
INDEPENDENT_ITEMS = ('opportunity-risk',)
PUBLICATION_KEYS = STAGES + INDEPENDENT_ITEMS


def _item_key(spec, items=None):
    """Return the independently published item for a slot when one exists."""
    if spec.get('slotId') in INDEPENDENT_ITEMS and (items is None or spec['slotId'] in items):
        return spec['slotId']
    return spec['stage']


def _release_item(release, spec):
    items = release.get('items') or {}
    key = _item_key(spec, items)
    item = items.get(key)
    if not item and key != spec['stage']:
        item = items.get(spec['stage'])
    return item, (key if items.get(key) else spec['stage'])


def validate_release(body, partial=False):
    """A delivered seed must cover every stage; ``partial`` admits unanalysed stages.

    Partial releases exist only when the image ships without a seed: stages
    are filled one by one by explicit manual analysis.  A stage that is
    present must still be a complete, same-year card.
    """
    if not isinstance(body, dict) or not str(body.get('period', '')).isdigit() or len(str(body['period'])) != 4:
        raise ValueError('年度发布版必须有明确的四位年度')
    items = body.get('items') or {}
    for stage in STAGES:
        item = items.get(stage)
        if partial and item is None:
            continue
        context = (item or {}).get('context') or {}
        if (not valid_card(item) or item.get('status') not in {'completed', 'limited'}
                or context.get('stage') != stage or context.get('period') != body['period']):
            raise ValueError('年度发布版缺少可交付的同年度环节：' + stage)
    for key in INDEPENDENT_ITEMS:
        item = items.get(key)
        if item is None:
            continue
        context = (item or {}).get('context') or {}
        spec = next((slot for slot in slot_registry() if slot['slotId'] == key), None)
        if (not spec or not valid_card(item) or item.get('status') not in {'completed', 'limited'}
                or context.get('stage') != spec['stage'] or context.get('slotId') != key
                or context.get('period') != body['period']):
            raise ValueError('独立卡片发布内容不合法：' + key)
    for spec in slot_registry():
        item, _ = _release_item(body, spec)
        if partial and item is None:
            continue
        if not card_delivery_state(publication_payload(project_card(item, spec['slotId'])), spec['slotId'])['renderable']:
            raise ValueError('年度发布版未覆盖全部AI插槽')
    return body


UNSEEDED_BASIS = '镜像未内置年度发布版；各环节需点击“分析”生成，成功一个环节发布一个环节。'


class FrozenAnnualStore:
    def __init__(self, path, seed=None):
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
            if seed and Path(seed).is_file():
                self.publish(json.loads(Path(seed).read_text(encoding='utf-8')))
            else:
                # No delivered seed: open with an empty annual release whose
                # cards are produced only by explicit manual analysis.
                from .periods import default_period
                self.publish(dict(period=default_period()[:4], createdAt=time.time(),
                                  basis=UNSEEDED_BASIS, items={}), partial=True)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.execute('PRAGMA busy_timeout=30000')
        try:
            with db:
                yield db
        finally:
            db.close()

    def publish(self, body, partial=False):
        body = deepcopy(validate_release(body, partial=partial))
        raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                         default=str)
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
        if row and row[0] != 'running':
            for work in (body.get('stageProgress') or {}).values():
                if work.get('status') in {'queued','running'}:
                    work.update(status='failed', phase='failed', finishedAt=row[2])
        return dict(body, status=row[0], error=row[1], updatedAt=row[2]) if row else dict(status='idle', error='', updatedAt=0)

    def progress(self, **body):
        with self.db() as db:
            db.execute('INSERT INTO annual_progress VALUES(1,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body',
                       (json.dumps(body, ensure_ascii=False),))
            db.execute('UPDATE annual_job SET updated=? WHERE id=1', (time.time(),))

    def clear_stage(self, stage):
        """Remove one stage's card so a failed round shows nothing for it."""
        if stage not in PUBLICATION_KEYS:
            raise ValueError('Unknown analysis stage')
        with self.lock:
            release = self.read()
            if stage not in (release.get('items') or {}):
                return release['version']
            release.pop('version', None)
            release['items'].pop(stage)
            release['createdAt'] = time.time()
            return self.publish(release, partial=True)

    def publish_stage(self, stage, item):
        # Keep every other stage at its last successful generation.
        if stage not in PUBLICATION_KEYS:
            raise ValueError('Unknown analysis stage')
        with self.lock:
            release = self.read()
            release.pop('version', None)
            release['items'][stage] = deepcopy(item)
            release['createdAt'] = time.time()
            release['basis'] = 'Customer manual annual analysis; stages publish independently. Evidence times and limitations belong to each card.'
            # Other stages keep their last generation; an unseeded release
            # may still lack stages that were never analysed.
            return self.publish(release, partial=True)

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


def stage_failure_message(exc):
    """Explain a failed stage without exposing raw driver or upstream text."""
    reason = getattr(exc, 'public_message', '')
    if not reason:
        # No tailored explanation: show the redacted error itself so the
        # failure can be located without opening the diagnostic store.
        from .diagnostics import redact
        code = str(getattr(exc, 'code', '') or '')
        detail = ' '.join(redact(str(exc)).split())[:300]
        reason = '原因：后台分析未完成\n错误类型：' + type(exc).__name__ + (f'（{code}）' if code else '')
        if detail:
            reason += '\n错误信息：' + detail
    return reason.rstrip('。.；; ') + '\n结果：本轮未发布，卡片已清空，请稍后重试。'


def stage_failure_details(exc, phase=''):
    """Grouped facts for the dialog's expandable section.

    A tailored explanation supplies its own sections; every failure also
    reports where the exception was raised, so it can be located from the
    page alone.  Text is redacted and bounded.
    """
    import traceback
    from .diagnostics import redact
    sections = [dict(title=str(item.get('title') or '')[:40],
                     lines=[str(line)[:1200] for line in (item.get('lines') or [])[:20]])
                for item in (getattr(exc, 'public_details', None) or [])[:8]
                if isinstance(item, dict) and item.get('lines')]
    lines = ['异常类型：' + type(exc).__name__]
    code = str(getattr(exc, 'code', '') or '')
    if code:
        lines.append('错误代码：' + code)
    step = str(getattr(exc, 'phase', '') or phase or '')
    if step:
        lines.append('失败阶段：' + step)
    detail = ' '.join(redact(str(exc)).split())[:600] if str(exc) else ''
    if detail:
        lines.append('异常信息：' + detail)
    frames = traceback.extract_tb(exc.__traceback__)[-3:]
    if frames:
        lines.append('出错位置：' + ' → '.join(
            f'{Path(frame.filename).name}:{frame.lineno} {frame.name}' for frame in frames))
    cause = exc.__cause__ or exc.__context__
    if cause is not None:
        lines.append('上游异常：' + type(cause).__name__ + '：'
                     + ' '.join(redact(str(cause)).split())[:300])
    sections.append(dict(title='程序异常', lines=lines))
    return sections


class FrozenAnnualService:
    def __init__(self, store, recompute=None):
        self.store, self.recompute = store, recompute
        self.queue_lock = threading.RLock()
        self.pending, self.completed, self.failures = [], [], []
        self.active = ''
        self.round_id = ''
        self.phase = 'idle'
        self.detail = {}
        self.stage_progress = {}
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
        if slot_id:
            # A card's "重新分析" analyses that card only.  It never drags in
            # visible cards, the rest of the page or the other stages.
            return [_item_key(registry[slot_id])]
        candidates = [_item_key(registry[v]) for v in visible_slots]
        # A page-wide refresh keeps the shared stage targets.  Independent
        # cards join only when the user targets them or they are visible.
        candidates += [_item_key(s) for s in registry.values() if s['page']==page]
        return list(dict.fromkeys(candidates + list(STAGES)))

    def _progress(self):
        self.store.progress(runId=self.round_id,activeStage=self.active, pendingStages=list(self.pending),
                            completedStages=list(self.completed), failedStages=list(self.failures),
                            phase=self.phase, progress=self.detail, stageProgress=dict(self.stage_progress), heartbeatAt=time.time())

    def report_progress(self, phase, **detail):
        with self.queue_lock:
            now = time.time()
            previous = self.stage_progress.get(self.active, {}) if self.active else {}
            self.phase, self.detail = phase, {**detail, 'lastProgressAt': now}
            if previous.get('phase') != phase:
                self.detail['stepStartedAt'] = now
            if self.active:
                self.stage_progress[self.active] = {**self.stage_progress.get(self.active, {}), **self.detail, 'phase':phase, 'status':'running'}
            self._progress()

    def _job_response(self, queued):
        job = self.store.job()
        return dict(queued=queued, status=job.get('status', 'idle'), manualUpdate=job)

    def _enqueue(self, stage):
        """Join the running round at the back; other cards keep their place."""
        if not stage or self.active == stage or stage in self.pending:
            return
        self.completed[:] = [item for item in self.completed if item != stage]
        self.failures[:] = [item for item in self.failures if item.get('stage') != stage]
        self.pending.append(stage)
        self.stage_progress[stage] = dict(status='queued', phase='queued', queuedAt=time.time())

    def prioritize(self, slot_id=None, page=None, visible_slots=None, requeue=False):
        """Validate the request; only an explicit card refresh changes the queue.

        Scrolling used to reorder and even drop queued stages.  The queue now
        belongs to the cards the user asked for, in the order they asked.
        """
        order = self.priority_order(slot_id, page, visible_slots)
        with self.queue_lock:
            if requeue and slot_id and self.store.job()['status']=='running':
                self._enqueue(order[0])
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
            self.stage_progress = {stage:dict(status='queued',phase='queued',queuedAt=time.time()) for stage in order}
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
                if hasattr(self.recompute, 'run_stage') or hasattr(self.recompute, 'run_slot'):
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
                            started_at = time.time()
                            self.phase, self.detail = 'fetching', {'startedAt':started_at, 'stepStartedAt':started_at}
                            self.stage_progress[stage] = {**self.stage_progress.get(stage, {}), **self.detail, 'phase':'fetching', 'status':'running'}
                            self._progress()
                        started=time.monotonic()
                        phase='stage_execution'
                        try:
                            with diagnostic_scope(runId=self.round_id,stage=stage):
                                if hasattr(self.recompute, 'run_slot'):
                                    item = self.recompute.run_slot(self.store.read()['period'], stage)
                                else:
                                    item = self.recompute.run_stage(self.store.read()['period'], stage)
                            if (item.get('execution') or {}).get('stopReason')=='stage_no_evidence':
                                missing_evidence = RuntimeError('No matching evidence for this stage')
                                missing_evidence.public_message = '本环节没有取到匹配的看板证据'
                                raise missing_evidence
                            phase='publication'
                            self.report_progress('publishing')
                            self.store.publish_stage(stage, item)
                            with self.queue_lock:
                                self.completed.append(stage)
                                self.stage_progress[stage].update(status='completed', phase='published', finishedAt=time.time())
                        except Exception as exc:
                            from .store import Store
                            diagnostic=record_failure(Store(self.store.path.parent/'history.sqlite3'),exc,
                                phase=phase,stage=stage,run_id=self.round_id,duration=time.monotonic()-started)
                            # A failed round never keeps showing the last card.
                            try:
                                self.store.clear_stage(stage)
                            except Exception as clear_exc:  # noqa: BLE001 - still report the stage failure
                                record_failure(Store(self.store.path.parent/'history.sqlite3'),clear_exc,
                                    phase='clear_stage',stage=stage,run_id=self.round_id)
                            message = stage_failure_message(exc)
                            try:
                                details = stage_failure_details(exc, phase)
                            except Exception:  # noqa: BLE001 - details never mask the failure
                                details = []
                            with self.queue_lock:
                                self.failures.append(dict(stage=stage,code=type(exc).__name__,diagnosticId=diagnostic['diagnosticId'],message=message))
                                self.stage_progress[stage].update(
                                    status='failed', phase='failed', finishedAt=time.time(),
                                    diagnosticId=diagnostic['diagnosticId'], error=message,
                                    errorDetails=details)
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
                    payload=slot['payload']
                    if payload is None:
                        # Not analysed yet; the manifest still lists it as missing.
                        continue
                    stage=slot.get('publicationKey') or slot['stage']
                    bundle=grouped.setdefault(stage,{'slots':{},'evidence':None})
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
        keys = {_item_key(s, release.get('items') or {}) for s in slot_registry()
                if page is None or s['page'] == page}
        items = {}
        for key, raw in release['items'].items():
            if key not in keys:
                continue
            item = compact_analysis(raw)
            item['context']['id'] = identity
            item['context']['publicationBasis'] = release.get('basis', '')
            items[key] = item
        return items

    def published_analysis(self, aid):
        """Look up an analysis by id across the current frozen release.

        Frozen cards live in the annual release rather than the ordinary
        append-only analysis table.  Task drafts and task dispatch still need
        the exact published item, including its evidence and recommendations.
        """
        if not isinstance(aid, str) or not aid:
            return None
        release = self.store.read()
        for item in (release.get('items') or {}).values():
            if isinstance(item, dict) and item.get('id') == aid:
                return deepcopy(item)
        return None

    def envelope(self, identity, ui_scope='default'):
        release = self.store.read()
        items = self.items(identity, release=release)
        slots = {}
        for spec in slot_registry():
            item, publication_key = _release_item(release, spec)
            if item is None:
                # Unseeded image: this stage has not been analysed yet.
                slots[spec['slotId']] = dict(**spec, publicationKey=publication_key,
                    status='missing', contentStatus='missing', contentComplete=False,
                    contentGaps=[], evidenceCount=0, riskFindingCount=0,
                    scopeMatch=True, periodMatch=True, displayScope='fixed-annual',
                    refreshStatus='missing', lastRefreshError='',
                    update=dict(status='missing', active=False, nextCheckAt=0), payload=None)
                continue
            item = compact_analysis(item)
            item['context']['id'] = identity
            item['context']['publicationBasis'] = release.get('basis', '')
            payload = publication_payload(project_card(item, spec['slotId']))
            delivery = card_delivery_state(payload, spec['slotId'])
            stamp = float(item.get('updatedAt') or release['createdAt'])
            slots[spec['slotId']] = dict(**spec, publicationKey=publication_key,
                status='ready', contentStatus=delivery['status'],
                contentComplete=delivery['complete'], contentGaps=delivery['gaps'],
                evidenceCount=delivery['evidenceCount'], riskFindingCount=delivery['riskFindingCount'],
                generatedAt=stamp, dataAsOf=stamp, lastSuccessfulPublication=payload,
                lastSuccessfulAt=stamp, scopeMatch=True, periodMatch=True, displayScope='fixed-annual',
                refreshStatus='published', lastRefreshError='',
                update=dict(status='published', active=False, nextCheckAt=0), payload=payload)
        complete = sum(s['contentComplete'] for s in slots.values())
        ready = sum(s['status'] == 'ready' for s in slots.values())
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
            expectedCount=len(slots), targetCount=len(slots), readyCount=ready,
            renderableCount=ready, publishedCount=ready, missingCount=len(slots)-ready,
            completeCount=complete, limitedCount=ready-complete, incompleteCount=len(slots)-complete,
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


STAGE_LABELS = {'opportunity': '商机获取', 'opportunity-risk': '商机获取', 'quotation': '报价', 'bid': '投标',
                'order': '订单接收', 'shipment': '发货',
                'combined': '销售额与出货量跨环节共同问题分析'}
_RECORD_LABELS = {'id': 'ID', 'customer': '客户', 'department': '产品部/部门',
                  'product': '产品', 'status': '状态', 'cause': '原因',
                  'amount': '金额', 'quantity': '数量', 'value': '值',
                  'unit': '单位', 'overdueDays': '逾期天数',
                  'evidence': '证据', 'name': '名称'}
_RECORD_ORDER = ('id', 'customer', 'department', 'product', 'status', 'cause',
                 'amount', 'quantity', 'value', 'unit', 'overdueDays',
                 'evidence', 'name')
EVIDENCE_ROW_CHUNK = 400
EVIDENCE_MAX_BLOCKS = 20
_EVIDENCE_CACHE = {}
_EVIDENCE_CACHE_LOCK = threading.Lock()
_CANVAS_MODULE = None


def _canvas_module():
    """Load the MCP canvas renderer without writing an artifact or calling a tool."""
    global _CANVAS_MODULE
    if _CANVAS_MODULE is None:
        base = os.environ.get('ONTOLOGY_MCP_PACKAGE') or str(Path(__file__).parents[2] / 'ontology-analytics-mcp')
        path = Path(base) / 'canvas_tool.py'
        spec = importlib.util.spec_from_file_location('cockpit_evidence_canvas', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _CANVAS_MODULE = module
    return _CANVAS_MODULE


def _record_columns(records):
    complex_keys = {key for record in records for key, value in record.items()
                    if isinstance(value, (dict, list))}
    keys = [key for key in _RECORD_ORDER
            if any(key in record for record in records) and key not in complex_keys]
    keys += [key for record in records for key in record
             if key not in keys and key not in complex_keys]
    return list(dict.fromkeys(keys))[:14]


def _fact_rows(facts):
    rows = []
    for fact in facts:
        value = fact.get('value')
        unit = str(fact.get('unit') or '').strip()
        if value is None or value == '':
            text = ''
        else:
            text = f'{value} {unit}'.strip()
        rows.append([fact.get('label') or fact.get('id') or '', text,
                     fact.get('definition') or ''])
    return rows


def _evidence_html(stage, item, release):
    evidence = item.get('evidence') or {}
    facts = [value for value in evidence.get('facts') or [] if isinstance(value, dict)]
    records = [value for value in evidence.get('records') or [] if isinstance(value, dict)]
    counts = evidence.get('counts') or {}
    try:
        fact_count = int(counts.get('facts', len(facts)))
        record_count = int(counts.get('records', len(records)))
        distinct_count = int(counts.get('distinct', 0)) or len({
            str(entry.get('id')) for key in ('facts', 'records', 'evidence')
            for entry in evidence.get(key) or [] if isinstance(entry, dict) and entry.get('id')})
        referenced_count = int(counts.get('referenced', len(evidence.get('evidence') or [])))
    except (TypeError, ValueError):
        fact_count, record_count = len(facts), len(records)
        distinct_count = referenced_count = 0
    result = item.get('result') or {}
    stamp = float(item.get('updatedAt') or release.get('createdAt') or 0)
    when = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stamp)) if stamp else ''
    seconds = (item.get('execution') or {}).get('durationSeconds')
    duration = ''
    if isinstance(seconds, (int, float)) and seconds > 0:
        total = round(seconds)
        duration = f'{total} 秒' if total < 60 else f'{total // 60} 分 {total % 60} 秒'
    lines = [f"- 环节：{STAGE_LABELS.get(stage, stage)}",
             f"- 期间：{release.get('period', '')}",
             f"- 分析时间：{when or '未知'}" + (f"（耗时 {duration}）" if duration else ''),
             f"- 证据规模：{fact_count} 项数值事实 · {record_count} 条明细记录 · "
             f"{referenced_count} 条引用证据 · 去重 {distinct_count} 条",
             f"- 分析 ID：{item.get('id', '')}"]
    summary = str(result.get('summary') or '').strip()
    if summary:
        lines.extend(['', summary])
    limitations = [str(value).strip() for value in evidence.get('limitations') or []
                   if str(value).strip()]
    if limitations:
        lines.extend(['', '**口径与限制**'])
        lines.extend(f"- {value}" for value in limitations[:20])
    blocks = [{'kind': 'text', 'heading': '本次分析', 'markdown': '\n'.join(lines)}]
    from .evidence_charts import chart_blocks
    charts = chart_blocks(item)
    for chart in charts:
        blocks.append(chart)
        blocks.append({'kind':'text','markdown':'口径与溯源：'+chart['params']['source_note']})
    if not charts:
        blocks.append({'kind':'text','markdown':'- 当前冻结证据不足以形成同一查询、同一指标的多点图表，保留以下事实与记录明细。'})
    if facts:
        blocks.append({'kind': 'table', 'heading': f'事实（{len(facts)} 项）',
                       'params': {'columns': [{'key': 'label', 'label': '事实'},
                                              {'key': 'value', 'label': '数值'},
                                              {'key': 'definition', 'label': '口径'}],
                                  'rows': _fact_rows(facts)}})
    keys = _record_columns(records)
    reserved = len(blocks)
    max_chunks = max(0, EVIDENCE_MAX_BLOCKS - reserved)
    if records and keys and len(records) > max_chunks * EVIDENCE_ROW_CHUNK:
        max_chunks = max(0, max_chunks - 1)
        truncated = True
    else:
        truncated = False
    shown = min(len(records), max_chunks * EVIDENCE_ROW_CHUNK)
    columns = [{'key': key, 'label': _RECORD_LABELS.get(key, key)} for key in keys]
    for index in range(0, shown, EVIDENCE_ROW_CHUNK):
        chunk = records[index:index + EVIDENCE_ROW_CHUNK]
        blocks.append({'kind': 'table',
                       'heading': f'记录 {index + 1}–{index + len(chunk)} / {len(records)}',
                       'params': {'columns': columns,
                                  'rows': [[record.get(key) for key in keys] for record in chunk]}})
    if not records:
        blocks.append({'kind': 'text',
                       'markdown': '- 本次分析没有可逐条展示的记录，以上事实即为全部证据。'})
    if truncated:
        blocks.append({'kind': 'text',
                       'markdown': f'- 记录较多，本页展示前 {shown} 条；'
                                   '完整原始数据可用 `?format=json` 查看。'})
    params = {
        'title': f"完整证据 · {STAGE_LABELS.get(stage, stage)}",
        'subtitle': f"{release.get('period', '')} 年度分析 · {record_count} 条明细记录 · 去重 {distinct_count} 条证据",
        'source_note': f"分析 {item.get('id', '')} · 期间 {release.get('period', '')}",
        'blocks': blocks,
    }
    canvas = _canvas_module()
    try:
        return canvas.render_canvas_html(params, allow_external_assets=False)
    except OSError:
        # Evidence remains readable if a deployment omits the local chart asset.
        params['blocks'] = [b for b in blocks if b['kind'] != 'chart']
        params['blocks'].append({'kind':'text','markdown':'- 本地图表资源不可用，以下保留原始证据表格；未请求外部资源。'})
        return canvas.render_canvas_html(params, allow_external_assets=False)



def evidence_page_html(stage, item, release):
    """Render one evidence report per analysis; repeat opens reuse the page."""
    key = ('evidence-charts-v1', stage, str(item.get('id') or ''), item.get('updatedAt'))
    with _EVIDENCE_CACHE_LOCK:
        cached = _EVIDENCE_CACHE.get(key)
    if cached is not None:
        return cached
    page = _evidence_html(stage, item, release)
    with _EVIDENCE_CACHE_LOCK:
        if len(_EVIDENCE_CACHE) >= 32:
            _EVIDENCE_CACHE.clear()
        _EVIDENCE_CACHE[key] = page
    return page


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
                if stage not in PUBLICATION_KEYS or len(parts)>2 or (len(parts)==2 and parts[1]!='evidence'):raise HTTPException(422,'无效分析环节')
                if len(parts)==2:
                    release=await asyncio.to_thread(self.service.store.read)
                    item=release['items'].get(stage)
                    if not item:
                        item=release['items'].get('opportunity')
                    if not item:
                        raise HTTPException(404,'该环节尚未发布完整证据')
                    expected=query.get('analysisId',[''])[0]
                    if expected and expected!=item['id']:raise HTTPException(409,'该环节分析已更新，请重新打开证据')
                    if query.get('format',['json'])[0]=='html':
                        try:
                            page=await asyncio.to_thread(lambda:evidence_page_html(stage,item,release))
                        except Exception as exc:  # noqa: BLE001
                            value=dict(analysisId=item['id'],stage=stage,period=release['period'],
                                       dataAsOf=item.get('updatedAt'),evidence=item.get('evidence') or {},
                                       htmlError=str(exc))
                            return await JSONResponse(value,headers={'Cache-Control':'private, no-store'})(scope,receive,send)
                        return await HTMLResponse(page,headers={'Cache-Control':'private, no-store'})(scope,receive,send)
                    response=await asyncio.to_thread(lambda:JSONResponse(dict(analysisId=item['id'],stage=stage,period=release['period'],dataAsOf=item.get('updatedAt'),evidence=item.get('evidence') or {}),headers={'Cache-Control':'private, no-store'}))
                    return await response(scope,receive,send)
                manifest,groups=await asyncio.to_thread(self.service.compact_publications,identity)
                if stage not in manifest['stageVersions']:
                    raise HTTPException(404,'该环节尚未分析')
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
    manager.implemented_only = True
    class Runner:
        def __init__(self):
            self._progress_callback = None

        def begin_round(self, period):
            manager.round_queries={}

        def set_progress(self, callback):
            self._progress_callback = callback
            manager.progress_callback=callback

        def run_slot(self, period, stage):
            item = self._analyse_slot(period, stage)
            if stage in SECTION_SUMMARY_STAGES:
                # The 销售额口径明细 cards open each section with a model
                # summary of the items that section displays.
                from .section_summary import with_section_summaries
                item = with_section_summaries(item, stage_name=STAGE_LABELS.get(stage, stage),
                                              progress=self._progress_callback)
            return item

        def _analyse_slot(self, period, stage):
            if stage == 'opportunity-risk':
                from .opportunity_v2 import build_card, default_ap_supplement, default_text_interpreter
                from .store import Store
                enabled = os.getenv('COCKPIT_OPPORTUNITY_V2_MODEL_ENABLED', '1').strip().lower() not in {'0', 'false', 'no', 'off'}
                supplement_enabled = os.getenv('COCKPIT_OPPORTUNITY_V2_AP_SUPPLEMENT', '1').strip().lower() not in {'0', 'false', 'no', 'off'}
                diagnostic_store = Store(store.path.parent / 'history.sqlite3')

                def report_diagnostic(entry):
                    return record_query_failure(
                        diagnostic_store, identity=1, stage='opportunity-risk', **entry)

                return build_card(period, text_interpreter=default_text_interpreter if enabled else None,
                                  supplement=default_ap_supplement if supplement_enabled else None,
                                  progress=self._progress_callback,
                                  diagnostic_reporter=report_diagnostic)
            return self.run_stage(period, stage)

        def run_stage(self, period, stage):
            page = target_page(stage) or 'analysis'
            store.request_refresh(period_target_scope(1, page, stage, period), now=time.time())
            result = manager.preheat_period(1, page, stage, period, force=True)
            hit = store.published_period(1, period, stage, {}, data_identity=get_gateway().config.identity())
            if result.get('status') not in {'published', 'frozen'} or not hit:
                from .diagnostics import redact
                status = str(result.get('status') or 'unknown')
                detail = ' '.join(redact(str(result.get('error') or '')).split())[:300]
                not_ready = RuntimeError(f'Annual stage not ready: {stage}; status={status}; error={detail}')
                lines = [f'原因：{STAGE_LABELS.get(stage, stage)}环节分析没有产出可发布的卡片',
                         f'说明：取数与分析任务结束状态为 {status}'
                         + ('，没有找到本年度已发布的结果。' if not hit else '。')]
                if detail:
                    lines.append('错误信息：' + detail)
                not_ready.public_message = '\n'.join(lines)
                raise not_ready
            item=store.get_analysis(hit['analysis_id'])
            return item
    return Runner()
