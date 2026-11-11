"""Bounded, redacted backend-only failure records. Never change query semantics."""
from contextlib import contextmanager
from contextvars import ContextVar
import json
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import re
import time
import uuid

from bi_agent.tool_runtime import sanitize_error_message

_scope = ContextVar('cockpit_diagnostic_scope', default={})


@contextmanager
def diagnostic_scope(**values):
    token = _scope.set({**_scope.get(), **values})
    try:
        yield
    finally:
        _scope.reset(token)


def current_scope():
    return dict(_scope.get())


def redact(message):
    text = str(message or '')
    text = re.sub(r'(?i)(https?://|postgres(?:ql)?://)[^\s/@]+:[^\s/@]+@', r'\1[REDACTED]@', text)
    secrets = [v for k,v in os.environ.items() if len(v)>=4 and any(t in k.upper() for t in ('PASSWORD','SECRET','TOKEN','API_KEY','AUTHORIZATION','COOKIE'))]
    try:
        path=Path(os.getenv('COCKPIT_AP_HEADERS_FILE',''))
        if path.is_file() and path.stat().st_size<=65536:
            headers=json.loads(path.read_text())
            if isinstance(headers,dict):secrets.extend(v for k,v in headers.items() if isinstance(v,str) and len(v)>=4 and k.lower() not in {'accept','content-type','x-ontology-repository-id'})
    except (OSError,ValueError):
        pass
    for secret in sorted(secrets,key=len,reverse=True):text=text.replace(secret,'[REDACTED]')
    text=re.sub(r'(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+', 'Bearer [REDACTED]', text)
    text = re.sub(r'''(?i)(["']?(?:cookie|authorization|password|api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|apifoxToken)["']?\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,;]+)''', r'\1[REDACTED]', text)
    text=re.sub(r'\bsk-[A-Za-z0-9_-]{12,}', '[REDACTED]', text)
    text=sanitize_error_message(text,limit=max(1600,len(text)))
    return text if len(text)<=1600 else text[:1000]+' ...[truncated]... '+text[-550:]


class AnalysisFailure(RuntimeError):
    def __init__(self, message, *, phase='main_service', code='MAIN_SERVICE_ERROR', last_tool=''):
        super().__init__('Main service analysis failed; inspect backend diagnostics')
        self.original_message=redact(message)
        self.phase=phase
        self.code=code
        self.last_tool=last_tool


def record_failure(store, exc, *, phase, identity=1, stage='', analysis_id='', run_id='', duration=0, query_hash=''):
    scope=current_scope()
    detail=getattr(exc,'diagnostic_message',None) or getattr(exc,'original_message',None) or getattr(exc,'detail',None) or str(exc)
    if not isinstance(detail,str):detail=json.dumps(detail,ensure_ascii=False,default=str)
    value=dict(diagnosticId=uuid.uuid4().hex,analysisId=analysis_id,runId=run_id or scope.get('runId',''),
        identity=int(identity),stage=stage or scope.get('stage',''),phase=getattr(exc,'phase',phase),
        errorCode=redact(str(getattr(exc,'code',getattr(exc,'status_code',type(exc).__name__))))[:120],
        errorType=type(exc).__name__,upstreamStatus=getattr(exc,'upstream_status',None),
        upstreamCode=redact(str(getattr(exc,'upstream_code','')))[:120] if getattr(exc,'upstream_code',None) is not None else None,message=redact(detail),lastTool=redact(getattr(exc,'last_tool',''))[:100] if getattr(exc,'last_tool','') else '',
        durationSeconds=round(float(duration),3),queryHash=query_hash,createdAt=time.time(),createdAtIso=datetime.now(timezone.utc).isoformat())
    try:
        store.save_diagnostic(value)
    except Exception:
        logging.getLogger(__name__).warning('cockpit_diagnostic persistence failed id=%s',value['diagnosticId'])
    logging.getLogger(__name__).warning('cockpit_diagnostic %s',json.dumps(value,ensure_ascii=False))
    return value


def record_query_failure(store, *, phase='database_query', query='', code='QUERY_FAILED',
                         message='', upstream_code='', duration_seconds=0, identity=1,
                         stage='', analysis_id='', run_id=''):
    """Persist one redacted query/model diagnostic and return its id.

    Query diagnostics intentionally keep the statement name, SQLSTATE and
    duration so an operator can distinguish a connection failure from a field
    error, timeout or row-limit condition.  The raw driver message is redacted;
    it is never returned by the public card API.
    """
    scope = current_scope()
    value = dict(
        diagnosticId=uuid.uuid4().hex,
        analysisId=analysis_id,
        runId=run_id or scope.get('runId', ''),
        identity=int(identity),
        stage=stage or scope.get('stage', ''),
        phase=str(phase or 'database_query')[:60],
        query=str(query or '')[:80],
        errorCode=redact(str(code or 'QUERY_FAILED'))[:120],
        errorType='QueryDiagnostic',
        upstreamStatus=None,
        upstreamCode=redact(str(upstream_code or ''))[:120] or None,
        message=redact(message or '')[:1600],
        lastTool='',
        durationSeconds=round(float(duration_seconds or 0), 3),
        queryHash='',
        createdAt=time.time(),
        createdAtIso=datetime.now(timezone.utc).isoformat(),
    )
    try:
        store.save_diagnostic(value)
    except Exception:
        logging.getLogger(__name__).warning('cockpit_query_diagnostic persistence failed id=%s', value['diagnosticId'])
    logging.getLogger(__name__).warning('cockpit_query_diagnostic %s', json.dumps(value, ensure_ascii=False))
    return value
