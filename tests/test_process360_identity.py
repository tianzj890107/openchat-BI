from __future__ import annotations

import pytest

from bi_agent.process360.identity import PrincipalScope
from bi_agent.process360.models import Scope


def test_principal_requires_tenant_and_user_and_intersects_scope() -> None:
    with pytest.raises(ValueError):
        PrincipalScope.from_payload({"tenantId": "t1"})
    principal = PrincipalScope.from_payload(
        {
            "tenantId": "t1",
            "userId": "u1",
            "customerIds": ["c1", "c2"],
            "ownerIds": ["u1"],
            "canDispatch": True,
        }
    )
    scope = principal.merge_scope(
        Scope.from_payload({"customerIds": ["c2", "c9"], "ownerIds": ["u1"]})
    )
    assert scope.customer_ids == ("c2",)
    assert scope.owner_ids == ("u1",)
    assert principal.key == "t1:u1"


def test_principal_scope_never_widens_an_empty_intersection() -> None:
    principal = PrincipalScope.from_payload(
        {"tenantId": "t1", "userId": "u1", "customerIds": ["c1"]}
    )
    with pytest.raises(ValueError, match="outside the principal"):
        principal.merge_scope(Scope.from_payload({"customerIds": ["c2"]}))


def test_principal_unrestricted_dimension_is_still_bounded_by_request() -> None:
    principal = PrincipalScope.from_payload({"tenantId": "t1", "userId": "u1"})
    scope = principal.merge_scope(Scope.from_payload({"productIds": ["p1"]}))
    assert scope.product_ids == ("p1",)


def test_empty_grant_is_not_unlimited() -> None:
    denied = PrincipalScope.from_payload(
        {"tenantId": "t1", "userId": "u1", "grantKind": "none"}
    )
    assert denied.can_read_data is False
    with pytest.raises(ValueError, match="no data grant"):
        denied.merge_scope(Scope.from_payload({}))

    ambiguous = PrincipalScope.from_payload(
        {"tenantId": "t1", "userId": "u1", "grantKind": "restricted"}
    )
    with pytest.raises(ValueError, match="at least one"):
        ambiguous.merge_scope(Scope.from_payload({}))

    full = PrincipalScope.from_payload(
        {"tenantId": "t1", "userId": "u1", "grantKind": "all"}
    )
    assert full.merge_scope(Scope.from_payload({"customerIds": ["c9"]})).customer_ids == ("c9",)


def test_poc_principal_comes_from_server_config(monkeypatch) -> None:
    monkeypatch.delenv("PROCESS360_POC_PRINCIPAL", raising=False)
    poc = PrincipalScope.poc()
    assert poc.grant_kind == "all"
    assert poc.source == "server-poc-config"
    assert poc.tenant_id and poc.user_id

    monkeypatch.setenv(
        "PROCESS360_POC_PRINCIPAL",
        '{"tenantId":"ywln","userId":"reader","grantKind":"restricted","customerIds":["c1"]}',
    )
    restricted = PrincipalScope.poc()
    assert restricted.grant_kind == "restricted"
    assert restricted.merge_scope(Scope.from_payload({})).customer_ids == ("c1",)
