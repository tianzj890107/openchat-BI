"""Durable Process360 runtime records.

The business database is read-only.  Drafts, frozen runs, executions,
idempotency keys, approvals and receipts therefore live in a separate local
SQLite database.  The POC default is ``dataset/process360/runtime.sqlite3``;
``PROCESS360_STORE_PATH`` can point at an exported/copied database for
migration.  Nothing in this module writes the customer PostgreSQL database.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _load(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    return json.loads(str(value))


def _now() -> float:
    return time.time()


class Process360Store:
    """Small, append-preserving SQLite store for the Process360 POC."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS runs (
      id TEXT PRIMARY KEY,
      scenario TEXT NOT NULL,
      tenant TEXT NOT NULL DEFAULT '',
      principal TEXT NOT NULL DEFAULT '',
      payload TEXT NOT NULL,
      payload_hash TEXT NOT NULL,
      created_at REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS requests (
      id TEXT PRIMARY KEY,
      surface TEXT NOT NULL DEFAULT '',
      tenant TEXT NOT NULL DEFAULT '',
      principal TEXT NOT NULL DEFAULT '',
      conversation_id TEXT NOT NULL DEFAULT '',
      authorization_version TEXT NOT NULL DEFAULT '',
      created_at REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS steps (
      id TEXT PRIMARY KEY,
      request_id TEXT NOT NULL,
      scenario TEXT NOT NULL DEFAULT '',
      tool TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT '',
      input_hash TEXT NOT NULL DEFAULT '',
      duration_ms INTEGER NOT NULL DEFAULT 0,
      rows_returned INTEGER NOT NULL DEFAULT 0,
      refs TEXT NOT NULL DEFAULT '{}',
      created_at REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS steps_request ON steps(request_id, created_at);
    CREATE TABLE IF NOT EXISTS queries (
      id TEXT PRIMARY KEY,
      scenario TEXT NOT NULL,
      tenant TEXT NOT NULL DEFAULT '',
      principal TEXT NOT NULL DEFAULT '',
      scope TEXT NOT NULL,
      query_hash TEXT NOT NULL,
      catalog_version TEXT NOT NULL DEFAULT '',
      catalog_hash TEXT NOT NULL DEFAULT '',
      authorization_version TEXT NOT NULL DEFAULT '',
      grant_fingerprint TEXT NOT NULL DEFAULT '',
      source_connection TEXT NOT NULL DEFAULT '',
      template_version TEXT NOT NULL DEFAULT '',
      result_hash TEXT NOT NULL DEFAULT '',
      complete INTEGER NOT NULL DEFAULT 0,
      full_count INTEGER NOT NULL DEFAULT 0,
      expires_at REAL NOT NULL DEFAULT 0,
      full_rows TEXT NOT NULL DEFAULT '[]',
      contract_version TEXT NOT NULL DEFAULT 'legacy',
      payload TEXT NOT NULL,
      created_at REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS queries_scope ON queries(scenario, tenant, principal, created_at);
    CREATE TABLE IF NOT EXISTS drafts (
      id TEXT PRIMARY KEY,
      run_id TEXT NOT NULL DEFAULT '',
      scenario TEXT NOT NULL,
      tenant TEXT NOT NULL DEFAULT '',
      principal TEXT NOT NULL DEFAULT '',
      payload TEXT NOT NULL,
      payload_hash TEXT NOT NULL,
      approval_status TEXT NOT NULL DEFAULT 'pending',
      created_at REAL NOT NULL,
      expires_at REAL NOT NULL,
      consumed_at REAL,
      consumed_by TEXT
    );
    CREATE TABLE IF NOT EXISTS actions (
      draft_id TEXT NOT NULL,
      action_id TEXT NOT NULL,
      payload TEXT NOT NULL,
      PRIMARY KEY (draft_id, action_id)
    );
    CREATE TABLE IF NOT EXISTS action_consumptions (
      draft_id TEXT NOT NULL,
      action_id TEXT NOT NULL,
      consumed_by TEXT NOT NULL DEFAULT '',
      consumed_at REAL NOT NULL,
      PRIMARY KEY (draft_id, action_id)
    );
    CREATE TABLE IF NOT EXISTS executions (
      id TEXT PRIMARY KEY,
      draft_id TEXT NOT NULL,
      action_id TEXT NOT NULL,
      idempotency_key TEXT NOT NULL UNIQUE,
      source_todo_id TEXT NOT NULL,
      status TEXT NOT NULL,
      tenant TEXT NOT NULL DEFAULT '',
      principal TEXT NOT NULL DEFAULT '',
      request_id TEXT NOT NULL DEFAULT '',
      authorization_version TEXT NOT NULL DEFAULT '',
      recipient_hash TEXT NOT NULL DEFAULT '',
      request TEXT,
      response TEXT,
      created_at REAL NOT NULL,
      updated_at REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS executions_draft ON executions(draft_id, action_id);
    CREATE TABLE IF NOT EXISTS receipts (
      source_todo_id TEXT PRIMARY KEY,
      status TEXT NOT NULL,
      payload TEXT NOT NULL,
      updated_at REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS plans (
      id TEXT PRIMARY KEY,
      payload TEXT NOT NULL,
      status TEXT NOT NULL,
      created_at REAL NOT NULL,
      updated_at REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS plan_step_runs (
      id TEXT PRIMARY KEY,
      plan_id TEXT NOT NULL,
      step_id TEXT NOT NULL,
      request_id TEXT NOT NULL DEFAULT '',
      tool TEXT NOT NULL,
      status TEXT NOT NULL,
      input_hash TEXT NOT NULL DEFAULT '',
      refs TEXT NOT NULL DEFAULT '{}',
      created_at REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS plan_step_runs_plan
      ON plan_step_runs(plan_id, step_id, created_at);
    CREATE TABLE IF NOT EXISTS exploration_calls (
      id TEXT PRIMARY KEY,
      plan_id TEXT NOT NULL,
      step_id TEXT NOT NULL,
      tool TEXT NOT NULL,
      request_hash TEXT NOT NULL,
      status TEXT NOT NULL,
      output TEXT,
      rows_returned INTEGER NOT NULL DEFAULT 0,
      elapsed_ms INTEGER NOT NULL DEFAULT 0,
      created_at REAL NOT NULL,
      UNIQUE(plan_id, step_id, request_hash)
    );
    CREATE INDEX IF NOT EXISTS exploration_plan ON exploration_calls(plan_id, created_at);
    CREATE TABLE IF NOT EXISTS evidence (
      id TEXT PRIMARY KEY,
      run_id TEXT NOT NULL DEFAULT '',
      template_code TEXT NOT NULL,
      payload TEXT NOT NULL,
      payload_hash TEXT NOT NULL,
      status TEXT NOT NULL,
      created_at REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS evidence_run ON evidence(run_id, template_code);
    CREATE TABLE IF NOT EXISTS approvals (
      id TEXT PRIMARY KEY,
      draft_id TEXT NOT NULL,
      status TEXT NOT NULL,
      approver TEXT NOT NULL DEFAULT '',
      note TEXT NOT NULL DEFAULT '',
      payload TEXT,
      created_at REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS trusted_approvals (
      id TEXT PRIMARY KEY,
      tenant TEXT NOT NULL,
      scenario TEXT NOT NULL DEFAULT '',
      status TEXT NOT NULL,
      target REAL,
      direction TEXT NOT NULL DEFAULT '>=',
      minimum_denominator INTEGER NOT NULL DEFAULT 1,
      valid_from REAL NOT NULL DEFAULT 0,
      valid_until REAL NOT NULL DEFAULT 0,
      payload TEXT NOT NULL DEFAULT '{}',
      created_at REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS trusted_approvals_scope
      ON trusted_approvals(tenant, scenario, status, created_at);
    CREATE TABLE IF NOT EXISTS artifacts (
      id TEXT PRIMARY KEY,
      artifact_hash TEXT NOT NULL,
      request_id TEXT NOT NULL DEFAULT '',
      plan_id TEXT NOT NULL DEFAULT '',
      query_id TEXT NOT NULL DEFAULT '',
      run_id TEXT NOT NULL DEFAULT '',
      tenant TEXT NOT NULL DEFAULT '',
      principal TEXT NOT NULL DEFAULT '',
      gate_result TEXT NOT NULL DEFAULT '{}',
      checked_at REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS artifacts_request ON artifacts(request_id, checked_at);
    """

    def __init__(self, path: str | Path | None = None) -> None:
        configured = (os.environ.get("PROCESS360_STORE_PATH") or "").strip()
        self.path = Path(path or configured or Path.cwd() / "dataset" / "process360" / "runtime.sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(self.SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """Incremental, append-preserving migrations for existing POC stores."""
        additions = {
            "requests": {
                "conversation_id": "TEXT NOT NULL DEFAULT ''",
                "authorization_version": "TEXT NOT NULL DEFAULT ''",
            },
            "queries": {
                "catalog_hash": "TEXT NOT NULL DEFAULT ''",
                "authorization_version": "TEXT NOT NULL DEFAULT ''",
                "grant_fingerprint": "TEXT NOT NULL DEFAULT ''",
                "source_connection": "TEXT NOT NULL DEFAULT ''",
                "template_version": "TEXT NOT NULL DEFAULT ''",
                "result_hash": "TEXT NOT NULL DEFAULT ''",
                "complete": "INTEGER NOT NULL DEFAULT 0",
                "full_count": "INTEGER NOT NULL DEFAULT 0",
                "expires_at": "REAL NOT NULL DEFAULT 0",
                "full_rows": "TEXT NOT NULL DEFAULT '[]'",
                "contract_version": "TEXT NOT NULL DEFAULT 'legacy'",
            },
            "executions": {
                "tenant": "TEXT NOT NULL DEFAULT ''",
                "principal": "TEXT NOT NULL DEFAULT ''",
                "request_id": "TEXT NOT NULL DEFAULT ''",
                "authorization_version": "TEXT NOT NULL DEFAULT ''",
                "recipient_hash": "TEXT NOT NULL DEFAULT ''",
            },
        }
        with self._connect() as db:
            for table, columns in additions.items():
                existing = {
                    str(row["name"])
                    for row in db.execute(f"PRAGMA table_info({table})").fetchall()
                }
                for name, declaration in columns.items():
                    if name not in existing:
                        db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(str(self.path), timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA busy_timeout=15000")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # -- runs -------------------------------------------------------------
    def save_run(
        self,
        *,
        scenario: str,
        payload: Mapping[str, Any],
        tenant: str = "",
        principal: str = "",
        run_id: str = "",
    ) -> dict[str, Any]:
        record_id = str(run_id or uuid.uuid4().hex)
        payload_hash = digest(payload)
        with self._connect() as db:
            db.execute(
                "INSERT INTO runs(id,scenario,tenant,principal,payload,payload_hash,created_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (record_id, str(scenario).upper(), tenant, principal, _json(payload), payload_hash, _now()),
            )
        return {"id": record_id, "hash": payload_hash, "scenario": str(scenario).upper()}

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (str(run_id or ""),)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["payload"] = _load(result.get("payload"))
        return result

    # -- request trail ----------------------------------------------------
    def ensure_request(
        self,
        request_id: str,
        *,
        surface: str = "",
        tenant: str = "",
        principal: str = "",
        conversation_id: str = "",
        authorization_version: str = "",
    ) -> str:
        record_id = str(request_id or uuid.uuid4().hex)
        with self._connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO requests(id,surface,tenant,principal,conversation_id,authorization_version,created_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (
                    record_id, str(surface), str(tenant), str(principal),
                    str(conversation_id), str(authorization_version), _now(),
                ),
            )
        return record_id

    def save_step(
        self,
        *,
        request_id: str,
        tool: str,
        status: str = "",
        scenario: str = "",
        input_hash: str = "",
        duration_ms: int = 0,
        rows_returned: int = 0,
        refs: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        record_id = uuid.uuid4().hex
        with self._connect() as db:
            db.execute(
                "INSERT INTO steps(id,request_id,scenario,tool,status,input_hash,duration_ms,rows_returned,refs,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    record_id, str(request_id), str(scenario).upper(), str(tool), str(status),
                    str(input_hash), int(duration_ms), int(rows_returned), _json(dict(refs or {})), _now(),
                ),
            )
        return {"id": record_id, "requestId": str(request_id)}

    def get_request(
        self, request_id: str, *, tenant: str = "", principal: str = ""
    ) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM requests WHERE id=?", (str(request_id or ""),)).fetchone()
            if row and tenant and str(row["tenant"]) != str(tenant):
                row = None
            if row and principal and str(row["principal"]) != str(principal):
                row = None
            if not row:
                return None
            steps = db.execute(
                "SELECT * FROM steps WHERE request_id=? ORDER BY created_at", (str(request_id),)
            ).fetchall()
        result = dict(row)
        result["steps"] = [
            {**dict(item), "refs": _load(dict(item).get("refs"))} for item in steps
        ]
        return result

    # -- queries ----------------------------------------------------------
    def save_query(
        self,
        *,
        scenario: str,
        scope: Mapping[str, Any],
        payload: Mapping[str, Any],
        tenant: str = "",
        principal: str = "",
        catalog_version: str = "",
        query_id: str = "",
        catalog_hash: str = "",
        authorization_version: str = "",
        grant_fingerprint: str = "",
        source_connection: str = "",
        template_version: str = "",
        result_hash: str = "",
        complete: bool = False,
        full_count: int = 0,
        expires_at: float = 0,
        full_rows: list[Mapping[str, Any]] | None = None,
        contract_version: str = "",
    ) -> dict[str, Any]:
        record_id = str(query_id or uuid.uuid4().hex)
        effective_contract = str(contract_version or "").strip() or (
            "process360.query.v2"
            if any(
                (
                    catalog_hash, authorization_version, grant_fingerprint,
                    source_connection, template_version, expires_at, full_rows,
                )
            )
            else "legacy"
        )
        with self._connect() as db:
            db.execute(
                "INSERT INTO queries(id,scenario,tenant,principal,scope,query_hash,catalog_version,"
                "catalog_hash,authorization_version,grant_fingerprint,source_connection,template_version,"
                "result_hash,complete,full_count,expires_at,full_rows,contract_version,payload,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    record_id,
                    str(scenario).upper(),
                    tenant,
                    principal,
                    _json(dict(scope)),
                    digest({"scenario": str(scenario).upper(), "scope": dict(scope)}),
                    catalog_version,
                    catalog_hash,
                    authorization_version,
                    grant_fingerprint,
                    source_connection,
                    template_version,
                    result_hash or digest(payload),
                    1 if complete else 0,
                    int(full_count or 0),
                    float(expires_at or 0),
                    _json(list(full_rows or [])),
                    effective_contract,
                    _json(dict(payload)),
                    _now(),
                ),
            )
        return {"id": record_id}

    def get_query(self, query_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM queries WHERE id=?", (str(query_id or ""),)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["payload"] = _load(result.get("payload"))
        result["scope"] = _load(result.get("scope"))
        result["full_rows"] = _load(result.get("full_rows")) or []
        result["complete"] = bool(result.get("complete"))
        return result

    # -- drafts -----------------------------------------------------------
    def save_draft(
        self,
        *,
        payload: Mapping[str, Any],
        scenario: str,
        run_id: str = "",
        tenant: str = "",
        principal: str = "",
        approval_status: str = "pending",
        ttl_seconds: int = 7 * 86400,
        draft_id: str = "",
    ) -> dict[str, Any]:
        record_id = str(draft_id or uuid.uuid4().hex)
        payload_hash = digest(payload)
        created = _now()
        expires = created + max(60, int(ttl_seconds))
        with self._connect() as db:
            db.execute(
                "INSERT INTO drafts(id,run_id,scenario,tenant,principal,payload,payload_hash,approval_status,created_at,expires_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (record_id, run_id, str(scenario).upper(), tenant, principal, _json(payload), payload_hash, approval_status, created, expires),
            )
            for action in list(payload.get("canvasActions") or []):
                action_id = str(action.get("id") or "").strip()
                if action_id:
                    db.execute(
                        "INSERT OR REPLACE INTO actions(draft_id,action_id,payload) VALUES(?,?,?)",
                        (record_id, action_id, _json(action)),
                    )
        return {
            "id": record_id,
            "hash": payload_hash,
            "expiresAt": expires,
            "approvalStatus": approval_status,
        }

    def get_draft(self, draft_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM drafts WHERE id=?", (str(draft_id or ""),)).fetchone()
            actions = db.execute("SELECT action_id,payload FROM actions WHERE draft_id=?", (str(draft_id or ""),)).fetchall() if row else []
        if not row:
            return None
        result = dict(row)
        result["payload"] = _load(result.get("payload"))
        result["actions"] = {item["action_id"]: _load(item["payload"]) for item in actions}
        result["expired"] = bool(result.get("expires_at")) and float(result["expires_at"]) <= _now()
        result["consumed"] = result.get("consumed_at") is not None
        return result

    def consume_draft(self, draft_id: str, *, consumed_by: str = "") -> bool:
        with self._connect() as db:
            cursor = db.execute(
                "UPDATE drafts SET consumed_at=?, consumed_by=? WHERE id=? AND consumed_at IS NULL AND expires_at>?",
                (_now(), consumed_by, str(draft_id or ""), _now()),
            )
            return cursor.rowcount == 1

    def consume_action(self, draft_id: str, action_id: str, *, consumed_by: str = "") -> bool:
        """Consume one action exactly once; other actions in the draft stay usable."""
        now = _now()
        with self._connect() as db:
            draft = db.execute(
                "SELECT expires_at, consumed_at FROM drafts WHERE id=?", (str(draft_id or ""),)
            ).fetchone()
            if not draft or draft["consumed_at"] is not None or float(draft["expires_at"]) <= now:
                return False
            try:
                db.execute(
                    "INSERT INTO action_consumptions(draft_id,action_id,consumed_by,consumed_at) "
                    "VALUES(?,?,?,?)",
                    (str(draft_id or ""), str(action_id or ""), consumed_by, now),
                )
            except sqlite3.IntegrityError:
                return False
            return True

    def get_action_consumption(self, draft_id: str, action_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM action_consumptions WHERE draft_id=? AND action_id=?",
                (str(draft_id or ""), str(action_id or "")),
            ).fetchone()
        return dict(row) if row else None

    def set_approval(self, draft_id: str, *, status: str, approver: str = "", note: str = "") -> dict[str, Any]:
        record_id = uuid.uuid4().hex
        with self._connect() as db:
            db.execute(
                "INSERT INTO approvals(id,draft_id,status,approver,note,payload,created_at) VALUES(?,?,?,?,?,?,?)",
                (record_id, str(draft_id or ""), str(status).upper(), approver, note, None, _now()),
            )
            db.execute("UPDATE drafts SET approval_status=? WHERE id=?", (str(status).upper(), str(draft_id or "")))
        return {"id": record_id, "draftId": draft_id, "status": str(status).upper(), "approver": approver, "note": note}

    def get_approval(self, draft_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM approvals WHERE draft_id=? ORDER BY created_at DESC LIMIT 1",
                (str(draft_id or ""),),
            ).fetchone()
        return dict(row) if row else None

    def save_trusted_approval(
        self,
        *,
        tenant: str,
        scenario: str,
        status: str,
        target: float | None,
        direction: str,
        minimum_denominator: int,
        valid_from: Any,
        valid_until: Any,
        payload: Mapping[str, Any] | None = None,
        approval_id: str = "",
    ) -> dict[str, Any]:
        from datetime import datetime

        def epoch(value: Any) -> float:
            if isinstance(value, (int, float)):
                return float(value)
            text = str(value or "").strip().replace("Z", "+00:00")
            return datetime.fromisoformat(text).timestamp() if text else 0.0

        record_id = str(approval_id or uuid.uuid4().hex)
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO trusted_approvals(id,tenant,scenario,status,target,direction,minimum_denominator,valid_from,valid_until,payload,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    record_id, str(tenant), str(scenario).upper(), str(status).lower(),
                    float(target) if target is not None else None, str(direction or ">="),
                    int(minimum_denominator or 1), epoch(valid_from), epoch(valid_until),
                    _json(payload or {}), _now(),
                ),
            )
        return self.get_trusted_approval(record_id) or {}

    def get_trusted_approval(self, approval_id: str, *, tenant: str = "") -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM trusted_approvals WHERE id=?",
                (str(approval_id or ""),),
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        if tenant and str(item.get("tenant") or "") != str(tenant):
            return None
        item["payload"] = _load(item.get("payload")) or {}
        return item

    # -- artifacts --------------------------------------------------------
    def save_artifact(
        self,
        *,
        artifact_id: str,
        artifact_hash: str,
        request_id: str,
        plan_id: str,
        query_id: str,
        run_id: str,
        tenant: str,
        principal: str,
        gate_result: Mapping[str, Any],
    ) -> dict[str, Any]:
        with self._connect() as db:
            db.execute(
                "INSERT INTO artifacts(id,artifact_hash,request_id,plan_id,query_id,run_id,tenant,principal,gate_result,checked_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    str(artifact_id), str(artifact_hash), str(request_id), str(plan_id),
                    str(query_id), str(run_id), str(tenant), str(principal),
                    _json(gate_result), _now(),
                ),
            )
        return self.get_artifact(artifact_id) or {}

    def get_artifact(self, artifact_id: str, *, tenant: str = "", principal: str = "") -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM artifacts WHERE id=?",
                (str(artifact_id or ""),),
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        if tenant and str(item.get("tenant") or "") != str(tenant):
            return None
        if principal and str(item.get("principal") or "") != str(principal):
            return None
        item["gate_result"] = _load(item.get("gate_result")) or {}
        return item

    # -- executions / idempotency ----------------------------------------
    def claim_execution(
        self,
        *,
        draft_id: str,
        action_id: str,
        idempotency_key: str,
        source_todo_id: str,
        consumed_by: str,
        tenant: str = "",
        principal: str = "",
        request_id: str = "",
        authorization_version: str = "",
        recipient_hash: str = "",
        request: Mapping[str, Any] | None = None,
    ) -> tuple[str, dict[str, Any] | None]:
        """Atomically claim one draft action and create its execution row.

        Outcomes: ``created``, ``existing`` or ``consumed``.  A concurrent click
        can never create two execution records or consume one action twice.
        """
        record_id = uuid.uuid4().hex
        now = _now()
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM executions WHERE idempotency_key=?",
                (str(idempotency_key),),
            ).fetchone()
            if row:
                return "existing", self._execution(row)
            consumed = db.execute(
                "SELECT * FROM action_consumptions WHERE draft_id=? AND action_id=?",
                (str(draft_id), str(action_id)),
            ).fetchone()
            if consumed:
                return "consumed", dict(consumed)
            try:
                db.execute(
                    "INSERT INTO executions(id,draft_id,action_id,idempotency_key,source_todo_id,status,tenant,principal,request_id,authorization_version,recipient_hash,request,response,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        record_id, str(draft_id), str(action_id), str(idempotency_key),
                        str(source_todo_id), "sending", str(tenant), str(principal),
                        str(request_id), str(authorization_version), str(recipient_hash),
                        _json(request or {}), None, now, now,
                    ),
                )
                db.execute(
                    "INSERT INTO action_consumptions(draft_id,action_id,consumed_by,consumed_at) "
                    "VALUES(?,?,?,?)",
                    (str(draft_id), str(action_id), str(consumed_by), now),
                )
            except sqlite3.IntegrityError:
                db.rollback()
                row = db.execute(
                    "SELECT * FROM executions WHERE idempotency_key=?",
                    (str(idempotency_key),),
                ).fetchone()
                if row:
                    return "existing", self._execution(row)
                consumed = db.execute(
                    "SELECT * FROM action_consumptions WHERE draft_id=? AND action_id=?",
                    (str(draft_id), str(action_id)),
                ).fetchone()
                if consumed:
                    return "consumed", dict(consumed)
                raise
        return "created", {
            "id": record_id,
            "draft_id": str(draft_id),
            "action_id": str(action_id),
            "idempotency_key": str(idempotency_key),
            "source_todo_id": str(source_todo_id),
            "status": "sending",
            "tenant": str(tenant),
            "principal": str(principal),
            "request_id": str(request_id),
            "authorization_version": str(authorization_version),
            "recipient_hash": str(recipient_hash),
            "request": dict(request or {}),
            "response": None,
        }

    def begin_execution(
        self,
        *,
        draft_id: str,
        action_id: str,
        idempotency_key: str,
        source_todo_id: str,
        request: Mapping[str, Any] | None = None,
    ) -> tuple[bool, dict[str, Any]]:
        record_id = uuid.uuid4().hex
        now = _now()
        with self._connect() as db:
            try:
                db.execute(
                    "INSERT INTO executions(id,draft_id,action_id,idempotency_key,source_todo_id,status,request,response,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (record_id, draft_id, action_id, idempotency_key, source_todo_id, "in_progress", _json(request or {}), None, now, now),
                )
                return True, {"id": record_id, "status": "in_progress", "sourceTodoId": source_todo_id}
            except sqlite3.IntegrityError:
                row = db.execute("SELECT * FROM executions WHERE idempotency_key=?", (idempotency_key,)).fetchone()
        if not row:
            raise RuntimeError("idempotency record disappeared")
        return False, self._execution(row)

    def finish_execution(self, execution_id: str, *, status: str, response: Mapping[str, Any] | None = None) -> dict[str, Any]:
        with self._connect() as db:
            db.execute(
                "UPDATE executions SET status=?,response=?,updated_at=? WHERE id=?",
                (str(status), _json(response or {}), _now(), str(execution_id)),
            )
            row = db.execute("SELECT * FROM executions WHERE id=?", (str(execution_id),)).fetchone()
        return self._execution(row) if row else {}

    def get_execution(self, idempotency_key: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM executions WHERE idempotency_key=?", (str(idempotency_key or ""),)).fetchone()
        return self._execution(row) if row else None

    def list_executions(self, *, draft_id: str = "", run_id: str = "") -> list[dict[str, Any]]:
        del run_id  # Runs are linked through drafts; keep the public shape explicit.
        with self._connect() as db:
            if draft_id:
                rows = db.execute("SELECT * FROM executions WHERE draft_id=? ORDER BY created_at", (draft_id,)).fetchall()
            else:
                rows = db.execute("SELECT * FROM executions ORDER BY created_at DESC LIMIT 200").fetchall()
        return [self._execution(row) for row in rows]

    def _execution(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        result["request"] = _load(result.get("request"))
        result["response"] = _load(result.get("response"))
        return result

    # -- receipts ---------------------------------------------------------
    def save_receipt(self, source_todo_id: str, *, status: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO receipts(source_todo_id,status,payload,updated_at) VALUES(?,?,?,?)",
                (str(source_todo_id or ""), str(status), _json(payload), _now()),
            )
        return {"sourceTodoId": str(source_todo_id or ""), "status": str(status), "payload": dict(payload)}

    def get_receipt(self, source_todo_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM receipts WHERE source_todo_id=?", (str(source_todo_id or ""),)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["payload"] = _load(result.get("payload"))
        return result

    # -- plans / evidence -------------------------------------------------
    def save_plan(self, payload: Mapping[str, Any], *, plan_id: str = "", status: str = "planned") -> dict[str, Any]:
        record_id = str(plan_id or uuid.uuid4().hex)
        now = _now()
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO plans(id,payload,status,created_at,updated_at) VALUES(?,?,?,?,?)",
                (record_id, _json(payload), str(status), now, now),
            )
        return {"id": record_id, "status": str(status)}

    def get_plan(self, plan_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM plans WHERE id=?", (str(plan_id or ""),)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["payload"] = _load(result.get("payload"))
        return result

    def record_plan_step(
        self,
        *,
        plan_id: str,
        step_id: str,
        request_id: str,
        tool: str,
        status: str,
        input_hash: str = "",
        refs: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        record_id = uuid.uuid4().hex
        with self._connect() as db:
            db.execute(
                "INSERT INTO plan_step_runs(id,plan_id,step_id,request_id,tool,status,input_hash,refs,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    record_id, str(plan_id), str(step_id), str(request_id), str(tool),
                    str(status), str(input_hash), _json(refs or {}), _now(),
                ),
            )
        return {
            "id": record_id,
            "planId": str(plan_id),
            "stepId": str(step_id),
            "requestId": str(request_id),
            "tool": str(tool),
            "status": str(status),
            "refs": dict(refs or {}),
        }

    def list_plan_steps(self, plan_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM plan_step_runs WHERE plan_id=? ORDER BY created_at",
                (str(plan_id or ""),),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["refs"] = _load(item.get("refs")) or {}
            result.append(item)
        return result

    def record_exploration(
        self,
        *,
        plan_id: str,
        step_id: str,
        tool: str,
        request_hash: str,
        status: str,
        output: Mapping[str, Any] | None = None,
        rows_returned: int = 0,
        elapsed_ms: int = 0,
    ) -> tuple[bool, dict[str, Any]]:
        record_id = uuid.uuid4().hex
        with self._connect() as db:
            try:
                db.execute(
                    "INSERT INTO exploration_calls(id,plan_id,step_id,tool,request_hash,status,output,rows_returned,elapsed_ms,created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        record_id, str(plan_id), str(step_id), str(tool), str(request_hash),
                        str(status), _json(output or {}), int(rows_returned), int(elapsed_ms), _now(),
                    ),
                )
                created = True
            except sqlite3.IntegrityError:
                row = db.execute(
                    "SELECT * FROM exploration_calls WHERE plan_id=? AND step_id=? AND request_hash=?",
                    (str(plan_id), str(step_id), str(request_hash)),
                ).fetchone()
                return False, self._exploration(row)
        return created, {
            "id": record_id,
            "planId": plan_id,
            "stepId": step_id,
            "tool": tool,
            "requestHash": request_hash,
            "status": status,
            "output": dict(output or {}),
            "rowsReturned": int(rows_returned),
            "elapsedMs": int(elapsed_ms),
        }

    def _exploration(self, row: sqlite3.Row | None) -> dict[str, Any]:
        if row is None:
            return {}
        result = dict(row)
        result["output"] = _load(result.get("output"))
        return result

    def list_exploration(self, plan_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM exploration_calls WHERE plan_id=? ORDER BY created_at",
                (str(plan_id or ""),),
            ).fetchall()
        return [self._exploration(row) for row in rows]

    def save_evidence(self, *, run_id: str, template_code: str, payload: Mapping[str, Any], status: str) -> dict[str, Any]:
        record_id = uuid.uuid4().hex
        with self._connect() as db:
            db.execute(
                "INSERT INTO evidence(id,run_id,template_code,payload,payload_hash,status,created_at) VALUES(?,?,?,?,?,?,?)",
                (record_id, str(run_id or ""), str(template_code), _json(payload), digest(payload), str(status), _now()),
            )
        return {"id": record_id, "runId": run_id, "templateCode": template_code, "status": status, "hash": digest(payload)}

    def list_evidence(self, run_id: str = "") -> list[dict[str, Any]]:
        with self._connect() as db:
            if run_id:
                rows = db.execute("SELECT * FROM evidence WHERE run_id=? ORDER BY created_at", (run_id,)).fetchall()
            else:
                rows = db.execute("SELECT * FROM evidence ORDER BY created_at DESC LIMIT 500").fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["payload"] = _load(item.get("payload"))
            result.append(item)
        return result

    # -- export -----------------------------------------------------------
    def export(self) -> dict[str, Any]:
        tables = (
            "runs", "drafts", "actions", "action_consumptions", "executions",
            "receipts", "plans", "plan_step_runs", "exploration_calls", "evidence",
            "approvals", "trusted_approvals", "artifacts",
        )
        payload: dict[str, Any] = {"schema": "process360.store.v1", "exportedAt": _now(), "tables": {}}
        with self._connect() as db:
            for table in tables:
                rows = db.execute(f"SELECT * FROM {table}").fetchall()
                payload["tables"][table] = [dict(row) for row in rows]
        return payload
