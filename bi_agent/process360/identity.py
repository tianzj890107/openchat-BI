"""Trusted caller identity for Process360 data access.

A host-supplied :class:`PrincipalScope` is deliberately separate from the
user-selected query ``Scope``.  The query scope narrows what the user wants to
see; the principal scope is an authorization boundary.  They are combined by
intersection only, so a caller can never widen its own data range by adding
filters.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .models import Scope, as_list


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
        allowed = set(aliases) | set(aliases.values()) | {"roles", "source"}
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
        )

    @classmethod
    def local(cls) -> "PrincipalScope":
        """Internal/test principal.  MCP callers must supply a host principal."""
        return cls(tenant_id="local", user_id="local", source="local", can_dispatch=True)

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
        }

    @property
    def key(self) -> str:
        return f"{self.tenant_id}:{self.user_id}"

    def merge_scope(self, scope: Scope) -> Scope:
        """Intersect user filters with the principal's allowed data range."""
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
        }


def require_principal(payload: Mapping[str, Any] | None, *, required: bool = True) -> PrincipalScope:
    return PrincipalScope.from_payload(payload, required=required)
