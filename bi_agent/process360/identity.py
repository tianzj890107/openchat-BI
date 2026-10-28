"""Trusted caller identity for Process360 data access.

A host-supplied :class:`PrincipalScope` is deliberately separate from the
user-selected query ``Scope``.  The query scope narrows what the user wants to
see; the principal scope is an authorization boundary.  They are combined by
intersection only, so a caller can never widen its own data range by adding
filters.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .models import Scope, as_list

GRANT_KINDS = ("none", "restricted", "all")
DEFAULT_POC_PRINCIPAL = {
    "tenantId": "ywln",
    "userId": "poc-readonly",
    "grantKind": "all",
    "canDispatch": False,
    "source": "server-poc-config",
}

# The MCP runtime sets this for the duration of one tool call.  Business tools
# read the identity from here, never from model-supplied arguments.
_ACTIVE_PRINCIPAL: contextvars.ContextVar[Mapping[str, Any] | None] = contextvars.ContextVar(
    "process360_active_principal", default=None
)


def set_active_principal(payload: Mapping[str, Any] | None):
    return _ACTIVE_PRINCIPAL.set(dict(payload) if payload is not None else None)


def reset_active_principal(token: Any) -> None:
    _ACTIVE_PRINCIPAL.reset(token)


def active_principal_payload() -> Mapping[str, Any] | None:
    return _ACTIVE_PRINCIPAL.get()


def _strings(value: Any, *, field: str, maximum: int = 500) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)) or len(value) > maximum:
        raise ValueError(f"{field} must be an array of at most {maximum} values")
    items = [str(item).strip() for item in value]
    if any(not item for item in items):
        raise ValueError(f"{field} must contain non-empty values")
    return tuple(dict.fromkeys(items))


@dataclass(frozen=True)
class PrincipalScope:
    tenant_id: str
    user_id: str
    org_ids: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()
    customer_ids: tuple[str, ...] = ()
    owner_ids: tuple[str, ...] = ()
    product_ids: tuple[str, ...] = ()
    can_dispatch: bool = False
    source: str = "host"
    grant_kind: str = "restricted"
    authorization_version: str = ""

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None, *, required: bool = True) -> "PrincipalScope":
        if payload is None:
            if required:
                raise ValueError("principal is required for business data access")
            return cls.local()
        if not isinstance(payload, Mapping):
            raise ValueError("principal must be an object")
        raw = dict(payload)
        aliases = {
            "tenant_id": "tenantId",
            "user_id": "userId",
            "org_ids": "orgIds",
            "customer_ids": "customerIds",
            "owner_ids": "ownerIds",
            "product_ids": "productIds",
            "can_dispatch": "canDispatch",
        }
        allowed = set(aliases) | set(aliases.values()) | {
            "roles", "source", "grantKind", "grant_kind",
            "authorizationVersion", "authorization_version",
        }
        unknown = set(raw) - allowed
        if unknown:
            raise ValueError("principal contains unsupported fields")
        for key, alias in aliases.items():
            if key in raw and alias in raw and raw[key] != raw[alias]:
                raise ValueError(f"conflicting principal fields: {key}")
        tenant = str(raw.get("tenantId", raw.get("tenant_id", "")) or "").strip()
        user = str(raw.get("userId", raw.get("user_id", "")) or "").strip()
        if required and (not tenant or not user):
            raise ValueError("principal.tenantId and principal.userId are required")
        if len(tenant) > 200 or len(user) > 200:
            raise ValueError("principal identity is too long")
        dispatch = raw.get("canDispatch", raw.get("can_dispatch", False))
        if not isinstance(dispatch, bool):
            raise ValueError("principal.canDispatch must be a boolean")
        raw_grant = raw.get("grantKind", raw.get("grant_kind"))
        if raw_grant is None:
            raise ValueError("principal.grantKind is required")
        grant_kind = str(raw_grant).strip().lower()
        if grant_kind not in GRANT_KINDS:
            raise ValueError(f"principal.grantKind must be one of {GRANT_KINDS}")
        authorization_version = str(
            raw.get("authorizationVersion", raw.get("authorization_version", "")) or ""
        ).strip()
        if len(authorization_version) > 200:
            raise ValueError("principal.authorizationVersion is too long")
        return cls(
            tenant_id=tenant,
            user_id=user,
            org_ids=_strings(raw.get("orgIds", raw.get("org_ids")), field="orgIds"),
            roles=_strings(raw.get("roles"), field="roles", maximum=50),
            customer_ids=_strings(raw.get("customerIds", raw.get("customer_ids")), field="customerIds"),
            owner_ids=_strings(raw.get("ownerIds", raw.get("owner_ids")), field="ownerIds"),
            product_ids=_strings(raw.get("productIds", raw.get("product_ids")), field="productIds"),
            can_dispatch=dispatch,
            source=str(raw.get("source") or "host")[:40],
            grant_kind=grant_kind,
            authorization_version=authorization_version,
        )

    @classmethod
    def poc(cls) -> "PrincipalScope":
        """Server-configured POC identity.

        The model never supplies this.  It defaults to a read-only, full-scope
        POC principal and can be overridden by ``PROCESS360_POC_PRINCIPAL``.
        """
        raw = os.environ.get("PROCESS360_POC_PRINCIPAL")
        payload: dict[str, Any] = dict(DEFAULT_POC_PRINCIPAL)
        explicit_dispatch = False
        if raw and raw.strip():
            try:
                parsed = json.loads(raw)
            except ValueError as exc:
                raise ValueError("PROCESS360_POC_PRINCIPAL must be valid JSON") from exc
            if not isinstance(parsed, dict):
                raise ValueError("PROCESS360_POC_PRINCIPAL must be a JSON object")
            explicit_dispatch = "canDispatch" in parsed or "can_dispatch" in parsed
            payload.update(parsed)
        dispatch_raw = (os.environ.get("PROCESS360_POC_DISPATCH") or "").strip().lower()
        if not explicit_dispatch:
            payload["canDispatch"] = dispatch_raw in {"1", "true", "yes", "on"}
        return cls.from_payload(payload)

    @classmethod
    def local(cls) -> "PrincipalScope":
        """Internal/test principal.  Never resolves from model-supplied input."""
        return cls(
            tenant_id="local",
            user_id="local",
            source="local",
            can_dispatch=True,
            grant_kind="all",
            authorization_version="local",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenantId": self.tenant_id,
            "userId": self.user_id,
            "orgIds": list(self.org_ids),
            "roles": list(self.roles),
            "customerIds": list(self.customer_ids),
            "ownerIds": list(self.owner_ids),
            "productIds": list(self.product_ids),
            "canDispatch": self.can_dispatch,
            "source": self.source,
            "grantKind": self.grant_kind,
            "authorizationVersion": self.authorization_version,
        }

    @property
    def key(self) -> str:
        return f"{self.tenant_id}:{self.user_id}"

    @property
    def can_read_data(self) -> bool:
        return self.grant_kind in {"restricted", "all"}

    def grant_scope(self) -> dict[str, Any]:
        return {
            "tenantId": self.tenant_id,
            "userId": self.user_id,
            "orgIds": list(self.org_ids),
            "roles": list(self.roles),
            "customerIds": list(self.customer_ids),
            "ownerIds": list(self.owner_ids),
            "productIds": list(self.product_ids),
            "grantKind": self.grant_kind,
        }

    @property
    def grant_fingerprint(self) -> str:
        payload = self.grant_scope()
        payload["authorizationVersion"] = self.effective_authorization_version
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @property
    def effective_authorization_version(self) -> str:
        if self.authorization_version:
            return self.authorization_version
        payload = self.grant_scope()
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return "grant-" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]

    def merge_scope(self, scope: Scope) -> Scope:
        """Intersect user filters with the principal's allowed data range.

        Empty allowances never mean "unlimited": a ``restricted`` grant must
        name at least one dimension, and ``all`` must be granted explicitly.
        """
        if self.grant_kind == "none":
            raise ValueError("principal has no data grant")
        if self.grant_kind == "all":
            return scope
        if not any((self.customer_ids, self.owner_ids, self.product_ids)):
            raise ValueError(
                "restricted principal grant must name at least one customer/owner/product"
            )

        def narrow(requested: tuple[str, ...], allowed: tuple[str, ...]) -> tuple[str, ...]:
            if not allowed:
                return requested
            if not requested:
                return allowed
            overlap = tuple(value for value in requested if value in set(allowed))
            if not overlap:
                raise ValueError("requested scope is outside the principal data grant")
            return overlap

        return Scope(
            as_of=scope.as_of,
            period_start=scope.period_start,
            period_end=scope.period_end,
            customer_ids=narrow(scope.customer_ids, self.customer_ids),
            owner_ids=narrow(scope.owner_ids, self.owner_ids),
            product_ids=narrow(scope.product_ids, self.product_ids),
            limit=scope.limit,
            include_current_snapshot=scope.include_current_snapshot,
        )

    def fingerprint(self) -> dict[str, Any]:
        return {
            "tenantId": self.tenant_id,
            "userId": self.user_id,
            "orgIds": list(self.org_ids),
            "roles": list(self.roles),
            "canDispatch": self.can_dispatch,
            "grantKind": self.grant_kind,
            "source": self.source,
            "authorizationVersion": self.effective_authorization_version,
        }


def require_principal(payload: Mapping[str, Any] | None, *, required: bool = True) -> PrincipalScope:
    return PrincipalScope.from_payload(payload, required=required)
