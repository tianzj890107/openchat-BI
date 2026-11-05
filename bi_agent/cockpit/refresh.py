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

from .cards import valid_card
from .dashboard_source import (RELEASE, STAGE_METRICS, filter_stage_selected, page_analysis_context,
                              supplement_failed_queries)
from . import periods
from .page_cache import (PageRequest, build_page, page_fingerprint, page_scope,
                         stage_evidence, transport_identity)
from .publications import config_version, digest, view_scope
from .runtime import METADATA, SNAPSHOTS
from .targets import maintenance_targets

DEFAULT_IDENTITIES = (1, 2)
DEFAULT_PAGES = ('overview', 'operations', 'analysis')
_DELIVERED_QUERY_CACHE = None
_COMPONENT_QUERY_CACHE = None
_METRIC_STAGES = {code: stage for stage, codes in STAGE_METRICS.items() for code in codes if stage != 'combined'}
DEFAULT_CUSTOM_REFRESH_TTL_SECONDS = 24 * 60 * 60


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def delivered_stage_requests(stage):
    """Query plans from the delivered release snapshot.

    The snapshot is component metadata/configuration, not user evidence.  It
    lets a never-opened node enter preheat without waiting for someone to click
    it.  The refresh path still executes the queries again and validates the
    new receipts, so this never reuses old values as fresh evidence.
    """
    global _DELIVERED_QUERY_CACHE
    if _DELIVERED_QUERY_CACHE is None:
        try:
            _DELIVERED_QUERY_CACHE = json.loads(SNAPSHOTS.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            _DELIVERED_QUERY_CACHE = {}
    selected = {}
    for section in ('analysis', 'batch'):
        for raw, result in (_DELIVERED_QUERY_CACHE.get(section) or {}).items():
            if not isinstance(result, dict) or not result.get('success'):
                continue
            try:
                request = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if isinstance(request, (dict, list)):
                selected[_canonical(request)] = {'request': request}
    try:
        kept, _excluded = filter_stage_selected(selected, stage)
    except ValueError:
        return []
    return [selected[key]['request'] for key in sorted(kept)]


def delivered_component_requests(stage):
    """Build stage query plans from the delivered component configuration.

    The release snapshot is useful for older delivered queries, but some nodes
    use newer metric codes that are only present in ``runtime.json``.  Reading
    the component field definitions keeps first-run preheat independent from a
    browser visit without inventing metric meanings.  The generated requests
    are executed and validated by the normal receipt/evidence path.
    """
    global _COMPONENT_QUERY_CACHE
    if _COMPONENT_QUERY_CACHE is None:
        try:
            _COMPONENT_QUERY_CACHE = json.loads(
                (METADATA.parent / 'runtime.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            _COMPONENT_QUERY_CACHE = {}
    field_keys = {
        'measure', 'subMeasure', 'target', 'valueAxis', 'tableFields', 'categoryAxis',
        'dimensions', 'indicators', 'bidMeasure', 'shipMeasure', 'orderMeasure',
        'quoteMeasure', 'paymentMeasure', 'opportunityMeasure',
    }

    def collect(value, dimensions, indicators):
        if isinstance(value, dict):
            code = value.get('identifierCode')
            if isinstance(code, str) and code:
                if value.get('fieldType') == 'Dimension':
                    dimensions[code] = {key: value[key] for key in
                                        ('identifierCode', 'label', 'alias', 'fieldType', 'valueType')
                                        if key in value}
                elif value.get('fieldType') == 'Indicator':
                    indicators[code] = {key: value[key] for key in
                                        ('identifierCode', 'label', 'alias', 'name', 'fieldType', 'valueType')
                                        if key in value}
        elif isinstance(value, list):
            for item in value:
                collect(item, dimensions, indicators)

    candidates = {}
    specs = list((_COMPONENT_QUERY_CACHE.get('pages') or {}).values())
    specs.extend((_COMPONENT_QUERY_CACHE.get('templates') or {}).values())
    for spec in specs:
        for component in (spec or {}).get('components') or []:
            data = component.get('dataConfig') or {}
            dimensions, indicators = {}, {}
            for key in field_keys:
                collect(data.get(key), dimensions, indicators)
            if not indicators:
                continue
            selected = {}
            for code, indicator in indicators.items():
                if code in _METRIC_STAGES:
                    if _METRIC_STAGES[code] != stage:
                        continue
                    selected[code] = indicator
                    continue
                probe = {
                    'analysisConfig': {'dimensions': list(dimensions.values()),
                                       'indicators': [indicator]},
                    'commonConfig': {'filters': {'logic': 'AND', 'children': []}},
                }
                try:
                    kept, _excluded = filter_stage_selected({'probe': {'request': probe}}, stage)
                except ValueError:
                    return []
                if kept:
                    selected[code] = indicator
            if not selected:
                continue
            query = {
                'analysisConfig': {
                    'dimensions': list(dimensions.values()),
                    'indicators': list(selected.values()),
                },
                'commonConfig': {
                    'filters': {'logic': 'AND', 'children': []},
                    'pagination': {'pageNum': 1, 'pageSize': 500},
                },
            }
            candidates[_canonical(query)] = {'request': query}
    return [candidates[key]['request'] for key in sorted(candidates)]


def _snapshot_scope(config, body):
    return page_scope(config, int(body['id']), body['page'], body.get('uiScope') or 'default', 'ap')


def view_target_scope(view_key, stage):
    """Synthetic maintenance key for one published default-scope AI card."""
    return digest({'view': view_key, 'stage': stage})


def period_target_scope(identity, page, stage, period):
    """Maintenance key for one period x stage preheat target."""
    return digest({'period': period, 'id': int(identity), 'page': page, 'stage': stage})


def preheat_target_scope(identity, page, stage):
    """Maintenance key for a configured slot that has no published card yet."""
    return digest({'preheat': True, 'id': int(identity), 'page': page, 'stage': stage})


def refresh_business_key(kind, identity, page='', stage='', ui_scope='default'):
    """Stable maintenance identity that survives config/contract rotations."""
    return digest({'business': kind, 'id': int(identity), 'page': page or '',
                   'stage': stage or '', 'uiScope': ui_scope or 'default'})


def custom_refresh_expiry(now=None):
    try:
        ttl = int(os.getenv('COCKPIT_CUSTOM_REFRESH_TTL_SECONDS',
                            str(DEFAULT_CUSTOM_REFRESH_TTL_SECONDS)))
    except ValueError:
        ttl = DEFAULT_CUSTOM_REFRESH_TTL_SECONDS
    return (time.time() if now is None else float(now)) + max(300, ttl)


def stage_card_status(store, identity, page, *, now=None):
    """Aggregate refresh state for pages whose AI cards have no page snapshot.

    A seeded future check is a schedule, not an in-flight update.  Manual
    refreshes set ``waiting`` with an immediate next-check time, so they still
    surface as active while a scheduled card does not leave the page saying it
    is updating forever.
    """
    now = time.time() if now is None else float(now)
    rows = []
    for view_key, stage, body in store.default_views(limit=2000):
        context = body.get('context') or {}
        if (int(context.get('id') or 0) != int(identity)
                or context.get('page') != page
                or context.get('engine') not in {'main', None}):
            continue
        state = store.refresh_state(view_target_scope(view_key, stage)) or {}
        rows.append((stage, state, body))
    if not rows:
        return None

    def effective(state):
        status = str(state.get('status') or 'idle')
        if status == 'waiting' and float(state.get('next_check') or 0) > now + 5 \
                and float(state.get('lease_until') or 0) <= now:
            return 'scheduled'
        return status

    states = [effective(state) for _stage, state, _body in rows]
    active = [status for status in states if status in {'running', 'checking', 'queued', 'waiting'}]
    if active:
        status = 'running' if 'running' in active else ('queued' if 'queued' in active else 'waiting')
    elif 'retry_wait' in states or 'failed' in states:
        status = 'retry_wait'
    elif 'published' in states:
        status = 'published'
    elif 'scheduled' in states:
        status = 'scheduled'
    else:
        status = states[0]
    analyzed = max((float((body or {}).get('updatedAt') or 0) for _stage, _state, body in rows), default=0)
    successful = [float(state.get('last_success') or 0) for _stage, state, _body in rows]
    errors = [str(state.get('last_error') or '') for _stage, state, _body in rows
              if state.get('last_error')]
    next_checks = [float(state.get('next_check') or 0) for _stage, state, _body in rows
                   if float(state.get('next_check') or 0) > 0]
    checked = [float(state.get('updated') or 0) for _stage, state, _body in rows]
    return dict(scope='', publicationVersion='', dataAsOf=0, analyzedAt=analyzed,
                publishedAt=max(successful, default=0), update=dict(
                    status=status, lastSuccessAt=max(successful + [analyzed]), nextCheckAt=min(next_checks, default=0),
                    lastCheckedAt=max(checked, default=0), error='; '.join(errors)[:500],
                    attempt=max((int(state.get('attempt') or 0) for _stage, state, _body in rows), default=0)))


class RefreshManager:
    """One-scope-at-a-time, append-preserving publication refresher.

    ``query(identity, kind, payload)`` must be the same shared read-only AP
    transport used by the page.  ``start_analysis(body, resolved)`` is the
    router-owned analysis entry point; passing ``resolved`` avoids querying AP
    a second time.
    """

    def __init__(self, store, config, query, start_analysis, *, interval=900, poll=2.0,
                 timeout=1200, cancel_analysis=None):
        self.store = store
        self.config = config
        self.query = query
        self.start_analysis = start_analysis
        self.interval = max(60, int(interval))
        self.poll = max(0.1, float(poll))
        self.timeout = max(60, int(timeout))
        self.cancel_analysis = cancel_analysis

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
        seen = set()
        for entry in body.get('entries') or []:
            kind, payload = entry.get('kind'), entry.get('payload')
            if kind == 'pg':
                # A previous publication answered this query from PostgreSQL.
                # Try AP again first so a recovered source replaces the fallback.
                retry.append(payload)
                continue
            if kind not in {'analysis', 'batch', 'helmet'} or payload is None:
                raise RuntimeError('历史页面包含无效查询，保留上次完整版本')
            seen.add(_canonical(payload))
            try:
                data = self.query(int(body['id']), kind, payload)
            except Exception as exc:
                if kind == 'helmet':
                    raise RuntimeError('头盔图查询失败，保留上次完整版本') from exc
                failures.append(_canonical(payload))
                continue
            records.append(self._receipt(int(body['id']), kind, payload, data))
        # A publication stores only successful/fallback entries, so failures
        # with no registered fallback would otherwise never be retried.  Re-read
        # them from the stage contexts as well; a recovered AP source must be
        # allowed to replace the old partial evidence.
        previous = []
        for item in (body.get('items') or {}).values():
            for raw in ((item or {}).get('context') or {}).get('unavailableQueries') or []:
                previous.append(json.loads(raw))
        for payload in retry + previous:
            key = _canonical(payload)
            if key in seen:
                continue
            seen.add(key)
            kind = 'batch' if isinstance(payload, list) else 'analysis'
            try:
                data = self.query(int(body['id']), kind, payload)
            except Exception:
                failures.append(key)
                continue
            records.append(self._receipt(int(body['id']), kind, payload, data))
        return records, failures

    def _query_requests(self, identity, requests):
        records, failures = [], []
        for payload in requests:
            kind = 'batch' if isinstance(payload, list) else 'analysis'
            try:
                data = self.query(identity, kind, payload)
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

    def _cancel(self, item):
        if not item or not item.get('id'):
            return
        try:
            if self.cancel_analysis:
                self.cancel_analysis(item['id'])
            else:
                self.store.update_analysis(item['id'], status='cancelled',
                                           progress='后台更新已超时停止')
        except Exception:
            pass

    def _owned(self, claim):
        return bool(claim and self.store.owns_refresh(
            claim['scope'], claim['job_id'], claim['generation']))

    def _await(self, item, claim=None):
        deadline = time.time() + self.timeout
        while item and item.get('status') in {'queued', 'running'}:
            if time.time() > deadline:
                self._cancel(item)
                raise RuntimeError('后台分析更新超时，已停止旧执行，保留上次完整版本')
            if claim:
                if not self.store.heartbeat_refresh(
                        claim['scope'], claim['job_id'],
                        lease=max(180, self.timeout + 60)):
                    self._cancel(item)
                    raise RuntimeError('刷新任务租约已失效，已停止旧执行')
            time.sleep(self.poll)
            item = self.store.get_analysis(item['id'])
        if not item or item.get('status') not in {'completed', 'limited'}:
            raise RuntimeError((item or {}).get('error') or '后台分析未完整交付，保留上次完整版本')
        if (item.get('result') or {}).get('cardContract') != 'cockpit-cards-v1':
            raise RuntimeError('后台分析缺少卡片契约，保留上次完整版本')
        if claim and not self._owned(claim):
            raise RuntimeError('刷新任务已被更新的配置取代，未写回旧结果')
        return item

    def period_policy(self, ui_scope, context=None, *, now=None):
        """Refresh cadence for the business period this scope belongs to."""
        period = periods.period_of_scope(ui_scope, (context or {}).get('period') or '')
        return periods.policy_for(period, now=now, interval=self.interval)

    def _schedule(self, ui_scope, context=None, *, now=None):
        """(status, next_check) for a finished refresh; freeze historical ranges."""
        now = time.time() if now is None else float(now)
        policy = self.period_policy(ui_scope, context, now=now)
        if policy['recheckAfter'] is None:
            return 'frozen', 0.0
        return 'published', now + float(policy['recheckAfter'])

    def _finish(self, scope, claim, status, *, next_check=None, error=None,
                last_success=None):
        if claim:
            return self.store.finish_refresh(
                scope, claim['job_id'], claim['generation'], status,
                next_check=next_check, error=error, last_success=last_success)
        self._set(scope, status, next_check=next_check, error=error,
                  last_success=last_success)
        return True

    def _failure(self, scope, exc, claim=None):
        now = time.time()
        state = self.store.refresh_state(scope) or {}
        attempt = int(state.get('attempt') or 1)
        self._finish(scope, claim, 'retry_wait',
                     next_check=now + min(900, 60 * max(1, attempt)),
                     error=str(exc)[:500])
        return dict(scope=scope, status='retry_wait', error=str(exc)[:500])

    def refresh(self, body):
        """Refresh one published page.  Returns a compact status dict."""
        scope = _snapshot_scope(self.config, body)
        if body.get('dataSource') not in {'ap', 'ap+pg', 'pg'}:
            self._set(scope, 'published', next_check=time.time() + self.interval)
            return dict(scope=scope, status='unchanged', reason='not-ap')
        claim = self.store.claim_refresh_info(
            scope, lease=max(180, self.timeout + 60), config_version=config_version())
        if not claim:
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
                if not self._owned(claim):
                    raise RuntimeError('刷新范围已被更新的配置取代，未写回旧结果')
                queries = sorted({_canonical(record['request']) for record in records
                                  if record['kind'] in {'analysis', 'batch'}})
                receipt_ids = [record['id'] for record in records
                               if record['kind'] in {'analysis', 'batch'}]
                forced = (body.get('configVersion') != config_version()
                          or body.get('dataIdentity') != identity)
                old_scoped = stage_evidence([
                    {'kind': entry.get('kind'), 'request': entry.get('payload'),
                     'response': entry.get('data')}
                    for entry in (body.get('entries') or [])])
                new_scoped = stage_evidence(all_records)
                for stage, old in old_items.items():
                    context = (old or {}).get('context') or {}
                    # Only re-analyse the stages whose own evidence moved.  A
                    # stage without matching evidence falls back to the page
                    # fingerprint so behaviour never becomes more permissive.
                    before = old_scoped.get(stage)
                    after = new_scoped.get(stage)
                    expected_fp = (after or {}).get('fingerprint') or fingerprint
                    expected_queries = (after or {}).get('queries') or queries
                    if forced:
                        unchanged = False
                    elif before and after:
                        unchanged = (before['fingerprint'] == after['fingerprint']
                                     and before['queries'] == after['queries'])
                    elif not before and not after:
                        unchanged = body.get('dataFingerprint') == fingerprint
                    else:
                        unchanged = False
                    record = self.store.stage_evidence_for((old or {}).get('id'))
                    recorded = bool(record
                                    and record.get('fingerprint') == expected_fp
                                    and sorted(record.get('queries') or [])
                                    == sorted(expected_queries))
                    if unchanged and old and old.get('id'):
                        if recorded:
                            continue
                        # One-time migration for analyses published before a
                        # node kept its own fingerprint.  The stage evidence is
                        # unchanged, so recording it against the existing
                        # analysis is truthful and needs no model call.
                        self.store.set_stage_evidence(old['id'], stage, expected_fp,
                                                      expected_queries)
                        continue
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
                    item = self._await(job, claim)
                    analysis_ids[stage] = item['id']
                    self.store.set_stage_evidence(item['id'], stage, expected_fp,
                                                  expected_queries)
            page = build_page(PageRequest(
                id=int(body['id']), page=body['page'], uiScope=body.get('uiScope') or 'default',
                apReceiptIds=[record['id'] for record in records], pgReceiptIds=pg_ids,
                analysisIds=analysis_ids), self.store, self.config,
                data_source=data_source, data_identity=identity)
            if not self._owned(claim):
                raise RuntimeError('刷新范围已被更新的配置取代，未写回旧结果')
            current_page = self.store.published_page(scope)
            if not current_page or current_page.get('version') != page.get('version'):
                if not self.store.publish_page(scope, page):
                    raise RuntimeError('服务端复核结果早于当前发布版本，未覆盖')
            now = time.time()
            status, next_check = self._schedule(body.get('uiScope'), old_items
                                                and next(iter(old_items.values()), {}).get('context')
                                                or None, now=now)
            self._finish(scope, claim, status, next_check=next_check,
                         error='', last_success=now)
            return dict(scope=scope, status=status, changed=changed,
                        fingerprint=fingerprint, version=page.get('version'))
        except Exception as exc:
            return self._failure(scope, exc, claim)

    def refresh_view(self, view_key, stage, analysis):
        """Refresh one published default AI card when its page has no snapshot."""
        context = analysis.get('context') or {}
        scope = view_target_scope(view_key, stage)
        if context.get('engine') != 'main' or context.get('source') != 'service':
            self._set(scope, 'published', next_check=time.time() + self.interval)
            return dict(scope=scope, status='unchanged', reason='not-main')
        claim = self.store.claim_refresh_info(
            scope, lease=max(180, self.timeout + 60), config_version=config_version())
        if not claim:
            return dict(scope=scope, status='already-running')
        try:
            # Successful and previously unavailable queries are both re-read;
            # a recovered AP source replaces the registered PostgreSQL answer.
            # Historical contexts can contain queries for every slot on the
            # page.  Refresh only the stage this card owns.
            requests = _context_requests(context, stage)
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
                job = self.start_analysis(request, resolved)
                self._await(job, claim)
            if not self._owned(claim):
                raise RuntimeError('刷新范围已被更新的配置取代，未写回旧结果')
            now = time.time()
            status, next_check = self._schedule('default', context, now=now)
            self._finish(scope, claim, status, next_check=next_check,
                         error='', last_success=now)
            return dict(scope=scope, status=status, changed=changed)
        except Exception as exc:
            return self._failure(scope, exc, claim)

    def _stage_requests(self, identity, page, stage, period=None):
        """Seed one configured slot from saved cards or the page's own queries.

        A slot may exist on two pages.  Its own page is preferred, then the same
        stage published anywhere else, then the stage's queries from a saved
        page plan.  A saved query plan is not user data, so a missing role's
        plan may be reused from another role; the analysis result is still
        written with the requesting role's identity.  No query is invented: an
        empty result means the browser has never delivered a usable plan yet.
        """
        identity = int(identity)
        data_identity = self.config.identity()
        pages = (page, *[item for item in DEFAULT_PAGES if item != page])
        identities = (identity, *[item for item in DEFAULT_IDENTITIES if item != identity])

        def matches(context):
            return period is None or periods.normalise((context or {}).get('period')) == period

        for candidate_identity in identities:
            for candidate in pages:
                body = self.store.latest_views(candidate_identity, 'main', candidate,
                                               data_identity=data_identity).get(stage)
                context = (body or {}).get('context') or {}
                requests = _context_requests(context, stage)
                if requests and matches(context):
                    return context, requests
            for candidate in pages:
                body = self.store.latest_page(candidate_identity, candidate, 'default',
                                              data_identity=data_identity)
                if not body:
                    continue
                requests = _stage_queries(body, stage)
                if requests:
                    item = (body.get('items') or {}).get(stage) or {}
                    if matches(item.get('context')):
                        return item.get('context') or {}, requests
        # The latest published page plan is also a valid stage-plan source when
        # one role has never opened the page.  It contains only queries, not
        # another user's evidence or results.
        for _scope, body, _source in self.store.page_publications(limit=2000):
            if (body.get('uiScope') or 'default') != 'default' or body.get('page') not in pages:
                continue
            requests = _stage_queries(body, stage)
            if requests:
                item = (body.get('items') or {}).get(stage) or {}
                if matches(item.get('context')):
                    return item.get('context') or {}, requests
        # No browser has visited this node.  The delivered release snapshot
        # carries the exact component query plans; reuse those requests as a
        # plan and fetch fresh receipts rather than requiring navigation first.
        if period is not None:
            # A dated period must never be analysed with the delivered default
            # queries: those carry no period filter, so the result would be the
            # wrong range.  Missing plan means "awaiting-plan", not "guess".
            return {}, []
        return {}, (delivered_component_requests(stage) or delivered_stage_requests(stage))

    def preheat_period(self, identity, page, stage, period):
        """Materialise one configured slot for an explicit business period."""
        scope = period_target_scope(identity, page, stage, period)
        claim = self.store.claim_refresh_info(
            scope, lease=max(180, self.timeout + 60), config_version=config_version())
        if not claim:
            return dict(scope=scope, status='already-running')
        try:
            seed, requests = self._stage_requests(identity, page, stage, period=period)
            if not requests:
                self._finish(scope, claim, 'awaiting-plan',
                             next_check=time.time() + self.interval, error='')
                return dict(scope=scope, status='awaiting-plan')
            identity = int(identity)
            records, failures = self._query_requests(identity, requests)
            extra, notes = self._supplement(identity, failures, [stage])
            pg_ids = sorted({value['receiptId'] for value in extra.values()})
            if not records and not pg_ids:
                raise RuntimeError('本次取数和已登记补查均失败，保留上次卡片')
            request = dict(
                id=identity, engine='main', source='service', page=page, stage=stage,
                defaultView=True, period=period,
                department=seed.get('department') or '全部产品部',
                filters=seed.get('filters') or {}, repositoryId='',
                clarifications=seed.get('clarifications') or {},
                baselineAnalysisId='', chartSnapshotId=RELEASE,
                chartQueries=sorted({_canonical(record['request']) for record in records}),
                apReceiptIds=[record['id'] for record in records],
                unavailableQueries=list(failures))
            resolved = page_analysis_context(
                {**request, 'pgReceiptIds': pg_ids}, self.store,
                data_mode='ap', resolve_fallback=False, fallback_notes=notes)
            key = view_scope({**request, **resolved, 'sourceMode': 'service',
                              'stageName': stage})
            existing = self.store.published_view(key).get(stage)
            changed = (not existing
                       or existing.get('context', {}).get('dataFingerprint')
                       != resolved['dataFingerprint'])
            if changed:
                job = self.start_analysis(request, resolved)
                item = self._await(job, claim)
                self.store.set_stage_evidence(
                    item['id'], stage, resolved['dataFingerprint'],
                    [record for record in request['chartQueries']])
            if not self._owned(claim):
                raise RuntimeError('刷新范围已被更新的配置取代，未写回旧结果')
            now = time.time()
            status, next_check = self._schedule('default', request, now=now)
            self._finish(scope, claim, status, next_check=next_check,
                         error='', last_success=now)
            self.store.set_refresh_state(view_target_scope(key, stage), status,
                                         next_check=next_check, last_success=now)
            return dict(scope=scope, status=status, changed=changed, period=period)
        except Exception as exc:
            return self._failure(scope, exc, claim)

    def preheat_target(self, identity, page, stage):
        """Materialise a card for one configured slot, even before it is opened."""
        scope = preheat_target_scope(identity, page, stage)
        claim = self.store.claim_refresh_info(
            scope, lease=max(180, self.timeout + 60), config_version=config_version())
        if not claim:
            return dict(scope=scope, status='already-running')
        try:
            seed, requests = self._stage_requests(identity, page, stage)
            if not requests:
                # No browser has delivered this page's query plan yet; this is
                # a waiting condition, not a failed refresh.
                self._finish(scope, claim, 'awaiting-plan',
                             next_check=time.time() + self.interval, error='')
                return dict(scope=scope, status='awaiting-plan')
            identity = int(identity)
            records, failures = self._query_requests(identity, requests)
            extra, notes = self._supplement(identity, failures, [stage])
            pg_ids = sorted({value['receiptId'] for value in extra.values()})
            if not records and not pg_ids:
                raise RuntimeError('本次取数和已登记补查均失败，保留上次卡片')
            request = dict(
                id=identity, engine='main', source='service', page=page, stage=stage,
                defaultView=True, period=seed.get('period') or '2025-10',
                department=seed.get('department') or '全部产品部',
                filters=seed.get('filters') or {}, repositoryId='',
                clarifications=seed.get('clarifications') or {},
                baselineAnalysisId='', chartSnapshotId=RELEASE,
                chartQueries=sorted({_canonical(record['request']) for record in records}),
                apReceiptIds=[record['id'] for record in records],
                unavailableQueries=list(failures))
            resolved = page_analysis_context(
                {**request, 'pgReceiptIds': pg_ids}, self.store,
                data_mode='ap', resolve_fallback=False, fallback_notes=notes)
            key = view_scope({**request, **resolved, 'sourceMode': 'service',
                              'stageName': stage})
            existing = self.store.published_view(key).get(stage)
            changed = (not existing
                       or existing.get('context', {}).get('dataFingerprint')
                       != resolved['dataFingerprint'])
            if changed:
                job = self.start_analysis(request, resolved)
                self._await(job, claim)
            if not self._owned(claim):
                raise RuntimeError('刷新范围已被更新的配置取代，未写回旧结果')
            now = time.time()
            status, next_check = self._schedule('default', seed, now=now)
            self._finish(scope, claim, status, next_check=next_check,
                         error='', last_success=now)
            self.store.set_refresh_state(view_target_scope(key, stage), status,
                                         next_check=next_check, last_success=now)
            return dict(scope=scope, status=status, changed=changed)
        except Exception as exc:
            return self._failure(scope, exc, claim)


def _context_requests(context, stage=None):
    requests, seen, items = [], set(), {}
    parsed = []
    for value in list(context.get('chartQueries') or []) + list(context.get('unavailableQueries') or []):
        try:
            request = json.loads(value)
        except (TypeError, ValueError):
            continue
        key = _canonical(request)
        if key in seen:
            continue
        seen.add(key)
        parsed.append((key, request))
        items[key] = {'request': request}
    if stage:
        try:
            kept, _excluded = filter_stage_selected(items, stage)
        except ValueError:
            return []
        allowed = set(kept)
        parsed = [(key, request) for key, request in parsed if key in allowed]
    requests = [request for _key, request in parsed]
    return requests


def _stage_queries(body, stage):
    """Keep only the page-plan queries that belong to one business stage."""
    items = {}
    for index, entry in enumerate(body.get('entries') or []):
        kind, payload = entry.get('kind'), entry.get('payload')
        if kind not in {'analysis', 'batch'} or payload is None:
            continue
        items[str(index)] = {'request': payload}
    if not items:
        return []
    try:
        kept, _excluded = filter_stage_selected(items, stage)
    except ValueError:
        return []
    return [items[key]['request'] for key in sorted(kept, key=int)]


def publication_status(store, scope, body=None):
    now = time.time()
    state = store.refresh_state(scope) or {}
    body = body or {}
    items = body.get('items') or {}
    analyzed = max((float((item or {}).get('updatedAt') or 0) for item in items.values()), default=0)
    context = (body.get('items') or {}).get('stage') or {}
    policy = periods.policy_for(
        periods.period_of_scope(body.get('uiScope'), (body.get('items') or {})
                                and next(iter((body.get('items') or {}).values()), {})
                                .get('context', {}).get('period') or ''))
    return dict(
        scope=scope,
        period=policy['period'],
        periodPolicy=policy,
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
            queue=store.refresh_queue_stats(now=now),
        ),
    )


class RefreshScheduler(threading.Thread):
    """Small POC scheduler.  A database lease prevents duplicate scope workers."""

    def __init__(self, manager, store, *, scan_seconds=20, scope_limit=1):
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
            if stage == 'combined':
                continue  # Composite refresh is explicit and reuses saved receipts only.
            context = body.get('context') or {}
            # The publication row is append-only history.  A view key created
            # by an older component/config revision stays displayable but is
            # not a refresh target; the current configured slot is handled by
            # the preheat target below.
            if view_scope(context) != view_key:
                continue
            targets.setdefault(view_target_scope(view_key, stage), (view_key, stage, body))
        return targets

    def _period_targets(self):
        targets = {}
        for period in periods.period_catalog():
            for identity, page, stage in maintenance_targets():
                targets[period_target_scope(identity, page, stage, period)] = (
                    identity, page, stage, period)
        return targets

    def _preheat_targets(self):
        targets = {}
        for identity, page, stage in maintenance_targets():
            targets[preheat_target_scope(identity, page, stage)] = (identity, page, stage)
        return targets

    def _seed_check(self, ui_scope, context, current):
        """Next check for a published scope; historical periods stay frozen."""
        policy = self.manager.period_policy(ui_scope or 'default', context, now=current)
        if policy['recheckAfter'] is None:
            return 0.0, 'frozen'
        return current + float(policy['recheckAfter']), 'waiting'

    def _resume(self, scope, check, seed_status):
        """Un-freeze a scope whose period became active/grace again."""
        if seed_status == 'frozen':
            return
        state = self.store.refresh_state(scope) or {}
        if state.get('status') == 'frozen':
            # Resume on the normal cadence; a frozen row is never running, so
            # this cannot steal a live lease or delete published history.
            self.store.set_refresh_state(scope, 'waiting', next_check=check)

    def _seed_periods(self, current, period_targets):
        """Register the explicit period x stage catalog.

        A period with no published card is queued once (low priority) even when
        the period is historical: the first fill must happen exactly once, then
        the normal policy freezes it.  Periods that already have a card follow
        the regular cadence.
        """
        if not period_targets:
            return set()
        covered = self.store.published_stage_periods()
        version = config_version()
        active = set()
        for target, (identity, page, stage, period) in period_targets.items():
            active.add(target)
            ready = (int(identity), stage, period) in covered
            check, seed_status = self._seed_check('default', {'period': period}, current)
            state = self.store.refresh_state(target) or {}
            if not ready and state.get('status') not in {'running', 'frozen'}:
                self.store.ensure_refresh_state(
                    target, next_check=current, expires=0, lifecycle='active',
                    config_version=version,
                    business_key=refresh_business_key('period', identity, page, stage,
                                                      ui_scope=period))
                if state.get('status') not in {'waiting', 'queued'}:
                    self.store.request_refresh(target, now=current)
            else:
                self.store.ensure_refresh_state(
                    target, next_check=check, expires=0, lifecycle='active',
                    config_version=version,
                    business_key=refresh_business_key('period', identity, page, stage,
                                                      ui_scope=period))
                if seed_status == 'frozen' and ready:
                    self.store.set_refresh_state(target, 'frozen', next_check=0)
                else:
                    self._resume(target, check, seed_status)
        return active

    def _seed(self, bodies, current, view_targets, preheat_targets, custom_targets,
              period_targets=None):
        """Register every configured slot, not only the ones already published.

        A deploy must not re-query and re-analyse every default page at once,
        so the first automatic check waits one interval.  A page that has never
        formed a complete snapshot is still registered; its published stage
        cards are maintained separately, and a configured slot with no card yet
        is materialised by ``RefreshManager.preheat_target``.
        """
        due = current + self.manager.interval
        active = set()
        version = config_version()
        for identity in DEFAULT_IDENTITIES:
            for page in DEFAULT_PAGES:
                scope = page_scope(self.manager.config, identity, page, 'default', 'ap')
                active.add(scope)
                body = bodies.get(scope) or {}
                item = next(iter((body.get('items') or {}).values()), {}) or {}
                check, seed_status = self._seed_check(
                    body.get('uiScope'), item.get('context'), current)
                self.store.ensure_refresh_state(
                    scope, next_check=check if body else due, expires=0, lifecycle='active',
                    config_version=version,
                    business_key=refresh_business_key('page', identity, page,
                                                      ui_scope='default'))
                if body and seed_status == 'frozen':
                    self.store.set_refresh_state(scope, 'frozen', next_check=0)
                else:
                    self._resume(scope, check, seed_status)
        for target, (view_key, stage, body) in view_targets.items():
            context = body.get('context') or {}
            identity = int(context.get('id') or 0)
            page = context.get('page') or ''
            active.add(target)
            check, seed_status = self._seed_check(context.get('uiScope', 'default'),
                                                  context, current)
            self.store.ensure_refresh_state(
                target, next_check=check, expires=0, lifecycle='active',
                config_version=version,
                business_key=refresh_business_key('view', identity, page, stage))
            if seed_status == 'frozen':
                self.store.set_refresh_state(target, 'frozen', next_check=0)
            else:
                self._resume(target, check, seed_status)
        preheat_check, preheat_status = self._seed_check('default', None, current)
        for target, (identity, page, stage) in preheat_targets.items():
            active.add(target)
            state = self.store.refresh_state(target)
            self._resume(target, preheat_check, preheat_status)
            # A configured slot without a readable card is a first-run task, not
            # a future maintenance task.  Start it on this scan so opening the
            # page does not wait for the 15-minute interval.  Existing retry
            # backoff is respected to avoid a hot loop when the source is down.
            if not self._has_card(identity, page, stage):
                if state is None:
                    self.store.ensure_refresh_state(
                        target, next_check=current, expires=0, lifecycle='active',
                        config_version=version,
                        business_key=refresh_business_key('preheat', identity, page, stage))
                elif state.get('status') not in {'running', 'retry_wait', 'frozen'}:
                    self.store.request_refresh(
                        target, now=current, expires=0,
                        config_version=version,
                        business_key=refresh_business_key('preheat', identity, page, stage))
            else:
                self.store.ensure_refresh_state(
                    target, next_check=due, expires=0, lifecycle='active',
                    config_version=version,
                    business_key=refresh_business_key('preheat', identity, page, stage))
        for scope, body, last_access in custom_targets:
            identity = int(body.get('id') or 0)
            page = body.get('page') or ''
            ui_scope = body.get('uiScope') or 'default'
            state = self.store.refresh_state(scope) or {}
            expires = max(float(state.get('expires') or 0),
                          custom_refresh_expiry(last_access or current))
            active.add(scope)
            item = next(iter((body.get('items') or {}).values()), {}) or {}
            check, seed_status = self._seed_check(ui_scope, item.get('context'), current)
            self.store.ensure_refresh_state(
                scope, next_check=check, expires=expires,
                last_access=last_access or current, lifecycle='active',
                config_version=version,
                business_key=refresh_business_key('page', identity, page,
                                                  ui_scope=ui_scope))
            if seed_status == 'frozen':
                self.store.set_refresh_state(scope, 'frozen', next_check=0)
            else:
                self._resume(scope, check, seed_status)
        active |= self._seed_periods(current, period_targets or {})
        # Rows from an older config are retained as history but no longer
        # participate in scheduling.  Custom scopes remain active until TTL.
        self.store.retire_unknown_refreshes(active, now=current)
        return active

    def _has_card(self, identity, page, stage):
        """Whether a saved card can already be served for this role/stage."""
        data_identity = self.manager.config.identity()
        for candidate in (page, *[item for item in DEFAULT_PAGES if item != page]):
            for key, stage_name, body in self.store.default_views(limit=2000):
                context = (body or {}).get('context') or {}
                if (stage_name == stage and int(context.get('id') or 0) == int(identity)
                        and context.get('page') == candidate
                        and view_scope(context) == key and valid_card(body)):
                    return True
            body = self.store.latest_page(identity, candidate, 'default',
                                          data_identity=data_identity)
            if (body and body.get('configVersion') == config_version()
                    and valid_card((body.get('items') or {}).get(stage))):
                return True
        return False

    def run_once(self, now=None):
        current = time.time() if now is None else float(now)
        bodies = self._page_bodies()
        custom_bodies = [
            (scope, body, source_time) for scope, body, source_time in
            self.store.page_publications(limit=2000)
            if (body.get('uiScope') or 'default') != 'default'
            and body.get('configVersion') == config_version()
        ]
        views = self._view_targets()
        preheat = self._preheat_targets()
        period_targets = self._period_targets()
        # A published card is already maintained through its view target; a
        # second preheat scope for the same page/stage would double the work.
        published_targets = set()
        for _key, stage, analysis in views.values():
            context = analysis.get('context') or {}
            published_targets.add((int(context.get('id') or 0), context.get('page'), stage))
        self._seed(bodies, current, views, preheat, custom_bodies, period_targets)
        # A whole-page refresh already re-analyses every stage in its plan;
        # maintaining those same stage cards separately would double the calls.
        pages_with_body = {(int(body['id']), body['page']) for body in bodies.values()
                           if body.get('uiScope') == 'default'}
        covered = {(int(body['id']), body['page']): set(body.get('items') or {})
                   for body in bodies.values() if body.get('uiScope') == 'default'}
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
            elif scope in period_targets:
                identity, page, stage, period = period_targets[scope]
                result = self.manager.preheat_period(identity, page, stage, period)
            elif scope in preheat:
                identity, page, stage = preheat[scope]
                if ((identity, page, stage) in published_targets
                        or stage in covered.get((identity, page), set())):
                    self.store.set_refresh_state(
                        scope, 'published', next_check=current + self.manager.interval)
                    continue
                result = self.manager.preheat_target(identity, page, stage)
            else:
                # No query plan yet: stay registered for the first complete
                # page instead of pretending the scope is idle or busy.
                self.store.set_refresh_state(
                    scope, 'awaiting-plan', next_check=current + self.manager.interval)
                continue
            if result.get('status') not in {'already-running', 'awaiting-plan'}:
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


def period_coverage(store, catalog=None, *, identities=DEFAULT_IDENTITIES):
    """Per period x stage publish coverage for the configured catalog."""
    periods_list = catalogue = list(catalog) if catalog else periods.period_catalog()
    published = store.published_stage_periods()
    stages = sorted({stage for _identity, _page, stage in maintenance_targets()})
    rows = []
    for period in periods_list:
        for identity in identities:
            for stage in stages:
                ready = (int(identity), stage, period) in published
                rows.append(dict(period=period, identity=int(identity), stage=stage,
                                 status='ready' if ready else 'missing'))
    return dict(catalog=catalogue,
                total=len(rows),
                ready=sum(1 for row in rows if row['status'] == 'ready'),
                missing=sum(1 for row in rows if row['status'] == 'missing'),
                periods=rows)
