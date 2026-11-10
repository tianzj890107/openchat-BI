"""Isolated, read-only AP transport. Never reads ontology/Doris credentials."""
from __future__ import annotations

import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

PATHS = {
    'analysis': '/v1/ontology/data/query',
    'batch': '/v1/ontology/data/multidimensional/batch',
    'helmet': '/v1/graphs/helmet-view',
}
MAX_RESPONSE = 16 * 1024 * 1024
COMBINATION_UNCONFIGURED = ('本地查询组合未配置', '本地查询组合未启用')


def _upstream_message(body):
    if not isinstance(body, dict):
        return ''
    for key in ('message', 'msg', 'detail', 'errorMsg', 'error'):
        value = body.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ''


def _analysis_indicators(payload):
    if not isinstance(payload, dict):
        return []
    config = payload.get('analysisConfig')
    indicators = config.get('indicators') if isinstance(config, dict) else None
    if not isinstance(indicators, list):
        return []
    return [item for item in indicators
            if isinstance(item, dict) and isinstance(item.get('identifierCode'), str)
            and item.get('identifierCode').strip()]


def _split_analysis(payload):
    """One AP query per indicator, used only after a combination rejection."""
    indicators = _analysis_indicators(payload)
    if len(indicators) < 2:
        return []
    parts = []
    for indicator in indicators:
        child = deepcopy(payload)
        child['analysisConfig']['indicators'] = [deepcopy(indicator)]
        parts.append(child)
    return parts


def _combination_rejected(error):
    return (isinstance(error, HTTPException) and error.status_code == 502
            and any(marker in str(error.detail or '') for marker in COMBINATION_UNCONFIGURED))


def _cell_value(cell):
    return cell.get('value') if isinstance(cell, dict) else cell


def _join_part(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _merge_analysis(payload, parts, results):
    """Merge per-indicator TABLE results on their shared dimension values.

    The payload keeps its original indicator set and receipt key, so published
    evidence still describes the query the dashboard requested.  Missing cells
    are left absent; no metric is invented and no dimension row is dropped.
    """
    if not results or len(results) != len(parts):
        raise HTTPException(502, 'AP拆分查询未返回完整指标结果')
    first = results[0]
    if (not isinstance(first, dict) or not isinstance(first.get('result'), dict)
            or first.get('resultType') != 'TABLE'):
        raise HTTPException(502, 'AP拆分查询结果不是同构表格，未合并部分指标')
    columns, seen = [], set()
    for data, part in zip(results, parts):
        if (not isinstance(data, dict) or data.get('resultType') != first.get('resultType')
                or not isinstance(data.get('result'), dict)):
            raise HTTPException(502, 'AP拆分查询结果结构不一致，未合并部分指标')
        expected = str((part.get('analysisConfig') or {}).get('indicators', [{}])[0].get('identifierCode') or '')
        returned = {str(column.get('identifierCode') or '') for column in
                    data['result'].get('columns') or [] if isinstance(column, dict)}
        if expected and expected not in returned:
            raise HTTPException(502, f'AP拆分查询缺少指标 {expected} 的返回列，未合并部分指标')
        for column in data['result'].get('columns') or []:
            if not isinstance(column, dict):
                raise HTTPException(502, 'AP拆分查询返回了无效列定义')
            key = str(column.get('identifierCode') or '') or _join_part(column)
            if key in seen:
                continue
            seen.add(key)
            columns.append(deepcopy(column))
    config = payload.get('analysisConfig') or {}
    dimension_codes = [str(item.get('identifierCode') or '') for item in config.get('dimensions') or []
                       if isinstance(item, dict) and item.get('identifierCode')]
    if dimension_codes:
        rows_by_key = {}
        for data in results:
            available = {str(column.get('identifierCode') or '') for column in
                         data['result'].get('columns') or [] if isinstance(column, dict)}
            missing = [code for code in dimension_codes if code not in available]
            if missing:
                raise HTTPException(502, 'AP拆分查询缺少维度列，无法按期间对齐指标')
            for row in data['result'].get('rows') or []:
                if not isinstance(row, dict):
                    raise HTTPException(502, 'AP拆分查询返回了无效行')
                key = tuple(_join_part(_cell_value(row.get(code))) for code in dimension_codes)
                target = rows_by_key.setdefault(key, {})
                for code, cell in row.items():
                    target[code] = deepcopy(cell)
        rows = list(rows_by_key.values())
    else:
        merged_row, has_row = {}, False
        for data in results:
            values = data['result'].get('rows') or []
            if not isinstance(values, list) or len(values) > 1 or any(not isinstance(row, dict) for row in values):
                raise HTTPException(502, 'AP拆分查询返回多行聚合结果，未合并部分指标')
            if values:
                has_row = True
                merged_row.update({code: deepcopy(cell) for code, cell in values[0].items()})
        rows = [merged_row] if has_row else []
    merged = deepcopy(first)
    merged['result'] = {**deepcopy(first['result']), 'columns': columns, 'rows': rows}
    return merged


class APQuery(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: int = Field(default=1, ge=1, le=2)
    kind: Literal['analysis', 'batch', 'helmet']
    payload: dict | list


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A login redirect must not disclose the server's AP credentials.
        return None


@dataclass(frozen=True)
class APConfig:
    base_url: str
    headers_file: str
    timeout: float
    concurrency: int
    receipt_ttl: int
    batch_mode: str = 'individual'
    repository_id: str = '8'

    @classmethod
    def load(cls):
        try:
            config = cls(os.getenv('COCKPIT_AP_BASE_URL', '').rstrip('/'),
                os.getenv('COCKPIT_AP_HEADERS_FILE', ''),
                min(240., max(1., float(os.getenv('COCKPIT_AP_TIMEOUT_SECONDS', '10')))),
                min(8, max(1, int(os.getenv('COCKPIT_AP_CONCURRENCY', '4')))),
                min(86400, max(60, int(os.getenv('COCKPIT_AP_RECEIPT_TTL_SECONDS', '1800')))),
                os.getenv('COCKPIT_AP_BATCH_MODE', 'individual'),
                os.getenv('COCKPIT_AP_REPOSITORY_ID', '8').strip())
        except ValueError:
            raise HTTPException(503, 'Cockpit AP配置无效') from None
        parts = urlsplit(config.base_url)
        if config.batch_mode not in {'native','individual'}:
            raise HTTPException(503, 'COCKPIT_AP_BATCH_MODE必须为native或individual')
        if not config.repository_id or len(config.repository_id) > 32 or not config.repository_id.isdigit():
            raise HTTPException(503, 'COCKPIT_AP_REPOSITORY_ID必须为数字本体库ID')
        if parts.scheme not in {'http', 'https'} or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
            raise HTTPException(503, '请配置独立的COCKPIT_AP_BASE_URL')
        return config

    def identity(self):
        import hashlib
        headers=self.headers()
        scope={'base':self.base_url,**{k.lower():v for k,v in headers.items() if k.lower() in {'x-app-id','x-ontology-repository-id'}}}
        return hashlib.sha256(json.dumps(scope,sort_keys=True).encode()).hexdigest()[:20]

    def headers(self):
        try:
            if self.headers_file and os.name=='posix' and Path(self.headers_file).stat().st_mode & 0o077:
                raise ValueError('AP credentials file must be private')
            headers = json.loads(Path(self.headers_file).read_text()) if self.headers_file else {}
            if not isinstance(headers, dict) or any(not isinstance(k, str) or not isinstance(v, str) or '\n' in k+v or '\r' in k+v for k,v in headers.items()):
                raise ValueError()
            forbidden = {'host', 'content-length', 'connection', 'transfer-encoding'}
            if any(k.lower() in forbidden for k in headers):
                raise ValueError()
            headers = {k: v for k, v in headers.items() if k.lower() != 'x-ontology-repository-id'}
            return {**headers, 'X-Ontology-Repository-Id': self.repository_id,
                    'Content-Type': 'application/json', 'Accept': 'application/json'}
        except (OSError, ValueError):
            raise HTTPException(503, 'Cockpit AP认证配置不可用，请检查独立请求头文件') from None


def data_mode():
    mode = os.getenv('COCKPIT_DATA_MODE', 'ap')
    if mode not in {'ap', 'snapshot'}:
        raise HTTPException(503, 'COCKPIT_DATA_MODE必须为ap或snapshot')
    return mode


class APGateway:
    def __init__(self, config: APConfig, opener=None):
        self.config = config
        self._capacity = threading.BoundedSemaphore(config.concurrency)
        self._opener = opener or build_opener(ProxyHandler({}), NoRedirect())

    def _sanitize(self, text):
        """Keep the upstream metric reason, never credentials or line breaks."""
        try:
            secrets = [value for value in self.config.headers().values()
                       if isinstance(value, str) and len(value) >= 4]
        except HTTPException:
            secrets = []
        cleaned = str(text or '')
        for value in secrets:
            cleaned = cleaned.replace(value, '***')
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        return cleaned[:240]

    def _diagnostic_error(self, error, message='', upstream_status=None):
        from .diagnostics import redact
        try:
            for value in self.config.headers().values():
                if isinstance(value,str) and len(value)>=4:message=str(message).replace(value,'[REDACTED]')
        except HTTPException:
            pass
        if message:error.diagnostic_message=redact(message)
        error.upstream_status=upstream_status
        return error

    def query(self, kind, payload, *, _deadline=None, timing=None):
        deadline = _deadline if _deadline is not None else time.monotonic() + self.config.timeout
        try:
            return self._query(kind, payload, _deadline=deadline, timing=timing)
        except HTTPException as error:
            if kind != 'analysis' or not _combination_rejected(error):
                raise
            parts = _split_analysis(payload)
            if not parts:
                raise
            return self._query_split_analysis(payload, parts, _deadline=deadline, timing=timing)

    def _query_split_analysis(self, payload, parts, *, _deadline, timing):
        if time.monotonic() >= _deadline:
            raise HTTPException(504, 'AP整批查询超时，未交付部分结果')
        results, errors, timings = {}, {}, [{} for _ in parts]
        workers = min(len(parts), max(1, self.config.concurrency))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix='cockpit-ap-split') as pool:
            futures = {pool.submit(self.query, 'analysis', part, _deadline=_deadline,
                                   timing=timings[index]): index
                       for index, part in enumerate(parts)}
            for future in as_completed(futures):
                index = futures[future]
                try:
                    results[index] = future.result()
                except Exception as error:
                    errors[index] = error
        if timing is not None:
            for item in timings:
                for key, value in item.items():
                    timing[key] = timing.get(key, 0) + value if isinstance(value, (int, float)) else value
        if errors:
            index = min(errors)
            error = errors[index]
            if _combination_rejected(error):
                code = str((parts[index].get('analysisConfig') or {}).get('indicators', [{}])[0].get('identifierCode') or '')
                raise HTTPException(502, f'AP未返回成功的数据结果：指标 {code} 本地查询组合未配置，拆分查询仍失败') from None
            raise error
        return _merge_analysis(payload, parts, [results[index] for index in range(len(parts))])

    def _query(self, kind, payload, *, _deadline=None, timing=None):
        if kind not in PATHS:
            raise HTTPException(422, '不支持的只读AP接口')
        if kind == 'batch':
            if not isinstance(payload, list) or not payload or len(payload) > 40 or any(not isinstance(x, dict) or not isinstance(x.get('analysisConfig'), dict) for x in payload):
                raise HTTPException(422, '批量AP请求必须是1至40个查询配置')
        elif not isinstance(payload, dict) or (kind == 'analysis' and not isinstance(payload.get('analysisConfig'), dict)):
            raise HTTPException(422, '无效的AP查询配置')
        if kind == 'helmet' and (not payload.get('flowCode') or any(not isinstance(v, (str, int, float, bool)) for v in payload.values())):
            raise HTTPException(422, '头盔图请求必须包含flowCode和标量参数')
        encoded = json.dumps(payload, ensure_ascii=False).encode()
        if len(encoded) > 256 * 1024:
            raise HTTPException(413, 'AP查询配置过大')
        # One budget per HTTP request: queueing behind the shared upstream bound
        # and the upstream execution share the same deadline, so a saturated
        # page cannot wait timeout*2 before the browser gives up.
        deadline = _deadline if _deadline is not None else time.monotonic() + self.config.timeout
        if kind == 'batch' and self.config.batch_mode == 'individual':
            # Explicit transport policy, not a partial-result or alternate-source fallback.
            # One overall deadline and the existing global capacity bound every child.
            cache = {}; result = []; size = 2
            for child in payload:
                key = json.dumps(child, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
                if key not in cache:
                    cache[key] = self.query('analysis', child, _deadline=deadline, timing=timing)
                item = dict(success=True, data=deepcopy(cache[key]))
                size += len(json.dumps(item, ensure_ascii=False).encode()) + 1
                if size > MAX_RESPONSE:raise HTTPException(502, 'AP响应过大，请缩小查询范围')
                result.append(item)
            if time.monotonic() > deadline:raise HTTPException(504, 'AP整批查询超时，未交付部分结果')
            return result
        headers = self.config.headers()
        url = self.config.base_url + PATHS[kind]
        request = Request(url + ('?' + urlencode(payload) if kind == 'helmet' else ''),
            data=None if kind == 'helmet' else encoded, headers=headers,
            method='GET' if kind == 'helmet' else 'POST')
        remaining = deadline-time.monotonic()
        if remaining <= 0:
            raise HTTPException(504, 'AP整批查询超时，未交付部分结果')
        # Queue behind the shared upstream bound instead of failing a page query.
        # The request deadline still caps the wait, so saturated traffic degrades
        # to one bounded timeout rather than bursty 429s in the dashboard.
        queue_started = time.monotonic() if timing is not None else None
        admitted = self._capacity.acquire(timeout=remaining)
        if timing is not None:
            queued = round((time.monotonic() - queue_started) * 1000, 1)
            timing['backendQueueMs'] = timing.get('backendQueueMs', 0) + queued
        if not admitted:
            raise HTTPException(504, 'AP查询排队超时，请稍后重试')
        try:
            timeout = deadline-time.monotonic()
            if timeout <= 0:raise HTTPException(504, 'AP整批查询超时，未交付部分结果')
            upstream_started = time.monotonic() if timing is not None else None
            with self._opener.open(request, timeout=timeout) as response:
                raw = response.read(MAX_RESPONSE + 1)
            if timing is not None:
                timing['upstreamMs'] = timing.get('upstreamMs', 0) + round((time.monotonic() - upstream_started) * 1000, 1)
            if len(raw) > MAX_RESPONSE:
                raise HTTPException(502, 'AP响应过大，请缩小查询范围')
            body = json.loads(raw)
            success = isinstance(body, dict) and (body.get('success') is True or str(body.get('code', '')).strip() == '200')
            if not success or body.get('data') is None:
                reason = self._sanitize(_upstream_message(body))
                detail = 'AP未返回成功的数据结果'
                detail += ('：' + reason) if reason else '，请检查查询口径及AP认证'
                error=HTTPException(502, detail)
                error.upstream_code=body.get('code')
                raise self._diagnostic_error(error,_upstream_message(body),getattr(response,'status',None))
            if kind == 'batch':
                failed = next((item for item in body['data'] if isinstance(item, dict) and item.get('success') is not True), None) if isinstance(body['data'], list) else None
                if not isinstance(body['data'], list) or len(body['data']) != len(payload) or failed is not None or any(not isinstance(v, dict) or v.get('data') is None for v in body['data']):
                    reason = self._sanitize(_upstream_message(failed))
                    detail = 'AP批量查询不完整或包含失败子查询'
                    detail += ('：' + reason) if reason else '；未交付缺项结果'
                    raise HTTPException(502, detail)
            if time.monotonic() > deadline:
                raise HTTPException(504, 'AP整批查询超时，未交付部分结果')
            return body['data']
        except HTTPError as exc:
            upstream=''
            try:
                upstream=_upstream_message(json.loads(exc.read(65536)))
            except (OSError,ValueError,AttributeError):
                pass
            if exc.code in {401, 403, 301, 302, 303, 307, 308}:
                raise self._diagnostic_error(HTTPException(502, 'AP认证失效或权限不足，请更新Cockpit独立认证'),upstream,exc.code) from None
            raise self._diagnostic_error(HTTPException(502, 'AP请求失败；未切换到本体、数据库或旧快照'),upstream,exc.code) from None
        except (TimeoutError, URLError):
            raise HTTPException(504, 'AP请求超时或不可达；未切换到其他数据源') from None
        except (ValueError, OSError):
            raise HTTPException(502, 'AP响应无效；未展示未校验的数据') from None
        finally:
            self._capacity.release()


_gateway_lock = threading.Lock()
_gateway = None


def get_gateway():
    global _gateway
    config = APConfig.load()
    with _gateway_lock:
        if _gateway is None or _gateway.config != config:
            _gateway = APGateway(config)
        return _gateway
