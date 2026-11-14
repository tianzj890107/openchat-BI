"""Render and run the global ontology's registered queries (read-only).

Only registered SQL is executed, never SQL written by the model.  Three kinds:

* T templates carry their period in a ``parameters`` CTE (no bind parameters);
* Q config queries use ``:name`` parameters and optional
  ``/*FILTER_BEGIN:CODE*/…/*FILTER_END:CODE*/`` and ``/*TIME_BEGIN*/…/*TIME_END*/``
  blocks, kept only when the caller supplies the parameters in them;
* N diagnostics stay disabled until they are accepted.
"""
from __future__ import annotations

import datetime as dt
import re

_NAME = re.compile(r"(?<![:\w]):([A-Za-z_]\w*)")
_FILTER = re.compile(r"/\*FILTER_BEGIN:([A-Za-z0-9_]+)\*/(.*?)/\*FILTER_END:\1\*/", re.S)
_TIME = re.compile(r"/\*TIME_BEGIN\*/(.*?)/\*TIME_END\*/", re.S)
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_NOW = re.compile(r"\b(CURRENT_DATE|CURRENT_TIMESTAMP|NOW\s*\(|LOCALTIMESTAMP)\b", re.I)


class QueryRejected(ValueError):
    """The call does not satisfy the query's contract; nothing was executed."""


def _strip_comments(sql):
    """Drop ``--`` line comments outside quoted literals (block markers stay)."""
    lines = []
    for line in sql.split("\n"):
        quoted, cut, index = False, None, 0
        while index < len(line):
            char = line[index]
            if char == "'":
                quoted = not quoted
            elif not quoted and line.startswith("--", index):
                cut = index
                break
            index += 1
        kept = line if cut is None else line[:cut]
        if kept.strip():
            lines.append(kept.rstrip())
    return "\n".join(lines)


def _outside_literals(sql, replace):
    """Apply ``replace`` to the parts of ``sql`` that are not string literals."""
    parts = re.split(r"('(?:[^']|'')*')", sql)
    return "".join(part if index % 2 else replace(part) for index, part in enumerate(parts))


def _date(value, label):
    text = "" if value is None else str(value).strip()
    if not _DATE.fullmatch(text):
        raise QueryRejected(f"{label} 需要 YYYY-MM-DD 日期")
    try:
        dt.date.fromisoformat(text)
    except ValueError as exc:
        raise QueryRejected(f"{label} 不是合法日期") from exc
    return text


def _values(value, label):
    items = value if isinstance(value, (list, tuple)) else [value]
    items = [str(item).strip() for item in items if item is not None and str(item).strip()]
    if not items:
        raise QueryRejected(f"{label} 不能为空")
    if len(items) > 200:
        raise QueryRejected(f"{label} 最多 200 个取值")
    return items


def render_template(sql, params, schema="ded_public"):
    """Bind a T template: its ``parameters`` CTE period and observation time."""
    start = _date(params.get("start_date"), "start_date")
    end = _date(params.get("end_exclusive"), "end_exclusive")
    if end <= start:
        raise QueryRejected("end_exclusive 必须晚于 start_date")
    observed = _date(params.get("observed_date") or dt.date.today().isoformat(), "observed_date")
    for name, value in (("start_date", start), ("end_exclusive", end)):
        pattern = (r"(?:DATE\s+'\d{4}-\d{2}-\d{2}'|CAST\(\s*'\d{4}-\d{2}-\d{2}'\s+AS\s+DATE\s*\))"
                   r"\s+AS\s+" + name + r"\b")
        sql, count = re.subn(pattern, f"DATE '{value}' AS {name}", sql, flags=re.I)
        if count != 1:
            raise QueryRejected(f"模板缺少唯一的 {name} 参数，不能绑定期间")
    stamp = f"TIMESTAMP '{observed} 23:59:59'"
    sql = re.sub(r"CAST\(\s*CURRENT_TIMESTAMP\s+AS\s+TIMESTAMP\s*\)|CURRENT_TIMESTAMP::timestamp",
                 stamp, sql, flags=re.I)
    return _finish(sql, {}, schema), dict(start_date=start, end_exclusive=end, observed_date=observed)


def render_config(sql, contract, params, schema="ded_public"):
    """Bind a Q config query from its filter contract and ``:name`` parameters."""
    supplied = {key: value for key, value in (params or {}).items()
                if value not in (None, "", [], ())}
    known = {name for spec in (contract or {}).values()
             for name in (spec.get("param"), spec.get("from"), spec.get("to")) if name}
    in_sql = set(_NAME.findall(_outside_literals(sql, lambda part: part)))
    unknown = sorted(set(supplied) - known - in_sql - {"observed_date"})
    if unknown:
        raise QueryRejected("查询不接受这些参数：" + "、".join(unknown))

    def block_params(body):
        return set(_NAME.findall(body))

    def keep(match):
        body = match.group(match.lastindex)
        return body if block_params(body) <= set(supplied) else ""

    sql = _FILTER.sub(keep, sql)
    sql = _TIME.sub(keep, sql)
    values, used = {}, {}

    def bind(part):
        def one(match):
            name = match.group(1)
            if name not in supplied:
                raise QueryRejected(f"缺少必需参数 {name}")
            raw = supplied[name]
            if name in {"start_date", "end_exclusive"} or re.search(r"_date$|^date_", name):
                values[name] = _date(raw, name)
                used[name] = values[name]
                return f"%({name})s"
            if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                values[name] = raw
                used[name] = raw
                return f"%({name})s"
            items = _values(raw, name)
            used[name] = items
            keys = []
            for index, item in enumerate(items):
                key = f"{name}_{index}"
                values[key] = item
                keys.append(f"%({key})s")
            return ", ".join(keys)
        return _NAME.sub(one, part.replace("%", "%%"))

    parts = re.split(r"('(?:[^']|'')*')", _strip_comments(sql))
    bound = "".join(part.replace("%", "%%") if index % 2 else bind(part) for index, part in enumerate(parts))
    if "start_date" in values and "end_exclusive" in values and values["end_exclusive"] <= values["start_date"]:
        raise QueryRejected("end_exclusive 必须晚于 start_date")
    return _finish(bound, values, schema, escaped=True), used


def _finish(sql, values, schema, escaped=False):
    if not escaped:
        sql = _strip_comments(sql).replace("%", "%%")
    sql = sql.strip().rstrip(";").rstrip()
    if schema and schema != "ded_public" and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
        sql = sql.replace("ded_public.", f"{schema}.")
    if not re.match(r"(?is)^\s*(with|select)\b", sql):
        raise QueryRejected("登记 SQL 不是只读查询")
    return sql, values


def render(config, index, params, schema="ded_public"):
    """(sql, bind values, effective parameters, notes) for a registered query."""
    query = (config.get("queries") or {}).get(index)
    if not query:
        raise QueryRejected(f"未登记的查询：{index}")
    if query["gate"] != "enabled":
        raise QueryRejected(f"{index} 不可执行：{query.get('gateReason') or query['gate']}")
    raw = config["sql"][index]
    notes = []
    if query["mode"] == "template":
        (sql, values), effective = render_template(raw, params or {}, schema)
        if _NOW.search(_outside_literals(sql, lambda part: part)):
            notes.append("该查询仍含数据库当前时间，结果只代表当前时点")
    else:
        (sql, values), effective = render_config(raw, query.get("contract") or {}, params or {}, schema)
        if _NOW.search(_outside_literals(raw, lambda part: part)):
            notes.append("该查询用数据库当前日期计算，结果只代表当前时点，不能解释为历史截止日")
    return sql, values, effective, notes


def classify(rows, truncated, metric_columns):
    """Result quality: ok / empty / zero / incomplete (never merged into one)."""
    if truncated:
        return "incomplete"
    if not rows:
        return "empty"
    numeric = [row.get(column) for row in rows for column in metric_columns if column in row]
    if numeric and all(value in (0, 0.0, None) for value in numeric):
        return "zero" if any(value in (0, 0.0) for value in numeric) else "empty"
    return "ok"
