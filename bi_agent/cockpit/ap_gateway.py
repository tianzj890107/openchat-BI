"""Isolated, read-only AP transport. Never reads ontology/Doris credentials."""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

PATHS = {
    'analysis': '/ontology/api/v1/analysis/data/query',
    'batch': '/x360/v1/ontology/data/multidimensional/batch',
    'helmet': '/x360/v1/graphs/helmet-view',
}
MAX_RESPONSE = 16 * 1024 * 1024


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

    @classmethod
    def load(cls):
        try:
            config = cls(os.getenv('COCKPIT_AP_BASE_URL', '').rstrip('/'),
                os.getenv('COCKPIT_AP_HEADERS_FILE', ''),
                min(30., max(1., float(os.getenv('COCKPIT_AP_TIMEOUT_SECONDS', '10')))),
                min(8, max(1, int(os.getenv('COCKPIT_AP_CONCURRENCY', '2')))),
                min(86400, max(60, int(os.getenv('COCKPIT_AP_RECEIPT_TTL_SECONDS', '1800')))))
        except ValueError:
            raise HTTPException(503, 'Cockpit AP配置无效') from None
        parts = urlsplit(config.base_url)
        if parts.scheme not in {'http', 'https'} or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
            raise HTTPException(503, '请配置独立的COCKPIT_AP_BASE_URL')
        return config

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
            return {**headers, 'Content-Type': 'application/json', 'Accept': 'application/json'}
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

    def query(self, kind, payload):
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
        headers = self.config.headers()
        url = self.config.base_url + PATHS[kind]
        request = Request(url + ('?' + urlencode(payload) if kind == 'helmet' else ''),
            data=None if kind == 'helmet' else encoded, headers=headers,
            method='GET' if kind == 'helmet' else 'POST')
        if not self._capacity.acquire(blocking=False):
            raise HTTPException(429, 'Cockpit AP查询并发已满，请稍后重试')
        try:
            with self._opener.open(request, timeout=self.config.timeout) as response:
                raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise HTTPException(502, 'AP响应过大，请缩小查询范围')
            body = json.loads(raw)
            if not isinstance(body, dict) or body.get('success') is not True or body.get('data') is None:
                raise HTTPException(502, 'AP未返回成功的数据结果，请检查查询口径及AP认证')
            if kind == 'batch':
                if not isinstance(body['data'], list) or len(body['data']) != len(payload) or any(not isinstance(v, dict) or v.get('success') is not True or v.get('data') is None for v in body['data']):
                    raise HTTPException(502, 'AP批量查询不完整或包含失败子查询')
            return body['data']
        except HTTPError as exc:
            if exc.code in {401, 403, 301, 302, 303, 307, 308}:
                raise HTTPException(502, 'AP认证失效或权限不足，请更新Cockpit独立认证') from None
            raise HTTPException(502, 'AP请求失败；未切换到本体、数据库或旧快照') from None
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
