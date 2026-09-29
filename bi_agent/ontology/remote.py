"""HTTP client for the production ontology service.

The service documented in ``常用API.docx`` exposes a small, stable contract
around object resolution, graph neighborhood lookup, and structured metadata
queries.  This client deliberately keeps transport concerns out of the agent
tools so local Excel and remote ontology backends can share the same tools.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def _rows_of(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _column_names(columns: Any, rows: list[dict[str, Any]]) -> list[str]:
    """Column order for a table: explicit ``identifierCode`` list, else row keys."""
    names: list[str] = []
    if isinstance(columns, list):
        for column in columns:
            if isinstance(column, dict):
                name = column.get("identifierCode") or column.get("name") or column.get("label")
            else:
                name = column
            if name not in (None, ""):
                names.append(str(name))
    if names:
        return names
    for row in rows:
        for key in row:
            if key not in names:
                names.append(str(key))
    return names


def _table_of(data: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return ``(columns, rows)`` for both MAL dialects, never raising.

    Recognition order: ``data.result.rows`` (new TABLE) → ``data.result``
    graph keys (new GRAPH: vertices/links/edges) → ``data.results[].rows``
    (legacy) → ``data.rows`` (bare rows).  A missing layer yields an empty
    table instead of an exception, and rows are never fabricated.
    """
    if not isinstance(data, dict):
        return [], []
    result = data.get("result")
    if isinstance(result, dict):
        raw_rows = result.get("rows")
        if isinstance(raw_rows, list):
            rows = _rows_of(raw_rows)
            return _column_names(result.get("columns"), rows), rows
        graph_rows = (
            _rows_of(result.get("vertices"))
            + _rows_of(result.get("links"))
            + _rows_of(result.get("edges"))
        )
        if graph_rows or any(isinstance(result.get(key), list) for key in ("vertices", "links", "edges")):
            return _column_names(result.get("columns"), graph_rows), graph_rows
    segments = data.get("results")
    if isinstance(segments, list):
        rows = []
        for segment in segments:
            if isinstance(segment, dict):
                rows.extend(_rows_of(segment.get("rows")))
        return _column_names(None, rows), rows
    rows = _rows_of(data.get("rows"))
    return _column_names(data.get("columns"), rows), rows


def _repository_fields(row: dict[str, Any]) -> dict[str, Any]:
    """Expose both the new and the legacy repository database field names."""
    normalised = dict(row)
    aliases = (
        ("dorisDatabase", "currentDatabase"),
        ("metaDatabase", "arcadedbMetaDatabase"),
        ("knowledgeDatabase", "arcadedbKnowledgeDatabase"),
    )
    for primary, legacy in aliases:
        value = row.get(primary) or row.get(legacy)
        if value not in (None, ""):
            normalised[primary] = str(value)
            normalised[legacy] = str(value)
    return normalised


class OntologyApiError(RuntimeError):
    """A transport or business-level error returned by the ontology API."""


def _query_scalar(value: Any) -> Any:
    """Unwrap scalar values returned by different script-query versions."""
    if isinstance(value, list) and len(value) == 1:
        return _query_scalar(value[0])
    if isinstance(value, dict) and set(value) == {"value"}:
        return _query_scalar(value["value"])
    return value


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
        self._graph_neighborhood_cache: dict[tuple[str, str, int, int, int], tuple[float, dict[str, Any]]] = {}
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

    def _dual_request(self, attempts: list[tuple[str, str, dict[str, Any]]]) -> dict[str, Any]:
        """Send the new-dialect request first, then fall back to the legacy one.

        The ontology service keeps the ``/api/v1/analysis/...`` family and the
        older ``/agent/...`` / ``/system/...`` paths online at the same time, so
        the client cannot assume a coordinated cutover.  The first answer wins;
        if every dialect fails the first error is re-raised so upstream
        messages are never hidden behind an empty result.
        """
        first_error: Optional[OntologyApiError] = None
        for method, path, kwargs in attempts:
            try:
                return self._request(method, path, **kwargs)
            except OntologyApiError as exc:
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error
        raise OntologyApiError("本体服务请求失败：没有可用的传输方言")

    @staticmethod
    def _object_info_of(row: dict[str, Any]) -> dict[str, Any]:
        """Normalise a resolved object row to ``{"typeName", "properties"}``."""
        properties = row.get("properties")
        if not isinstance(properties, dict):
            properties = {
                key: value
                for key, value in row.items()
                if key not in ("typeName", "type")
            }
        return {
            "typeName": str(row.get("typeName") or row.get("type") or "Unknown"),
            "properties": properties,
        }

    def ensure_object(self, name: str, candidate_types: list[str]) -> dict[str, Any]:
        payload = self._dual_request([
            ("POST", "/api/v1/analysis/context/resolve-ontology-object", {
                "body": {
                    "analysisConfig": {"name": name, "candidateTypes": candidate_types},
                    "commonConfig": {},
                },
            }),
            ("POST", "/agent/ontology/ensureOntologyObject", {
                "body": {"name": name, "candidateTypes": candidate_types},
            }),
        ])
        data = payload.get("data")
        if not isinstance(data, dict):
            data = {}
        if "found" in data or "objectInfo" in data:
            object_info = data.get("objectInfo")
            return {
                "found": bool(data.get("found")),
                "objectInfo": object_info if isinstance(object_info, dict) else None,
            }
        _, rows = _table_of(data)
        if not rows:
            return {"found": False, "objectInfo": None}
        return {"found": True, "objectInfo": self._object_info_of(rows[0])}

    def find_related(self, type_name: str, code: str, depth: int = 2) -> dict[str, Any]:
        query = {"type": type_name, "code": code, "depth": max(1, min(int(depth), 5))}
        payload = self._dual_request([
            ("GET", "/api/v1/analysis/context/expand-ontology-context", {"query": query}),
            ("GET", "/agent/ontology/findRelatedObjects", {"query": query}),
        ])
        data = payload.get("data")
        if not isinstance(data, dict):
            data = {}
        objects = data.get("objects") or data.get("relatedObjects")
        if isinstance(objects, list):
            return {"objects": [item for item in objects if isinstance(item, dict)]}
        _, rows = _table_of(data)
        return {"objects": [self._object_info_of(row) for row in rows]}

    def graph_neighborhood(
        self,
        type_name: str,
        code: str,
        *,
        depth: int = 3,
        max_objects: int = 800,
        max_relations: int = 3000,
    ) -> dict[str, Any]:
        """Return a bounded remote subgraph with vertices *and* directed edges.

        ``findRelatedObjects`` is the stable traversal API, but intentionally
        returns a de-duplicated vertex list without edge evidence.  Use that
        list as the safe traversal boundary, then recover all edges inside the
        boundary with the documented read-only OpenCypher endpoint.  Repositories
        that do not support the generic edge query still return the complete
        vertex neighborhood with ``relations_available=False``.
        """

        normalized_type = str(type_name or "").strip()
        normalized_code = str(code or "").strip()
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", normalized_type):
            raise ValueError("invalid ontology type")
        if not normalized_code:
            raise ValueError("ontology code is required")
        safe_depth = max(1, min(int(depth), 5))
        safe_objects = max(1, min(int(max_objects), 2000))
        safe_relations = max(1, min(int(max_relations), 10000))
        cache_key = (normalized_type, normalized_code, safe_depth, safe_objects, safe_relations)
        now = time.monotonic()
        cached = self._graph_neighborhood_cache.get(cache_key)
        if cached and now - cached[0] <= self.cache_ttl:
            return cached[1]

        related_error = ""
        try:
            related = self.find_related(normalized_type, normalized_code, safe_depth)
        except OntologyApiError as exc:
            # Some ontology-manager versions reject a traversal as soon as it
            # reaches a physical TableNode, even though TableNode vertices are
            # valid and queryable through the read-only OpenCypher endpoint.
            # Keep the global graph card usable by recovering the same bounded
            # vertex neighborhood through OpenCypher. Other API failures still
            # surface normally so configuration/auth errors are not hidden.
            if "未知本体类型: TableNode" not in str(exc):
                raise
            related_error = str(exc)
            related = {"objects": []}
        objects: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        def remember(type_value: str, props: dict[str, Any], *, anchor: bool = False) -> None:
            actual_type = str(type_value or props.get("typeName") or props.get("type") or "Unknown")
            actual_props = props.get("properties") if isinstance(props.get("properties"), dict) else props
            actual_props = dict(actual_props or {})
            obj_code = str(actual_props.get("code") or actual_props.get("identifierCode") or "").strip()
            if not obj_code:
                return
            key = (actual_type, obj_code)
            if key in seen or len(objects) >= safe_objects:
                return
            seen.add(key)
            objects.append({"typeName": actual_type, "properties": actual_props, "anchor": anchor})

        # Preserve the root even though findRelatedObjects normally excludes it.
        try:
            roots = self.list_objects(normalized_type, 5000)
            root = next((row for row in roots if str(row.get("code") or row.get("identifierCode") or "") == normalized_code), None)
        except OntologyApiError:
            root = None
        remember(normalized_type, root or {"code": normalized_code}, anchor=True)
        related_objects = [
            item
            for item in (related.get("objects") or related.get("relatedObjects") or [])
            if isinstance(item, dict)
        ]
        for item in related_objects:
            remember(str(item.get("typeName") or item.get("type") or "Unknown"), item)

        # The ``expand-ontology-context`` reply may legitimately carry no rows
        # (for example a repository that only answers the read-only OpenCypher
        # traversal).  Recover the same bounded neighbourhood through the
        # script endpoint instead of returning a lone anchor -- exactly what
        # the TableNode fallback below already does.
        if related_error or not related_objects:
            vertex_script = (
                f"MATCH p=(root)-[*0..{safe_depth}]-(n) "
                "WHERE root.code = $code "
                "UNWIND nodes(p) AS vertex "
                "RETURN DISTINCT labels(vertex) AS typeNames, "
                "properties(vertex) AS properties "
                f"LIMIT {safe_objects}"
            )
            vertex_data = self.script_query(
                "opencypher", vertex_script, [["code", normalized_code]],
            )
            for result in vertex_data.get("results") or []:
                for row in result.get("rows") or []:
                    if not isinstance(row, dict):
                        continue
                    type_names = _query_scalar(row.get("typeNames"))
                    if isinstance(type_names, list):
                        type_value = next((str(item) for item in type_names if item), "Unknown")
                    else:
                        type_value = str(type_names or "Unknown")
                    props = _query_scalar(row.get("properties"))
                    if isinstance(props, dict):
                        remember(type_value, props)

        codes = sorted({
            str(item["properties"].get("code") or item["properties"].get("identifierCode") or "").strip()
            for item in objects
        } - {""})
        relations: list[dict[str, Any]] = []
        relation_error = ""
        if len(codes) > 1:
            script = (
                "MATCH (s)-[r]->(t) "
                "WHERE s.code IN $codes AND t.code IN $codes "
                "RETURN s.code AS sourceCode, type(r) AS relationType, "
                "properties(r) AS relationProperties, t.code AS targetCode "
                f"LIMIT {safe_relations}"
            )
            try:
                edge_data = self.script_query("opencypher", script, [["codes", codes]])
                for result in edge_data.get("results") or []:
                    for row in result.get("rows") or []:
                        if isinstance(row, dict):
                            relations.append(row)
            except OntologyApiError as exc:
                relation_error = str(exc)

        relations_available = not relation_error and (len(codes) <= 1 or bool(relations))
        if len(codes) > 1 and not relations and not relation_error:
            relation_error = "edge query returned no relationships for a non-empty neighborhood"

        graph = {
            "anchor": {"typeName": normalized_type, "code": normalized_code},
            "depth": safe_depth,
            "objects": objects,
            "relations": relations,
            "relations_available": relations_available,
            "relation_error": relation_error,
        }
        self._graph_neighborhood_cache[cache_key] = (now, graph)
        return graph

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
        analysis_config: dict[str, Any] = {"language": language, "sql": script}
        if params_list is not None:
            analysis_config["paramsList"] = params_list
        legacy_body: dict[str, Any] = {"language": language, "script": script}
        if params_list is not None:
            legacy_body["paramsList"] = params_list
        payload = self._dual_request([
            ("POST", "/api/v1/analysis/meta/query", {
                "body": {"analysisConfig": analysis_config, "commonConfig": {}},
            }),
            ("POST", "/agent/ontology/scriptQuery", {"body": legacy_body}),
        ])
        data = payload.get("data")
        if not isinstance(data, dict):
            data = {}
        columns, rows = _table_of(data)
        if not rows:
            return {"results": []}
        return {"results": [{"rows": rows, "columns": columns}]}

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
        payload = self._dual_request([
            ("GET", f"/api/v1/analysis/context/ontology-repository/{self.repository_id}", {}),
            ("GET", f"/system/manager/ontology-repository/{self.repository_id}", {}),
        ])
        data = payload.get("data")
        if not isinstance(data, dict) or not data:
            data = payload
        if any(key in data for key in ("result", "results", "rows")):
            _, rows = _table_of(data)
            if rows:
                return _repository_fields(rows[0])
        return _repository_fields(data)

    def list_repositories(self, *, page: int = 1, size: int = 100) -> dict[str, Any]:
        """List selectable ontology repositories from the documented manager API."""
        safe_page = max(1, page)
        safe_size = max(1, min(size, 100))
        cache_key = (safe_page, safe_size)
        cached = self._repository_page_cache.get(cache_key)
        now = time.monotonic()
        if cached and now - cached[0] <= self.cache_ttl:
            return cached[1]
        query = {"page": safe_page, "size": safe_size}
        payload = self._dual_request([
            ("GET", "/api/v1/analysis/context/ontology-repository",
             {"query": query, "include_repository_header": False}),
            ("GET", "/system/manager/ontology-repository",
             {"query": query, "include_repository_header": False}),
        ])
        data = payload.get("data")
        if not isinstance(data, dict):
            data = {}
        items_value = data.get("items")
        if isinstance(items_value, list):
            items = [item for item in items_value if isinstance(item, dict)]
        else:
            _, items = _table_of(data)
        pagination = data.get("pagination") if isinstance(data.get("pagination"), dict) else {}
        total_value = pagination.get("total")
        if total_value is None:
            total_value = data.get("total")
        try:
            total = int(total_value or 0)
        except (TypeError, ValueError):
            total = 0
        if not total:
            total = len(items)
        normalised = {
            "items": [_repository_fields(item) for item in items],
            "total": total,
        }
        self._repository_page_cache[cache_key] = (now, normalised)
        return normalised
