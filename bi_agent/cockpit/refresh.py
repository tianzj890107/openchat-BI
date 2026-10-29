"""Server-owned refresh of last-successful page publications.

The browser is not the scheduler.  A page publication is an immutable evidence
snapshot; this module re-reads its original AP queries, compares the evidence
fingerprint, and only asks the main analysis service for cards when the data,
source identity, or delivered analysis contract really changed.
"""
from __future__ import annotations

import json
import os
import threading
import time

from .page_cache import PageRequest, build_page, page_fingerprint, page_scope, transport_identity
from .publications import config_version, digest


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _business_queries(records):
    return sorted({_canonical(r['request']) for r in records if r.get('kind') != 'helmet'})


def _snapshot_scope(config, body):
    return page_scope(config, int(body['id']), body['page'], body.get('uiScope') or 'default', 'ap')


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

    def _query_entries(self, body):
        records = []
        connection = self.config.identity()
        auth = transport_identity(self.config)
        # Receipts must stay valid through the whole refresh, including a
        # queue wait and every stage analysis; otherwise the final publish
        # would read expired evidence.
        ttl = max(int(self.config.receipt_ttl), self.timeout + 600)
        for entry in body.get('entries') or []:
            kind, payload = entry.get('kind'), entry.get('payload')
            if kind not in {'analysis', 'batch', 'helmet'} or payload is None:
                raise RuntimeError('历史页面包含无效查询，保留上次完整版本')
            data = self.query(kind, payload)
            records.append(self.store.save_ap_result(
                int(body['id']), kind, payload, data, ttl,
                connection, auth, self.config.batch_mode if kind == 'batch' else 'fixed-path'))
        if not records:
            raise RuntimeError('历史页面没有可复核查询，保留上次完整版本')
        return records

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

    def refresh(self, body):
        """Refresh one published page.  Returns a compact status dict."""
        scope = _snapshot_scope(self.config, body)
        if body.get('dataSource') != 'ap':
            self._set(scope, 'published', next_check=time.time() + self.interval)
            return dict(scope=scope, status='unchanged', reason='not-ap')
        if not self.store.claim_refresh(scope, lease=max(180, self.timeout + 60)):
            return dict(scope=scope, status='already-running')
        try:
            records = self._query_entries(body)
            fingerprint = page_fingerprint(records)
            source_changed = body.get('dataIdentity') != self.config.identity()
            contract_changed = body.get('configVersion') != config_version()
            changed = fingerprint != body.get('dataFingerprint') or source_changed or contract_changed
            analysis_ids = {stage: item.get('id') for stage, item in (body.get('items') or {}).items()
                            if item and item.get('id')}
            if changed:
                queries = _business_queries(records)
                receipt_ids = [r['id'] for r in records]
                first = next(iter((body.get('items') or {}).values()), {})
                context = first.get('context') or {}
                resolved = dict(
                    snapshotId='ap-' + digest({'queries': queries, 'fingerprint': fingerprint}),
                    repositoryId=body.get('repositoryId', context.get('repositoryId', '')),
                    dataSource='ap', dataIdentity=self.config.identity(),
                    dataFingerprint=fingerprint,
                    dataBasis='服务端定时复核的AP只读结果；未混用其他来源')
                for stage in (body.get('items') or {}):
                    old = (body['items'][stage] or {}).get('context') or {}
                    request = dict(
                        id=int(body['id']), engine='main', source='service', page=body['page'],
                        defaultView=(body.get('uiScope') or 'default') == 'default', stage=stage,
                        period=old.get('period') or context.get('period') or '2025-10',
                        department=old.get('department') or context.get('department') or '全部产品部',
                        filters=old.get('filters') or {}, repositoryId=old.get('repositoryId') or '',
                        clarifications=old.get('clarifications') or {},
                        baselineAnalysisId='', chartSnapshotId=old.get('chartSnapshotId') or '',
                        chartQueries=queries, apReceiptIds=receipt_ids, unavailableQueries=[])
                    job = self.start_analysis(request, resolved)
                    analysis_ids[stage] = self._await(job)['id']
            page = build_page(PageRequest(id=int(body['id']), page=body['page'],
                                          uiScope=body.get('uiScope') or 'default',
                                          apReceiptIds=[r['id'] for r in records],
                                          analysisIds=analysis_ids), self.store, self.config, data_source='ap')
            if not self.store.publish_page(scope, page):
                raise RuntimeError('服务端复核结果早于当前发布版本，未覆盖')
            now = time.time()
            self._set(scope, 'published', next_check=now + self.interval,
                      error='', last_success=now)
            return dict(scope=scope, status='published', changed=changed,
                        fingerprint=fingerprint, version=page.get('version'))
        except Exception as exc:
            now = time.time()
            state = self.store.refresh_state(scope) or {}
            attempt = int(state.get('attempt') or 1)
            self._set(scope, 'retry_wait', next_check=now + min(900, 60 * max(1, attempt)),
                      error=str(exc)[:500])
            return dict(scope=scope, status='retry_wait', error=str(exc)[:500])


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

    def run_once(self, now=None):
        current = time.time() if now is None else float(now)
        # Only default scopes are kept warm; the scan reads version metadata and
        # loads a full page body only for the few scopes it is about to refresh.
        publications = {scope: version for scope, version, _source
                        in self.store.default_publications(limit=2000)}
        for scope in publications:
            # New scopes wait one full interval before the first automatic
            # check: a deploy must not re-query and re-analyse every default
            # page at once while the dashboard is already serving traffic.
            self.store.ensure_refresh_state(scope, next_check=current + self.manager.interval)
        claimed = 0
        for scope in self.store.due_refresh_scopes(current, limit=self.scope_limit):
            body = self.store.published_page(scope) if scope in publications else None
            if not body:
                self.store.set_refresh_state(scope, 'idle', next_check=time.time() + self.manager.interval)
                continue
            result = self.manager.refresh(body)
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
