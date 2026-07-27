"""Agent tools backed by the production ontology HTTP API."""

from __future__ import annotations

from typing import Any, Callable

from ..ontology.remote import OntologyApiError, RemoteOntologyClient
from .graph_tools import GRAPH_CONTEXT_SCHEMA, GRAPH_EXPAND_SCHEMA
from .ontology_tools import (
    ENTITY_DESCRIBE_SCHEMA,
    LIST_BUSINESS_OBJECTS_SCHEMA,
    METRIC_LOOKUP_SCHEMA,
    ONTOLOGY_QUERY_SCHEMA,
    RELATION_LOOKUP_SCHEMA,
    TERM_DISAMBIGUATE_SCHEMA,
)

Executor = Callable[[dict[str, Any], str], str]

_CANDIDATE_TYPES = [
    "BusinessObject", "LogicalEntity", "BusinessAttribute", "Term",
    "Dimension", "Indicator", "TableNode", "Column",
]


def _props(data: dict[str, Any]) -> dict[str, Any]:
    obj = data.get("objectInfo") or data.get("object") or {}
    return obj.get("properties") or {}


def _type_name(data: dict[str, Any]) -> str:
    obj = data.get("objectInfo") or data.get("object") or {}
    return str(obj.get("typeName") or _props(data).get("typeName") or "")


def _format_object(type_name: str, props: dict[str, Any]) -> str:
    code = props.get("code") or props.get("identifierCode") or "?"
    label = props.get("label") or props.get("name") or code
    lines = [f"[{code}] {label} ({type_name})"]
    for key in ("name", "description", "alias", "physicalTable", "tableName", "columnName"):
        if props.get(key) and str(props.get(key)) not in lines:
            lines.append(f"  {key}: {props[key]}")
    return "\n".join(lines)


def _candidate_results(client: RemoteOntologyClient, query: str) -> list[tuple[str, dict[str, Any]]]:
    found: list[tuple[str, dict[str, Any]]] = []
    for type_name in _CANDIDATE_TYPES:
        try:
            data = client.ensure_object(query, [type_name])
        except OntologyApiError:
            data = {}
        if data.get("found"):
            props = _props(data)
            key = (str(data.get("objectInfo", {}).get("typeName") or type_name), str(props.get("code")))
            if not any(k == key for k, _ in found):
                found.append((key[0], data))
        # The backend's ensure endpoint documents English-name lookup. If the
        # user asks in Chinese (or uses a localized label), fall back to the
        # read-only script endpoint for that same type.
        if not data.get("found"):
            try:
                rows = client.search_objects(type_name, query, limit=10)
            except OntologyApiError:
                # A repository may not materialize every optional type
                # (TableNode/Column are common examples); keep searching the
                # remaining canonical types.
                rows = []
            for row in rows:
                pseudo = {"objectInfo": {"typeName": type_name, "properties": row}}
                key = (type_name, str(row.get("code") or row.get("name")))
                if not any(k == key for k, _ in found):
                    found.append((key[0], pseudo))
    return found


def _code_type(value: str) -> str:
    code = value.upper()
    if code.startswith("BO"):
        return "BusinessObject"
    if code.startswith("LE"):
        return "LogicalEntity"
    if code.startswith("AT"):
        return "BusinessAttribute"
    if code.startswith("M"):
        return "Indicator"
    if code.startswith("T"):
        return "Term"
    return "BusinessObject"


def _related_text(data: dict[str, Any], title: str = "关联本体") -> str:
    objects = data.get("objects") or []
    lines = [f"# {title} ({len(objects)})"]
    for item in objects:
        obj_type = str(item.get("typeName") or item.get("type") or "Unknown")
        lines.append(_format_object(obj_type, item.get("properties") or {}))
    return "\n\n".join(lines) if objects else f"{title}: no related objects."


def _make_query(client: RemoteOntologyClient) -> Executor:
    def run(params: dict[str, Any], cwd: str) -> str:
        query = str(params.get("query") or "").strip()
        if not query:
            return "OntologyQuery: empty query."
        try:
            matches = _candidate_results(client, query)
            if not matches:
                return f"OntologyQuery: no remote matches for {query!r}."
            return "# Remote OntologyQuery\n\n" + "\n\n".join(
                _format_object(kind, _props(data)) for kind, data in matches[:int(params.get("limit") or 10)]
            )
        except OntologyApiError as e:
            return f"OntologyQuery remote error: {e}"
    return run


def _make_term(client: RemoteOntologyClient) -> Executor:
    def run(params: dict[str, Any], cwd: str) -> str:
        term = str(params.get("term") or "").strip()
        if not term:
            return "TermDisambiguate: empty term."
        try:
            matches = _candidate_results(client, term)
            terms = [(kind, data) for kind, data in matches if kind.lower() in ("term", "terminology")]
            return "\n\n".join(_format_object(kind, _props(data)) for kind, data in (terms or matches)) or f"No term matches {term!r}."
        except OntologyApiError as e:
            return f"TermDisambiguate remote error: {e}"
    return run


def _make_metric(client: RemoteOntologyClient) -> Executor:
    def run(params: dict[str, Any], cwd: str) -> str:
        metric = str(params.get("metric") or "").strip()
        if not metric:
            return "MetricLookup: empty metric."
        try:
            matches = _candidate_results(client, metric)
            matches = [(kind, data) for kind, data in matches if kind.lower() in ("indicator", "metric")]
            return "\n\n".join(_format_object(kind, _props(data)) for kind, data in matches) or f"No metric matches {metric!r}."
        except OntologyApiError as e:
            return f"MetricLookup remote error: {e}"
    return run


def _make_related(client: RemoteOntologyClient) -> Executor:
    def run(params: dict[str, Any], cwd: str) -> str:
        entity = str(params.get("entity") or "").strip()
        if not entity:
            return "RelationLookup: empty entity."
        try:
            data = client.find_related(_code_type(entity), entity, depth=2)
            return _related_text(data, f"Remote relations for {entity}")
        except OntologyApiError as e:
            return f"RelationLookup remote error: {e}"
    return run


def _make_describe(client: RemoteOntologyClient) -> Executor:
    def run(params: dict[str, Any], cwd: str) -> str:
        entity = str(params.get("entity") or "").strip()
        if not entity:
            return "EntityDescribe: empty entity."
        try:
            matches = _candidate_results(client, entity)
            if not matches:
                return f"EntityDescribe: no remote match for {entity!r}."
            kind, data = matches[0]
            props = _props(data)
            related = client.find_related(kind, str(props.get("code") or entity), depth=1)
            return _format_object(kind, props) + "\n\n" + _related_text(related, "Attributes and relations")
        except OntologyApiError as e:
            return f"EntityDescribe remote error: {e}"
    return run


def _make_list_bos(client: RemoteOntologyClient) -> Executor:
    def run(params: dict[str, Any], cwd: str) -> str:
        try:
            limit = max(1, min(int(params.get("limit") or 100), 200))
            data = client.script_query(
                "sql", f"SELECT code, name, label FROM BusinessObject LIMIT {limit}"
            )
            rows = [
                row
                for result in (data.get("results") or [])
                for row in (result.get("rows") or [])
            ]
            if not rows:
                return "ListBusinessObjects: remote ontology is empty."
            return "# Remote BusinessObjects\n" + "\n".join(
                f"[{row.get('code', '?')}] {row.get('label') or row.get('name') or '?'} / {row.get('name', '-')}"
                for row in rows
            )
        except OntologyApiError as e:
            return f"ListBusinessObjects remote error: {e}"
    return run


def _make_graph_context(client: RemoteOntologyClient) -> Executor:
    def run(params: dict[str, Any], cwd: str) -> str:
        anchor = str(params.get("anchor") or "").strip()
        query = str(params.get("query") or "").strip()
        try:
            if not anchor:
                matches = _candidate_results(client, query)
                if not matches:
                    return f"GraphContext: no remote anchor for {query!r}."
                if len(matches) > 1:
                    return "GraphContext: multiple candidates; specify anchor:\n" + "\n".join(
                        _format_object(kind, _props(data)).splitlines()[0] for kind, data in matches
                    )
                kind, data = matches[0]
                props = _props(data)
                anchor = str(props.get("code") or "")
                type_name = kind
            else:
                type_name = _code_type(anchor)
            return _related_text(client.find_related(type_name, anchor, depth=2), f"Remote GraphContext [{anchor}]")
        except OntologyApiError as e:
            return f"GraphContext remote error: {e}"
    return run


def _make_graph_expand(client: RemoteOntologyClient) -> Executor:
    def run(params: dict[str, Any], cwd: str) -> str:
        anchor = str(params.get("anchor") or "").strip()
        if not anchor:
            return "GraphExpand: empty anchor."
        try:
            return _related_text(client.find_related(_code_type(anchor), anchor, depth=3), f"Remote GraphExpand [{anchor}]")
        except OntologyApiError as e:
            return f"GraphExpand remote error: {e}"
    return run


def remote_specs(client: RemoteOntologyClient) -> list[tuple[dict[str, Any], Executor]]:
    """Return executors that override local ontology tools in remote mode."""
    factories = [
        (ONTOLOGY_QUERY_SCHEMA, _make_query),
        (TERM_DISAMBIGUATE_SCHEMA, _make_term),
        (METRIC_LOOKUP_SCHEMA, _make_metric),
        (RELATION_LOOKUP_SCHEMA, _make_related),
        (ENTITY_DESCRIBE_SCHEMA, _make_describe),
        (LIST_BUSINESS_OBJECTS_SCHEMA, _make_list_bos),
        (GRAPH_CONTEXT_SCHEMA, _make_graph_context),
        (GRAPH_EXPAND_SCHEMA, _make_graph_expand),
    ]
    return [(schema, factory(client)) for schema, factory in factories]
