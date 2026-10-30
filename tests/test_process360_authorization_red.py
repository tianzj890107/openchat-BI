from __future__ import annotations

import pytest

from bi_agent.process360.identity import DEFAULT_POC_PRINCIPAL, PrincipalScope


def test_missing_grant_kind_is_rejected_instead_of_becoming_full_access() -> None:
    with pytest.raises(ValueError, match="grantKind"):
        PrincipalScope.from_payload({"tenantId": "t1", "userId": "u1"})
    with pytest.raises(ValueError, match="grantKind"):
        PrincipalScope.from_payload({"tenantId": "t1", "userId": "u1", "customerIds": ["c1"]})


def test_authorization_version_changes_the_effective_grant() -> None:
    first = PrincipalScope.from_payload(
        {"tenantId": "t1", "userId": "u1", "grantKind": "all", "authorizationVersion": "v1"}
    )
    second = PrincipalScope.from_payload(
        {"tenantId": "t1", "userId": "u1", "grantKind": "all", "authorizationVersion": "v2"}
    )
    assert first.effective_authorization_version == "v1"
    assert second.effective_authorization_version == "v2"
    assert first.grant_fingerprint != second.grant_fingerprint


def test_poc_read_access_and_dispatch_permission_are_separate(monkeypatch) -> None:
    monkeypatch.delenv("PROCESS360_POC_PRINCIPAL", raising=False)
    monkeypatch.delenv("PROCESS360_POC_DISPATCH", raising=False)
    poc = PrincipalScope.poc()
    assert poc.can_read_data is True
    assert poc.can_dispatch is False
    assert DEFAULT_POC_PRINCIPAL["grantKind"] == "all"

    monkeypatch.setenv("PROCESS360_POC_DISPATCH", "1")
    assert PrincipalScope.poc().can_dispatch is True
