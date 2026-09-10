"""Contract tests for the ontology repository allowlist (demo2 rollout).

RED group A of `docs/specs/ontology-repository-allowlist-and-single-draft-conversation.md`.

The allowlist must be applied at the single catalog choke point so the startup
validation, the `GET /api/sources` dropdown and the `PUT /api/sources` switch
all share it, and must stay backward compatible when the environment variable
is unset.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from bi_agent.web.app import (
    STATE,
    SourcesUpdate,
    _remote_repository_catalog,
    configure,
    get_sources_endpoint,
    put_sources_endpoint,
)

ALLOWLIST_ENV = "ONTOLOGY_ALLOWED_REPOSITORY_IDS"


class FakeRemote:
    """Manager stub exposing four repositories; demo2 only allows id 3."""

    base_url = "http://ontology.test"
    repository_id = "3"
    app_id = "app"
    auth_token = "token"
    namespace = "demo2"
    timeout = 10

    def __init__(self, repository_id: str = "3") -> None:
        self.repository_id = repository_id
        self.calls: list[int] = []

    def list_repositories(self, *, page: int, size: int):
        self.calls.append(page)
        if page != 1:
            return {"items": [], "total": 4}
        return {
            "items": [
                {"id": 1, "name": "库一", "namespaceCode": "one", "dorisDatabase": "ontology_one"},
                {"id": 3, "name": "ECore本体库-勿动", "namespaceCode": "demo2",
                 "dorisDatabase": "ontology_demometaerp"},
                {"id": 4, "name": "库四", "namespaceCode": "four", "dorisDatabase": "ontology_four"},
                {"id": 7, "name": "库七", "namespaceCode": "seven", "dorisDatabase": "ontology_seven"},
            ],
            "total": 4,
        }


class _FakeRegistry:
    def get(self, name):  # noqa: ANN001, ANN201
        return SimpleNamespace(name=name, tools=[])

    def list_names(self):  # noqa: ANN201
        return ["bi-analyst"]


class _AllowlistTestBase(unittest.TestCase):
    SOURCE_FIELDS = (
        "cwd", "ontology_store", "remote_ontology", "ontology_backend",
        "ontology_namespace", "doris_database", "doris_api_url", "use_doris",
        "remote_catalog_error", "remote_catalog_last_attempt",
        "agent_def", "conversation_store", "report_store",
    )

    def _snapshot_state(self) -> dict:
        return {name: getattr(STATE, name) for name in self.SOURCE_FIELDS}

    def _restore_state(self, snapshot: dict) -> None:
        for name, value in snapshot.items():
            setattr(STATE, name, value)

    def _source_state(self, temp_dir: str, remote: FakeRemote) -> dict:
        return {
            "cwd": temp_dir,
            "ontology_store": None,
            "remote_ontology": remote,
            "ontology_backend": "production",
            "ontology_namespace": "demo2",
            "doris_database": "ontology_demometaerp",
            "doris_api_url": "http://doris.test/query",
            "use_doris": True,
            "remote_catalog_error": "",
            "remote_catalog_last_attempt": 0.0,
        }


class RepositoryCatalogFilterTests(_AllowlistTestBase):
    def _catalog(self, env: dict) -> list[dict]:
        with patch.dict(os.environ, env, clear=False):
            if ALLOWLIST_ENV not in env:
                os.environ.pop(ALLOWLIST_ENV, None)
            return _remote_repository_catalog(FakeRemote())

    def test_catalog_without_allowlist_returns_every_accessible_repository(self) -> None:
        catalog = self._catalog({})
        self.assertEqual([repo["id"] for repo in catalog], ["1", "3", "4", "7"])

    def test_empty_allowlist_env_is_treated_as_unset(self) -> None:
        self.assertEqual([r["id"] for r in self._catalog({ALLOWLIST_ENV: ""})], ["1", "3", "4", "7"])
        self.assertEqual([r["id"] for r in self._catalog({ALLOWLIST_ENV: "  ,  "})], ["1", "3", "4", "7"])

    def test_single_allowlist_filters_catalog(self) -> None:
        catalog = self._catalog({ALLOWLIST_ENV: "3"})
        self.assertEqual([repo["id"] for repo in catalog], ["3"])
        self.assertEqual(catalog[0]["dorisDatabase"], "ontology_demometaerp")
        self.assertEqual(catalog[0]["namespace"], "demo2")
        self.assertEqual(catalog[0]["value"], "__metaerp_repository__:3")
        self.assertEqual(catalog[0]["databaseValue"], "__doris_repository__:3")

    def test_multi_value_allowlist_supports_commas_and_whitespace(self) -> None:
        self.assertEqual(
            [repo["id"] for repo in self._catalog({ALLOWLIST_ENV: " 3 , ,7 "})],
            ["3", "7"],
        )


class StartupValidationTests(_AllowlistTestBase):
    def _configure(self, temp_dir: str):
        # `STATE.ontology_backend` is captured when the module is imported, so
        # the process environment alone cannot switch this process to remote.
        STATE.ontology_backend = "production"
        return configure(temp_dir, temp_dir, temp_dir, agent_name="bi-analyst")

    def test_configure_rejects_active_repository_outside_allowlist(self) -> None:
        snapshot = self._snapshot_state()
        try:
            with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
                os.environ,
                {
                    "ONTOLOGY_BACKEND": "production",
                    "ONTOLOGY_REPOSITORY_ID": "4",
                    ALLOWLIST_ENV: "3",
                },
                clear=False,
            ), patch(
                "bi_agent.web.app.RemoteOntologyClient.from_env",
                return_value=FakeRemote("4"),
            ), patch(
                "bi_agent.web.app.register_all"
            ), patch(
                "bi_agent.web.app.load_agent_defs"
            ), patch(
                "bi_agent.web.app.get_agent_def_registry",
                return_value=_FakeRegistry(),
            ):
                with self.assertRaises(RuntimeError) as ctx:
                    self._configure(temp_dir)
                message = str(ctx.exception)
                self.assertIn("4", message)
                self.assertIn(ALLOWLIST_ENV, message)
        finally:
            self._restore_state(snapshot)

    def test_configure_accepts_demo2_allowlisted_repository(self) -> None:
        snapshot = self._snapshot_state()
        try:
            with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
                os.environ,
                {
                    "ONTOLOGY_BACKEND": "production",
                    "ONTOLOGY_REPOSITORY_ID": "3",
                    ALLOWLIST_ENV: "3",
                },
                clear=False,
            ), patch(
                "bi_agent.web.app.RemoteOntologyClient.from_env",
                return_value=FakeRemote("3"),
            ), patch(
                "bi_agent.web.app.register_all"
            ), patch(
                "bi_agent.web.app.load_agent_defs"
            ), patch(
                "bi_agent.web.app.get_agent_def_registry",
                return_value=_FakeRegistry(),
            ):
                self._configure(temp_dir)
                self.assertEqual(STATE.ontology_namespace, "demo2")
                self.assertEqual(STATE.doris_database, "ontology_demometaerp")
                self.assertTrue(STATE.use_doris)
                self.assertEqual(STATE.remote_ontology.repository_id, "3")
        finally:
            self._restore_state(snapshot)


class SourceEndpointFilterTests(_AllowlistTestBase):
    def test_sources_endpoint_only_exposes_allowlisted_repository(self) -> None:
        snapshot = self._snapshot_state()
        try:
            with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
                os.environ, {ALLOWLIST_ENV: "3"}, clear=False,
            ):
                for name, value in self._source_state(temp_dir, FakeRemote()).items():
                    setattr(STATE, name, value)
                payload = json.loads(get_sources_endpoint().body)
                self.assertEqual(
                    [repo["id"] for repo in payload["ontology"]["remote_repositories"]],
                    ["3"],
                )
                self.assertEqual(
                    [repo["name"] for repo in payload["ontology"]["remote_repositories"]],
                    ["ECore本体库-勿动"],
                )
                self.assertEqual(payload["ontology"]["options"], ["__metaerp_repository__:3"])
                self.assertEqual(payload["database"]["options"], ["__doris_repository__:3"])
                self.assertEqual(payload["doris"]["database"], "ontology_demometaerp")
                self.assertEqual(payload["atomic_source"]["repository_id"], "3")
                rendered = json.dumps(payload, ensure_ascii=False)
                for hidden in ("ontology_one", "ontology_four", "ontology_seven", "库四", "库七"):
                    self.assertNotIn(hidden, rendered)
        finally:
            self._restore_state(snapshot)

    def test_put_sources_rejects_non_allowlisted_repository(self) -> None:
        snapshot = self._snapshot_state()
        session_id = "allowlist-reject-test"
        STATE.source_contexts.pop(session_id, None)
        try:
            with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
                os.environ, {ALLOWLIST_ENV: "3"}, clear=False,
            ), patch("bi_agent.web.app.register_all"):
                for name, value in self._source_state(temp_dir, FakeRemote()).items():
                    setattr(STATE, name, value)
                with self.assertRaises(HTTPException) as ctx:
                    put_sources_endpoint(SourcesUpdate(
                        ontology="__metaerp_repository__:7",
                        session_id=session_id,
                    ))
                self.assertEqual(ctx.exception.status_code, 400)
                self.assertEqual(STATE.remote_ontology.repository_id, "3")
                self.assertEqual(STATE.doris_database, "ontology_demometaerp")
        finally:
            STATE.source_contexts.pop(session_id, None)
            self._restore_state(snapshot)

    def test_put_sources_allows_allowlisted_switch(self) -> None:
        snapshot = self._snapshot_state()
        session_id = "allowlist-accept-test"
        STATE.source_contexts.pop(session_id, None)
        try:
            with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
                os.environ, {ALLOWLIST_ENV: "3,7"}, clear=False,
            ), patch("bi_agent.web.app.register_all"):
                for name, value in self._source_state(temp_dir, FakeRemote()).items():
                    setattr(STATE, name, value)
                response = put_sources_endpoint(SourcesUpdate(
                    ontology="__metaerp_repository__:7",
                    session_id=session_id,
                ))
                payload = json.loads(response.body)
                self.assertEqual(payload["ontology"], "__metaerp_repository__:7")
                self.assertEqual(payload["database"], "__doris_repository__:7")
                self.assertEqual(payload["doris_database"], "ontology_seven")
                self.assertEqual(STATE.remote_ontology.repository_id, "3")
        finally:
            STATE.source_contexts.pop(session_id, None)
            self._restore_state(snapshot)


if __name__ == "__main__":
    unittest.main()
