"""Read-only charts from frozen query rows; no model, fetch or inferred totals."""
from __future__ import annotations

from collections import OrderedDict
from datetime import date
import hashlib
import json
import math
import re

MAX_CHARTS = 3
MAX_POINTS = 24


def _cell(row, code):
    keys = [key for key in row if key == code or key.endswith('[' + code + ']')]
    if len(keys) != 1:
        return None
    value = row[keys[0]]
    return value.get('value') if isinstance(value, dict) else value


def _number(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str) and not re.fullmatch(r'[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?', value.strip()):
        return None
    try:
        value = float(value.replace(',', '') if isinstance(value, str) else value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def _time_key(value):
    match = re.fullmatch(r'(20\d{2})(?:[-/年](\d{1,2})(?:[-/月](\d{1,2})日?)?月?)?年?', value)
    if not match:
        return None
    try:
        return date(int(match[1]), int(match[2] or 1), int(match[3] or 1))
    except ValueError:
        return None


def chart_blocks(item):
    """Separate every query/metric, keep returned units and disclose bounded rows.

    Duplicate categories cannot be safely summed without knowing the grain;
    skip those series. Missing numeric values are excluded, never zero-filled.
    """
    groups = OrderedDict()
    for record in (item.get('evidence') or {}).get('records') or []:
        if not isinstance(record, dict) or not isinstance(record.get('data'), dict):
            continue
        scope = record.get('scope') or {}
        if not isinstance(scope, dict):
            continue
        request = scope.get('request')
        if not isinstance(request, dict):
            continue
        config = request.get('analysisConfig') or {}
        if not isinstance(config, dict):
            continue
        dimensions = config.get('dimensions') or []
        indicators = config.get('indicators') or []
        if not isinstance(dimensions,list) or not isinstance(indicators,list) or not dimensions or not indicators or any(not isinstance(d,dict) or not d.get('identifierCode') for d in dimensions):
            continue
        key = json.dumps(scope, sort_keys=True, ensure_ascii=False)
        groups.setdefault(key, (scope, dimensions, indicators, []))[3].append(record)
    blocks = []
    for key, (scope, dimensions, indicators, records) in groups.items():
        for indicator in indicators:
            if not isinstance(indicator,dict):
                continue
            code = indicator.get('identifierCode')
            if not code:
                continue
            points, seen, duplicate, omitted = [], set(), False, 0
            for record in records:
                row = record['data']
                labels = [_cell(row, d['identifierCode']) for d in dimensions]
                number = _number(_cell(row, code))
                if number is None or any(v is None or not str(v).strip() for v in labels):
                    omitted += 1
                    continue
                category = ' / '.join(str(v).strip() for v in labels)
                if category in seen:
                    duplicate = True
                    break
                seen.add(category)
                points.append((category, number, str(record.get('id') or '')))
            if duplicate or len(points) < 2:
                continue
            temporal = len(dimensions) == 1 and all(_time_key(p[0]) for p in points)
            if temporal:
                points.sort(key=lambda p: _time_key(p[0]))
            total = len(points)
            points = points[:MAX_POINTS]
            label = str(indicator.get('alias') or indicator.get('label') or code)
            unit = str(indicator.get('unit') or '')
            query_hash = hashlib.sha256(key.encode()).hexdigest()[:12]
            note = (f"冻结查询 {query_hash} · 指标 {code} · 凭据 {scope.get('receiptId') or '见记录范围'} · "
                    f"来源 {scope.get('source') or '见原始口径'}；只展示本次证据样本，不换算单位、不外推总体。"
                    f"证据记录：{', '.join(p[2] for p in points)}")
            if omitted:
                note += f'；排除 {omitted} 条缺失数值或维度的记录，不按零处理。'
            if total > MAX_POINTS:
                note += f'；有效记录 {total} 条，图示前 {MAX_POINTS} 条。'
            blocks.append({'kind':'chart', 'heading':label + (' · 趋势' if temporal else ' · 分布'),
                'params':dict(chart_type='line' if temporal else 'horizontal_bar',title=label,
                    subtitle='仅本次冻结证据样本，不换算单位、不外推总体。', x_axis=[p[0] for p in points],
                    series=[dict(name=label, data=[p[1] for p in points])],
                    unit=unit, y_axis_name=unit or '原始返回值（单位见查询口径）', source_note=note)})
            if len(blocks) >= MAX_CHARTS:
                return blocks
    return blocks
