"""Server-owned refresh of last-successful page publications and AI cards.

The browser is not the scheduler.  A page publication is an immutable evidence
snapshot; a stage card is its own published result.  This module re-reads the
original AP queries, resolves failed ones through the same registered
PostgreSQL fallback as the HTTP path, compares the evidence fingerprint, and
only asks the main analysis service for cards when the data, source identity,
or delivered analysis contract really changed.
"""
from __future__ import annotations

import json
import os
import threading
import time

from .dashboard_source import RELEASE, page_analysis_context, supplement_failed_queries
from .page_cache import PageRequest, build_page, page_fingerprint, page_scope, transport_identity
from .publications import config_version, digest, view_scope

DEFAULT_IDENTITIES = (1, 2)
DEFAULT_PAGES = ('overview', 'operations', 'analysis')


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _snapshot_scope(config, body):
    return page_scope(config, int(body['id']), body['page'], body.get('uiScope') or 'default', 'ap')


def view_target_scope(view_key, stage):
    """Synthetic maintenance key for one published default-scope AI card."""
    return digest({'view': view_key, 'stage': stage})


class RefreshManager:
    """One-scope-at-a-time, append-preserving publication refresher.

    ``query(kind, payload)`` must be the same read-only AP transport used by the
    page.  ``start_analysis(body, resolved)`` is the router-owned analysis entry
    point; passing ``resolved`` avoids querying AP a second time.
    """

    def __init__(self, store, config, query, start_analysis, *, interval=900, poll=2.0, timeout=1200):
        self.store = store
        self.config = config
        self.query = query
        self.start_analysis = start_analysis
        self.interval = max(60, int(interval))
        self.poll = max(0.1, float(poll))
        self.timeout = max(60, int(timeout))

    def _set(self, scope, status, **changes):
        next_check = changes.pop('next_check', None)
        if next_check is None:
            next_check = time.time() + self.interval if status == 'published' else time.time() + 60
        return self.store.set_refresh_state(scope, status, next_check=next_check, **changes)

    def previous_publication(self, scope):
        """Last publication for this page/range when its scope key rotated.

        A metadata or component change derives a new scope key, so the queued
        scope has no view yet.  The previous body is still the right source of
        the original queries; it is only reused as input, never published as
        already-verified evidence.
        """
        for _scope, body, _source in self.store.page_publications(limit=200):
            if _snapshot_scope(self.config, body) == scope:
                return body
        return None

    def _receipt(self, identity, kind, payload, data):
        # Receipts must stay valid through the whole refresh, including a queue
        # wait and every stage analysis; otherwise the final publish would read
        # expired evidence.
        ttl = max(int(self.config.receipt_ttl), self.timeout + 600)
        return self.store.save_ap_result(
            identity, kind, payload, data, ttl, self.config.identity(),
            transport_identity(self.config),
            self.config.batch_mode if kind == 'batch' else 'fixed-path')

    def _query_entries(self, body):
        """Re-read every page query; one failed business query becomes a fallback candidate."""
        records, failures, retry = [], [], []
        for entry in body.get('entries') or []:
            kind, payload = entry.get('kind'), entry.get('payload')
            if kind == 'pg':
                # A previous publication answered this query from PostgreSQL.
                # Try AP again first so a recovered source replaces the fallback.
                retry.append(payload)
                continue
            if kind not in {'analysis', 'batch', 'helmet'} or payload is None:
                raise RuntimeError('历史页面包含无效查询，保留上次完整版本')
            try:
                data = self.query(kind, payload)
            except Exception as exc:
                if kind == 'helmet':
                    raise RuntimeError('头盔图查询失败，保留上次完整版本') from exc
                failures.append(_canonical(payload))
                continue
            records.append(self._receipt(int(body['id']), kind, payload, data))
        for payload in retry:
            kind = 'batch' if isinstance(payload, list) else 'analysis'
            try:
                data = self.query(kind, payload)
            except Exception:
                failures.append(_canonical(payload))
                continue
            records.append(self._receipt(int(body['id']), kind, payload, data))
        return records, failures

    def _query_requests(self, identity, requests):
        records, failures = [], []
        for payload in requests:
            kind = 'batch' if isinstance(payload, list) else 'analysis'
            try:
                data = self.query(kind, payload)
            except Exception:
                failures.append(_canonical(payload))
                continue
            records.append(self._receipt(identity, kind, payload, data))
        return records, failures

    def _supplement(self, identity, failures, stages):
        """Resolve failed queries once so every stage shares one evidence set."""
        if not failures:
            return {}, []
        try:
            return supplement_failed_queries(
                {'id': int(identity), 'stage': None, 'unavailableQueries': list(failures)},
                self.store, stages, limit=8)
        except Exception:
            # A broken fallback registry must not silently pretend the failed
            # query was answered; surface it as a blocked supplement instead.
            return {}, [dict(query=query, code='FALLBACK_UNAVAILABLE') for query in failures]

    def _await(self, item):
        deadline = time.time() + self.timeout
        while item and item.get('status') in {'queued', 'running'}:
            if time.time() > deadline:
                raise RuntimeError('后台分析更新超时，保留上次完整版本')
            time.sleep(self.poll)
            item = self.store.get_analysis(item['id'])
        if not item or item.get('status') not in {'completed', 'limited'}:
            raise RuntimeError((item or {}).get('error') or '后台分析未完整交付，保留上次完整版本')
        if (item.get('result') or {}).get('cardContract') != 'cockpit-cards-v1':
            raise RuntimeError('后台分析缺少卡片契约，保留上次完整版本')
        return item

    def _failure(self, scope, exc):
        now = time.time()
        state = self.store.refresh_state(scope) or {}
        attempt = int(state.get('attempt') or 1)
        self._set(scope, 'retry_wait', next_check=now + min(900, 60 * max(1, attempt)),
                  error=str(exc)[:500])
        return dict(scope=scope, status='retry_wait', error=str(exc)[:500])

    def refresh(self, body):
        """Refresh one published page.  Returns a compact status dict."""
        scope = _snapshot_scope(self.config, body)
        if body.get('dataSource') not in {'ap', 'ap+pg', 'pg'}:
            self._set(scope, 'published', next_check=time.time() + self.interval)
            return dict(scope=scope, status='unchanged', reason='not-ap')
        if not self.store.claim_refresh(scope, lease=max(180, self.timeout + 60)):
            return dict(scope=scope, status='already-running')
        try:
            records, failures = self._query_entries(body)
            old_items = body.get('items') or {}
            extra, notes = self._supplement(body['id'], failures, list(old_items))
            pg_ids = sorted({value['receiptId'] for value in extra.values()})
            pg_records = [value for value in
                          (self.store.get_ap_result(pid, int(body['id'])) for pid in pg_ids) if value]
            all_records = records + pg_records
            if not any(record['kind'] != 'helmet' for record in all_records):
                raise RuntimeError('历史页面没有可复核业务查询，保留上次完整版本')
            has_ap_business = any(record['kind'] in {'analysis', 'batch'} for record in records)
            identity = self.config.identity() if has_ap_business else 'postgres'
            fingerprint = page_fingerprint(all_records)
            changed = (fingerprint != body.get('dataFingerprint')
                       or body.get('dataIdentity') != identity
                       or body.get('configVersion') != config_version())
            analysis_ids = {stage: item.get('id') for stage, item in old_items.items()
                            if item and item.get('id')}
            data_source = body.get('dataSource') or 'ap'
            if changed:
                queries = sorted({_canonical(record['request']) for record in records
                                  if record['kind'] in {'analysis', 'batch'}})
                receipt_ids = [record['id'] for record in records
                               if record['kind'] in {'analysis', 'batch'}]
                for stage, old in old_items.items():
                    context = (old or {}).get('context') or {}
                    request = dict(
                        id=int(body['id']), engine='main', source='service', page=body['page'],
                        stage=stage, defaultView=(body.get('uiScope') or 'default') == 'default',
                        period=context.get('period') or '2025-10',
                        department=context.get('department') or '全部产品部',
                        filters=context.get('filters') or {}, repositoryId='',
                        clarifications=context.get('clarifications') or {},
                        baselineAnalysisId='', chartSnapshotId=RELEASE,
                        chartQueries=queries, apReceiptIds=receipt_ids,
                        unavailableQueries=list(failures))
                    resolved = page_analysis_context(
                        {**request, 'pgReceiptIds': pg_ids}, self.store,
                        data_mode='ap', resolve_fallback=False, fallback_notes=notes)
                    data_source = resolved['dataSource']
                    job = self.start_analysis(request, resolved)
                    analysis_ids[stage] = self._await(job)['id']
            page = build_page(PageRequest(
                id=int(body['id']), page=body['page'], uiScope=body.get('uiScope') or 'default',
                apReceiptIds=[record['id'] for record in records], pgReceiptIds=pg_ids,
                analysisIds=analysis_ids), self.store, self.config,
                data_source=data_source, data_identity=identity)
            current_page = self.store.published_page(scope)
            if not current_page or current_page.get('version') != page.get('version'):
                if not self.store.publish_page(scope, page):
                    raise RuntimeError('服务端复核结果早于当前发布版本，未覆盖')
            now = time.time()
            self._set(scope, 'published', next_check=now + self.interval,
                      error='', last_success=now)
            return dict(scope=scope, status='published', changed=changed,
                        fingerprint=fingerprint, version=page.get('version'))
        except Exception as exc:
            return self._failure(scope, exc)

    def refresh_view(self, view_key, stage, analysis):
        """Refresh one published default AI card when its page has no snapshot."""
        context = analysis.get('context') or {}
        scope = view_target_scope(view_key, stage)
        if context.get('engine') != 'main' or context.get('source') != 'service':
            self._set(scope, 'published', next_check=time.time() + self.interval)
            return dict(scope=scope, status='unchanged', reason='not-main')
        if not self.store.claim_refresh(scope, lease=max(180, self.timeout + 60)):
            return dict(scope=scope, status='already-running')
        try:
            # Successful and previously unavailable queries are both re-read;
            # a recovered AP source replaces the registered PostgreSQL answer.
            requests, seen = [], set()
            for value in list(context.get('chartQueries') or []) + list(context.get('unavailableQueries') or []):
                request = json.loads(value)
                key = _canonical(request)
                if key in seen:
                    continue
                seen.add(key)
                requests.append(request)
            if not requests:
                raise RuntimeError('历史分析没有可复核查询，保留上次卡片')
            identity = int(context.get('id') or 0)
            records, failures = self._query_requests(identity, requests)
            extra, notes = self._supplement(identity, failures, [stage])
            pg_ids = sorted({value['receiptId'] for value in extra.values()})
            if not records and not pg_ids:
                raise RuntimeError('本次取数和已登记补查均失败，保留上次卡片')
            request = dict(
                id=identity, engine='main', source='service',
                page=context.get('page') or 'analysis', stage=stage, defaultView=True,
                period=context.get('period') or '2025-10',
                department=context.get('department') or '全部产品部',
                filters=context.get('filters') or {}, repositoryId='',
                clarifications=context.get('clarifications') or {},
                baselineAnalysisId='', chartSnapshotId=RELEASE,
                chartQueries=sorted({_canonical(record['request']) for record in records}),
                apReceiptIds=[record['id'] for record in records],
                unavailableQueries=list(failures))
            resolved = page_analysis_context(
                {**request, 'pgReceiptIds': pg_ids}, self.store,
                data_mode='ap', resolve_fallback=False, fallback_notes=notes)
            current_scope = view_scope({**request, **resolved, 'sourceMode': 'service',
                                        'stageName': stage})
            changed = (resolved['dataFingerprint'] != context.get('dataFingerprint')
                       or resolved.get('fallbackVersion', '') != context.get('fallbackVersion', '')
                       or current_scope != view_key)
            if changed:
                self._await(self.start_analysis(request, resolved))
            now = time.time()
            self._set(scope, 'published', next_check=now + self.interval,
                      error='', last_success=now)
            return dict(scope=scope, status='published', changed=changed)
        except Exception as exc:
            return self._failure(scope, exc)


def publication_status(store, scope, body=None):
    state = store.refresh_state(scope) or {}
    body = body or {}
    items = body.get('items') or {}
    analyzed = max((float((item or {}).get('updatedAt') or 0) for item in items.values()), default=0)
    return dict(
        scope=scope,
        publicationVersion=body.get('version', ''),
        dataAsOf=body.get('dataAsOf', 0),
        analyzedAt=analyzed,
        publishedAt=body.get('publishedAt', 0),
        update=dict(
            status=state.get('status', 'idle'),
            lastSuccessAt=state.get('last_success') or body.get('publishedAt', 0),
            nextCheckAt=state.get('next_check', 0),
            lastCheckedAt=state.get('updated', 0),
            error=state.get('last_error', ''),
            attempt=state.get('attempt', 0),
        ),
    )


class RefreshScheduler(threading.Thread):
    """Small POC scheduler.  A database lease prevents duplicate scope workers."""

    def __init__(self, manager, store, *, scan_seconds=20, scope_limit=3):
        super().__init__(name='cockpit-publication-refresh', daemon=True)
        self.manager = manager
        self.store = store
        self.scan_seconds = max(2, int(scan_seconds))
        self.scope_limit = max(1, int(scope_limit))
        self.stop_event = threading.Event()

    def _page_bodies(self):
        return {scope: body for scope, body, _source in self.store.page_publications(limit=2000)}

    def _view_targets(self):
        targets = {}
        for view_key, stage, body in self.store.default_views(limit=2000):
            targets.setdefault(view_target_scope(view_key, stage), (view_key, stage, body))
        return targets

    def _seed(self, current, view_targets):
        """Register maintenance scopes independently of an existing page body.

        A deploy must not re-query and re-analyse every default page at once,
        so the first automatic check waits one interval.  A page that has never
        formed a complete snapshot is still registered; its published stage
        cards are maintained separately.
        """
        due = current + self.manager.interval
        for identity in DEFAULT_IDENTITIES:
            for page in DEFAULT_PAGES:
                self.store.ensure_refresh_state(
                    page_scope(self.manager.config, identity, page, 'default', 'ap'), next_check=due)
        for target in view_targets:
            self.store.ensure_refresh_state(target, next_check=due)

    def run_once(self, now=None):
        current = time.time() if now is None else float(now)
        bodies = self._page_bodies()
        views = self._view_targets()
        self._seed(current, views)
        # A whole-page refresh already re-analyses every stage; maintaining its
        # stage cards separately would double the model calls.
        pages_with_body = {(int(body['id']), body['page']) for body in bodies.values()
                           if body.get('uiScope') == 'default'}
        claimed = 0
        # Scan a few more rows than the execution limit so scopes that are only
        # waiting for their first page plan cannot starve ready work.
        for scope in self.store.due_refresh_scopes(current, limit=max(self.scope_limit * 8, 24)):
            if claimed >= self.scope_limit:
                break
            body = (bodies.get(scope) or self.store.refresh_plan(scope)
                    or self.manager.previous_publication(scope))
            if body:
                result = self.manager.refresh(body)
            elif scope in views:
                view_key, stage, analysis = views[scope]
                context = analysis.get('context') or {}
                if (int(context.get('id') or 0), context.get('page')) in pages_with_body:
                    self.store.set_refresh_state(
                        scope, 'published', next_check=current + self.manager.interval)
                    continue
                result = self.manager.refresh_view(view_key, stage, analysis)
            else:
                # No query plan yet: stay registered for the first complete
                # page instead of pretending the scope is idle or busy.
                self.store.set_refresh_state(
                    scope, 'awaiting-plan', next_check=current + self.manager.interval)
                continue
            if result.get('status') != 'already-running':
                claimed += 1
        return claimed

    def run(self):
        try:
            self.run_once()
        except Exception:
            pass
        while not self.stop_event.is_set():
            try:
                self.run_once()
            except Exception:
                # The dashboard must keep serving the last complete publication
                # even if the scheduler itself encounters an unexpected error.
                pass
            self.stop_event.wait(self.scan_seconds)

    def stop(self):
        self.stop_event.set()


def scheduler_enabled():
    value = os.getenv('COCKPIT_REFRESH_ENABLED')
    if value is None:
        return not bool(os.getenv('PYTEST_CURRENT_TEST'))
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}
