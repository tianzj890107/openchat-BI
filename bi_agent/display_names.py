"""Deterministic display-name resolution for user-facing BI content.

Internal computation, queries, joins and tracing keep using codes.  User
facing narratives, tables and charts must prefer business names and keep
codes only as secondary traceability.  This module is the single shared
layer for that normalization so chart / table / session code never
duplicates naming logic.

Rules enforced here:

- A valid business name is the primary display text; the code may follow in
  parentheses (``采购金额（M0001）``) when first mentioned or for tracing.
- Bare codes (``M0001``, ``BO0006``, ``D0001``, ``BU001``,
  ``supplier_code``) are replaced only when a trusted mapping exists.
- Names are never guessed or fabricated: without a trusted mapping the
  original code is preserved verbatim.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Iterable, Mapping

# Placeholder values that must never be treated as real business names.
_INVALID_NAMES = {
    "", "-", "?", "--", "—", "null", "none", "n/a", "na", "unknown",
    "未知", "未设置", "无", "undefined", "none值",
}

# Ontology codes: M0001 / MET001 / D001 / DIM001 / BO0001 / LE0001 / AT0001
# / TERM001 / RULE001 / ACT001 / SSP001 / REL001 / ER001 / MREL001 / PROC001
# / PT001 / COL001 / T001 ...  plus generic uppercase-letter codes (BU001).
_ONTOLOGY_CODE_RE = re.compile(
    r"^(?:(?:M(?:ET)?|D(?:IM)?|BO|LE|AT(?:T)?|TERM|R(?:ULE)?|ACT|A|REL|ER|"
    r"MREL|SSP|PROC|PT|COL|T|P)\d{2,}|[A-Z]{2,}\d+)$",
    re.IGNORECASE,
)

# Common physical/business code column names (supplier_code, unit_code, ...).
_FIELD_CODE_RE = re.compile(r"(?:^|_)(?:code|cd|code_id)(?:_|$)", re.IGNORECASE)
_CAMEL_CODE_RE = re.compile(r"(Code|CodeId|Id|No|Num)$")

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")

Resolver = Callable[[str], str | None]


def is_valid_name(value: Any) -> bool:
    """True when the value is a usable display name (not a placeholder)."""
    text = str(value or "").strip()
    return bool(text) and text.casefold() not in _INVALID_NAMES


def looks_like_code(value: Any) -> bool:
    """Recognize bare codes that may need display-name resolution.

    Recognition is only used to decide *whether* to resolve; it never
    fabricates a name.
    """
    text = str(value or "").strip()
    if not text:
        return False
    if _ONTOLOGY_CODE_RE.match(text):
        return True
    if _FIELD_CODE_RE.search(text) or _CAMEL_CODE_RE.search(text):
        return True
    return False


def _first_valid(values: Iterable[Any]) -> str:
    for value in values:
        if is_valid_name(value):
            return str(value).strip()
    return ""


def pick_display_name(props: Mapping[str, Any]) -> str:
    """Pick the best display name from a normalized/raw ontology object.

    Priority: valid Chinese label > valid Chinese name > non-empty label >
    non-empty name > alias > code.  Empty strings, ``-`` and ``?`` are never
    accepted; unknown names are never guessed.
    """
    code = _first_valid((props.get("code"), props.get("identifierCode"),
                         props.get("identifier_code")))
    label = _first_valid((props.get("label"),))
    name = _first_valid((props.get("name"),))

    raw_alias = props.get("alias") or props.get("aliases") or []
    if isinstance(raw_alias, str):
        raw_alias = [raw_alias]
    alias = _first_valid(raw_alias)

    for candidate in (label, name):
        if _CJK_RE.search(candidate):
            return candidate
    for candidate in (label, name, alias):
        if candidate:
            return candidate
    return code


def display_text(code: Any, name: Any = None, *, trace: bool = True) -> str:
    """Build user-facing display text.

    - name + code and trace=True  -> ``采购金额（M0001）``
    - name only                   -> ``采购金额``
    - code only                   -> ``M0001``
    """
    code_text = str(code or "").strip()
    name_text = str(name or "").strip() if is_valid_name(name) else ""
    if name_text and code_text and trace:
        return f"{name_text}（{code_text}）"
    if name_text:
        return name_text
    return code_text


def normalize_text(value: Any, resolve: Resolver) -> Any:
    """Replace a bare code with its trusted display name; keep other text.

    Only whole values that look like codes are considered, so SQL snippets,
    URLs, JSON and ``source_note`` strings are never rewritten.
    """
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text or not looks_like_code(text):
        return value
    name = resolve(text)
    if not name or name == text:
        return value
    return name


def unique_aliases(names: Mapping[str, str]) -> dict[str, str]:
    """Stable-unique alias map for remote endpoints that require unique aliases.

    Repeated business names get a stable ``（code）`` suffix instead of
    falling back to a bare code as the primary display name.
    """
    seen: set[str] = set()
    result: dict[str, str] = {}
    for code in sorted(names):
        base = str(names[code] or code).strip() or code
        if base in seen:
            result[code] = f"{base}（{code}）"
        else:
            seen.add(base)
            result[code] = base
    return result


def _normalize_series(series: Any, resolve: Resolver) -> Any:
    if not isinstance(series, list):
        return series
    normalized: list[Any] = []
    for item in series:
        if not isinstance(item, dict):
            normalized.append(item)
            continue
        entry = dict(item)
        entry["name"] = normalize_text(entry.get("name"), resolve)
        data = entry.get("data")
        if isinstance(data, list):
            entry["data"] = [
                {**slice_, "name": normalize_text(slice_.get("name"), resolve)}
                if isinstance(slice_, dict) and "name" in slice_
                else slice_
                for slice_ in data
            ]
        normalized.append(entry)
    return normalized


def normalize_chart_params(params: Mapping[str, Any], resolve: Resolver) -> dict[str, Any]:
    """Normalize ChartGenerate fields: title / subtitle / y_axis_name /
    series[].name / pie data[].name / x_axis labels."""
    out = dict(params)
    for key in ("title", "subtitle", "y_axis_name"):
        if key in out:
            out[key] = normalize_text(out[key], resolve)
    out["series"] = _normalize_series(out.get("series"), resolve)
    x_axis = out.get("x_axis")
    if isinstance(x_axis, list):
        out["x_axis"] = [normalize_text(item, resolve) for item in x_axis]
    return out


def normalize_chart_multidim_params(params: Mapping[str, Any], resolve: Resolver) -> dict[str, Any]:
    """Normalize ChartGenerateMultiDim fields: title / dimensions[].label /
    dimensions[].x_axis / dimensions[].series[].name / pie category names.

    Dimension ``key`` and ``default_dim`` stay untouched (they are stable ids).
    """
    out = dict(params)
    for key in ("title", "subtitle"):
        if key in out:
            out[key] = normalize_text(out[key], resolve)
    dims = out.get("dimensions")
    if not isinstance(dims, list):
        return out
    normalized_dims: list[Any] = []
    for dim in dims:
        if not isinstance(dim, dict):
            normalized_dims.append(dim)
            continue
        entry = dict(dim)
        entry["label"] = normalize_text(entry.get("label"), resolve)
        entry["y_axis_name"] = normalize_text(entry.get("y_axis_name"), resolve)
        entry["series"] = _normalize_series(entry.get("series"), resolve)
        x_axis = entry.get("x_axis")
        if isinstance(x_axis, list):
            entry["x_axis"] = [normalize_text(item, resolve) for item in x_axis]
        normalized_dims.append(entry)
    out["dimensions"] = normalized_dims
    return out


def _strip_code_suffix(key: str) -> str:
    lowered = key.casefold()
    for suffix in ("_code", "code", "_id", "id"):
        if lowered.endswith(suffix) and len(lowered) > len(suffix):
            return key[: len(key) - len(suffix)]
    return ""


def _code_name_pairs(columns: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Pair ``*_code`` columns with their sibling ``*_name`` columns."""
    by_key: dict[str, str] = {str(c.get("key") or "").casefold(): str(c.get("key") or "")
                              for c in columns}
    pairs: list[tuple[str, str]] = []
    for col in columns:
        key = str(col.get("key") or "")
        if not _FIELD_CODE_RE.search(key):
            continue
        base = _strip_code_suffix(key)
        if not base:
            continue
        name_key = by_key.get(f"{base}_name") or by_key.get(f"{base}name")
        if name_key:
            pairs.append((name_key, key))
    return pairs


def normalize_table_params(params: Mapping[str, Any], resolve: Resolver) -> dict[str, Any]:
    """Normalize TableGenerate params.

    - ``columns[].label`` prefers business names when the label is a bare code.
    - When both ``supplier_code`` and ``supplier_name`` columns exist and rows
      are object-keyed (safe to reorder), the name column is moved ahead of the
      code column so names are shown first while the code stays traceable.
    - Array rows are never reordered (alignment is preserved); codes are kept.
    """
    out = dict(params)
    cols = out.get("columns")
    if not isinstance(cols, list):
        return out
    normalized: list[dict[str, Any]] = []
    for col in cols:
        if not isinstance(col, dict):
            normalized.append(col)  # type: ignore[arg-type]
            continue
        item = dict(col)
        if "label" in item:
            item["label"] = normalize_text(item["label"], resolve)
        normalized.append(item)
    rows = out.get("rows")
    if isinstance(rows, list) and rows and all(isinstance(r, dict) for r in rows):
        pairs = _code_name_pairs(normalized)
        if pairs:
            keys = [c.get("key") for c in normalized]
            for name_key, code_key in pairs:
                if name_key in keys and code_key in keys and keys.index(name_key) > keys.index(code_key):
                    name_col = next(c for c in normalized if c.get("key") == name_key)
                    code_col = next(c for c in normalized if c.get("key") == code_key)
                    normalized.remove(name_col)
                    normalized.insert(keys.index(code_key), name_col)
                    keys = [c.get("key") for c in normalized]
    out["columns"] = normalized
    return out


def normalize_display_params(
    tool_name: str,
    params: Mapping[str, Any],
    resolve: Resolver,
) -> dict[str, Any]:
    """Dispatch display-name normalization for render tools."""
    if tool_name == "ChartGenerate":
        return normalize_chart_params(params, resolve)
    if tool_name == "ChartGenerateMultiDim":
        return normalize_chart_multidim_params(params, resolve)
    if tool_name == "TableGenerate":
        return normalize_table_params(params, resolve)
    return dict(params)
