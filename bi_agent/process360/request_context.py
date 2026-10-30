"""Trusted request context shared by MCP, Canvas and HTTP entry points.

Identity, authorization and tracing fields are resolved by the server.  They
are deliberately kept in one context object so a query, analysis, draft and
dispatch in the same user request cannot accidentally use different principals.
"""

from __future__ import annotations

import contextvars
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

from .identity import PrincipalScope, set_active_principal, reset_active_principal

SURFACES = frozenset({"mcp", "canvas", "web", "service", "internal"})
FORBIDDEN_CLIENT_FIELDS = frozenset(
    {
        "principal", "principalScope", "__principal", "tenantId", "userId",
        "grantKind", "grantScope", "authorizationVersion", "canDispatch",
    }
)


@dataclass(frozen=True)
class RequestContext:
    principal: PrincipalScope
    authorization_version: str
    conversation_id: str
    request_id: str
    surface: str

    @property
    def principal_id(self) -> str:
        return self.principal.user_id

    @property
    def tenant_id(self) -> str:
        return self.principal.tenant_id

    @property
    def grant_kind(self) -> str:
        return self.principal.grant_kind

    @property
    def grant_scope(self) -> dict[str, Any]:
        return self.principal.grant_scope()

    @property
    def grant_fingerprint(self) -> str:
        return self.principal.grant_fingerprint

    @property
    def key(self) -> str:
        return self.principal.key

    @property
    def can_dispatch(self) -> bool:
        return self.principal.can_dispatch

    def to_dict(self) -> dict[str, Any]:
        return {
            "principalId": self.principal_id,
            "tenantId": self.tenant_id,
            "grantKind": self.grant_kind,
            "grantScope": self.grant_scope,
            "authorizationVersion": self.authorization_version,
            "conversationId": self.conversation_id,
            "requestId": self.request_id,
            "surface": self.surface,
        }

    def fingerprint(self) -> dict[str, Any]:
        return {
            **self.principal.fingerprint(),
            "conversationId": self.conversation_id,
            "requestId": self.request_id,
            "surface": self.surface,
        }


_ACTIVE_CONTEXT: contextvars.ContextVar[RequestContext | None] = contextvars.ContextVar(
    "process360_request_context", default=None
)


def _bound(value: Any, field: str, *, maximum: int = 300, required: bool = False) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise ValueError(f"{field} is required")
    if len(text) > maximum:
        raise ValueError(f"{field} is too long")
    return text


def resolve_request_context(
    *,
    principal: Mapping[str, Any] | PrincipalScope | None = None,
    conversation_id: str = "",
    request_id: str = "",
    surface: str = "web",
    required: bool = True,
) -> RequestContext:
    normalized_surface = _bound(surface, "surface", maximum=32, required=True).lower()
    if normalized_surface not in SURFACES:
        raise ValueError("surface must be mcp, canvas, web, service or internal")
    request = _bound(request_id, "requestId", maximum=300, required=True)
    conversation = _bound(conversation_id, "conversationId")
    if isinstance(principal, PrincipalScope):
        identity = principal
    else:
        identity = PrincipalScope.from_payload(principal, required=required)
    return RequestContext(
        principal=identity,
        authorization_version=identity.effective_authorization_version,
        conversation_id=conversation,
        request_id=request,
        surface=normalized_surface,
    )


def set_request_context(context: RequestContext):
    principal_token = set_active_principal(context.principal.to_dict())
    context_token = _ACTIVE_CONTEXT.set(context)
    return context_token, principal_token


def reset_request_context(tokens: Any) -> None:
    context_token, principal_token = tokens
    _ACTIVE_CONTEXT.reset(context_token)
    reset_active_principal(principal_token)


def active_request_context() -> RequestContext | None:
    return _ACTIVE_CONTEXT.get()


def current_or_resolve(
    *,
    principal: Mapping[str, Any] | PrincipalScope | None = None,
    conversation_id: str = "",
    request_id: str = "",
    surface: str = "service",
) -> RequestContext:
    active = active_request_context()
    if active is not None:
        return active
    return resolve_request_context(
        principal=principal,
        conversation_id=conversation_id,
        request_id=request_id or uuid.uuid4().hex,
        surface=surface,
    )


def reject_client_identity_fields(payload: Mapping[str, Any] | None) -> None:
    unknown = set(payload or {}) & FORBIDDEN_CLIENT_FIELDS
    if unknown:
        raise ValueError(
            "身份、授权和执行上下文由服务端解析；调用方不得提交 "
            + ", ".join(sorted(unknown))
        )
