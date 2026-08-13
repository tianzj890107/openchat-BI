"""HTTP client for the production ontology service.

The service documented in ``常用API.docx`` exposes a small, stable contract
around object resolution, graph neighborhood lookup, and structured metadata
queries.  This client deliberately keeps transport concerns out of the agent
tools so local Excel and remote ontology backends can share the same tools.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class OntologyApiError(RuntimeError):
    """A transport or business-level error returned by the ontology API."""


class RemoteOntologyClient:
    def __init__(
        self,
        base_url: str,
        repository_id: str,
        *,
        app_id: str = "",
        auth_token: str = "",
        namespace: str = "",
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.repository_id = str(repository_id).strip()
        self.app_id = app_id.strip()
        self.auth_token = auth_token.strip()
        self.namespace = namespace.strip()
        self.timeout = timeout
        try:
            self.cache_ttl = max(0.0, float(os.environ.get("ONTOLOGY_CACHE_TTL_SECONDS", "30")))
        except ValueError:
            self.cache_ttl = 30.0
        self._object_cache: dict[str, tuple[float, list[dict[str, Any]], bool]] = {}
        self._repository_page_cache: dict[tuple[int, int], tuple[float, dict[str, Any]]] = {}
        if not self.base_url:
            raise ValueError("ONTOLOGY_BASE_URL is required for the remote ontology backend")
        if not self.repository_id:
            raise ValueError("ONTOLOGY_REPOSITORY_ID is required for the remote ontology backend")

    @classmethod
    def from_env(cls) -> "RemoteOntologyClient":
        try:
            timeout = float(os.environ.get("ONTOLOGY_TIMEOUT_SECONDS", "30"))
        except ValueError:
            timeout = 30.0
        return cls(
            os.environ.get("ONTOLOGY_BASE_URL", ""),
            os.environ.get("ONTOLOGY_REPOSITORY_ID", ""),
            app_id=os.environ.get("ONTOLOGY_APP_ID", ""),
            auth_token=os.environ.get("ONTOLOGY_AUTH_TOKEN", ""),
            namespace=os.environ.get("ONTOLOGY_NAMESPACE", ""),
            timeout=max(1.0, min(timeout, 120.0)),
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: Optional[dict[str, Any]] = None,
        body: Optional[dict[str, Any]] = None,
        include_repository_header: bool = True,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        if query:
            url += "?" + urlencode(query)
        headers = {"Accept": "application/json"}
        if include_repository_header and self.repository_id:
            headers["X-Ontology-Repository-Id"] = self.repository_id
        if self.app_id:
            headers["X-App-Id"] = self.app_id
        if self.auth_token:
            token = self.auth_token
            headers["Authorization"] = (
                token if token.lower().startswith(("bearer ", "basic "))
                else f"Bearer {token}"
            )
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = Request(url, data=data, headers=headers, method=method.upper())
        try:
            with urlopen(req, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:1000]
            raise OntologyApiError(f"HTTP {e.code} from {path}: {detail}") from e
        except URLError as e:
            raise OntologyApiError(f"无法连接本体服务 {self.base_url}: {e.reason}") from e
        except TimeoutError as e:
            raise OntologyApiError(f"本体服务请求超时: {path}") from e
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as e:
            raise OntologyApiError(f"本体服务返回非 JSON: {path}") from e
        if not isinstance(payload, dict):
            raise OntologyApiError(f"本体服务返回结构无效: {path}")
        # The documented wrapper uses either success=true or code=200.
        code = payload.get("code")
        if payload.get("success") is False or (code is not None and code not in (200, "200")):
            raise OntologyApiError(str(payload.get("msg") or f"本体服务业务错误 code={code}"))
        return payload

    def ensure_object(self, name: str, candidate_types: list[str]) -> dict[str, Any]:
        payload = self._request(
            "POST",
            "/agent/ontology/ensureOntologyObject",
            body={"name": name, "candidateTypes": candidate_types},
        )
        return payload.get("data") or {}

    def find_related(self, type_name: str, code: str, depth: int = 2) -> dict[str, Any]:
        payload = self._request(
            "GET",
            "/agent/ontology/findRelatedObjects",
            query={"type": type_name, "code": code, "depth": max(1, min(int(depth), 5))},
        )
        return payload.get("data") or {}

    def search_objects(self, type_name: str, text: str, limit: int = 20) -> list[dict[str, Any]]:
        """Search a type by its English name or localized label.

        ``ensureOntologyObject`` is intentionally exact/English-oriented in
        the backend contract. This small read-only fallback makes Chinese user
        queries work without putting a local copy of the ontology back into
        the application.
        """
        needle = str(text or "").strip().replace("'", "''")
        if not needle:
            return []
        safe_limit = max(1, min(int(limit), 100))
        script = (
            f"SELECT code, name, label, description FROM {type_name} "
            f"WHERE name LIKE '%{needle}%' OR label LIKE '%{needle}%' "
            f"LIMIT {safe_limit}"
        )
        data = self.script_query("sql", script)
        rows: list[dict[str, Any]] = []
        for result in data.get("results") or []:
            rows.extend(result.get("rows") or [])
        return rows[:safe_limit]

    def list_objects(self, type_name: str, limit: int = 2000) -> list[dict[str, Any]]:
        """Return complete property maps for one ontology type.

        The managed repositories currently contain at most a few thousand
        objects per type.  Keeping this primitive in the transport client lets
        the lookup layer apply the same ranking and field aliases regardless
        of the repository's metadata dialect.
        """
        safe_limit = max(1, min(int(limit), 5000))
        cached = self._object_cache.get(type_name)
        now = time.monotonic()
        if cached and now - cached[0] <= self.cache_ttl and (cached[2] or len(cached[1]) >= safe_limit):
            return cached[1][:safe_limit]
        data = self.script_query("sql", f"SELECT FROM {type_name} LIMIT {safe_limit}")
        rows: list[dict[str, Any]] = []
        for result in data.get("results") or []:
            for row in result.get("rows") or []:
                if isinstance(row, dict):
                    rows.append(row)
        # Cache only the largest snapshot seen for the type; a prior LIMIT 1
        # response must not masquerade as a complete later lookup.
        previous = self._object_cache.get(type_name)
        if previous is None or len(rows) >= len(previous[1]):
            self._object_cache[type_name] = (now, rows, len(rows) < safe_limit)
        return rows[:safe_limit]

    def script_query(
        self, language: str, script: str, params_list: Optional[list[list[Any]]] = None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"language": language, "script": script}
        if params_list is not None:
            body["paramsList"] = params_list
        payload = self._request("POST", "/agent/ontology/scriptQuery", body=body)
        return payload.get("data") or {}

    def metadata_query(self, analysis_config: dict[str, Any], common_config: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        payload = self._request(
            "POST",
            "/api/v1/analysis/meta/query",
            body={"analysisConfig": analysis_config, "commonConfig": common_config or {}},
        )
        return payload.get("data") or {}

    def data_query(self, analysis_config: dict[str, Any], common_config: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Execute a semantic metric/dimension query through the MAL API."""
        payload = self._request(
            "POST",
            "/api/v1/analysis/data/query",
            body={"analysisConfig": analysis_config, "commonConfig": common_config or {}},
        )
        return payload.get("data") or {}

    def repository_info(self) -> dict[str, Any]:
        payload = self._request("GET", f"/system/manager/ontology-repository/{self.repository_id}")
        return payload.get("data") or {}

    def list_repositories(self, *, page: int = 1, size: int = 100) -> dict[str, Any]:
        """List selectable ontology repositories from the documented manager API."""
        safe_page = max(1, page)
        safe_size = max(1, min(size, 100))
        cache_key = (safe_page, safe_size)
        cached = self._repository_page_cache.get(cache_key)
        now = time.monotonic()
        if cached and now - cached[0] <= self.cache_ttl:
            return cached[1]
        data = self._request(
            "GET",
            "/system/manager/ontology-repository",
            query={"page": safe_page, "size": safe_size},
            include_repository_header=False,
        ).get("data") or {}
        self._repository_page_cache[cache_key] = (now, data)
        return data
