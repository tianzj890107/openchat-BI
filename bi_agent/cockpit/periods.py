"""Period identity and refresh cadence for cockpit AI publications.

The cockpit keeps one published analysis per business range.  Historical
year/month ranges are analysed once and then frozen; the active range keeps
being re-checked on the configured interval, and the range that just ended
stays refreshable for a short grace window.

"Active" is the period the delivery is currently working on, not necessarily
the wall clock month: customer deployments can backfill a period (for example
2025-10) long after it ended.  ``COCKPIT_ACTIVE_PERIOD`` overrides the derived
value; otherwise the delivered date-filter default is used.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from pathlib import Path

DEFAULT_INTERVAL = 900
DEFAULT_HISTORY_INTERVAL = 24 * 60 * 60
DEFAULT_GRACE_DAYS = 7
_METADATA = Path(__file__).resolve().parents[1] / 'web/static/cockpit/metadata/runtime.json'
_METADATA_PERIOD = None

_MONTH_RE = re.compile(r'(20\d{2})\s*[-/年.]\s*(\d{1,2})')
_YEAR_RE = re.compile(r'(?<!\d)(20\d{2})(?!\d)')


def normalise(value) -> str:
    """Return ``YYYY`` or ``YYYY-MM``; unknown input yields ``''``."""
    if not isinstance(value, str):
        return ''
    text = value.strip()
    if not text:
        return ''
    match = _MONTH_RE.search(text)
    if match:
        year, month = int(match.group(1)), int(match.group(2))
        if 1 <= month <= 12:
            return f'{year:04d}-{month:02d}'
    match = _YEAR_RE.search(text)
    if match:
        return match.group(1)
    return ''


def period_of_scope(ui_scope, fallback='') -> str:
    """Extract the business period from a committed filter scope string.

    ``uiScope`` is the canonical JSON of committed ProUI filter calls.  The
    host treats it as opaque, so extraction is deliberately conservative: only
    unambiguous ``YYYY-MM`` / ``YYYY年M月`` / ``YYYY`` tokens are accepted, and
    anything else falls back to the analysis context period.
    """
    fallback = normalise(fallback)
    if not isinstance(ui_scope, str):
        return fallback
    text = ui_scope.strip()
    if not text or text == 'default':
        return fallback
    if text[:1] in {'[', '{'}:
        # Committed filter calls arrive as ASCII-escaped JSON; unescape so a
        # Chinese month label such as "2025年10月" is readable.
        try:
            text = json.dumps(json.loads(text), ensure_ascii=False)
        except ValueError:
            pass
    months = _MONTH_RE.findall(text)
    if months:
        year, month = int(months[-1][0]), int(months[-1][1])
        if 1 <= month <= 12:
            return f'{year:04d}-{month:02d}'
    # Remove month tokens so a "2025" year-only filter is not shadowed by the
    # year part of a month range already handled above.
    years = _YEAR_RE.findall(_MONTH_RE.sub(' ', text))
    return years[-1] if years else fallback


def _delivered_period() -> str:
    """Default period of the delivered date filter (``YWLN_D044``)."""
    global _METADATA_PERIOD
    if _METADATA_PERIOD is None:
        value = ''
        try:
            data = json.loads(_METADATA.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            data = {}
        stack = [data]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                default = item.get('defaultValue')
                if isinstance(default, dict):
                    values = default.get('values')
                    if isinstance(values, dict):
                        found = normalise(values.get('YWLN_D044'))
                        if found:
                            value = found
                            break
                stack.extend(item.values())
            elif isinstance(item, list):
                stack.extend(item)
        _METADATA_PERIOD = value
    return _METADATA_PERIOD


def active_period(now=None) -> str:
    override = normalise(os.getenv('COCKPIT_ACTIVE_PERIOD', ''))
    if override:
        return override
    delivered = _delivered_period()
    if delivered:
        return delivered
    moment = _moment(now)
    return f'{moment.year:04d}-{moment.month:02d}'


def _moment(now):
    if now is None:
        return dt.datetime.now()
    if isinstance(now, dt.datetime):
        return now
    return dt.datetime.fromtimestamp(float(now))


def _flag(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def _previous(active: str) -> str:
    try:
        if len(active) == 7:
            year, month = int(active[:4]), int(active[5:])
            return f'{year - 1:04d}-12' if month == 1 else f'{year:04d}-{month - 1:02d}'
        if len(active) == 4:
            return f'{int(active) - 1:04d}'
    except ValueError:
        return ''
    return ''


def _compare(period: str, active: str) -> int:
    """Compare periods of possibly different granularity (year vs month)."""
    if len(period) == 4 and len(active) == 7:
        return (period > active[:4]) - (period < active[:4])
    if len(period) == 7 and len(active) == 4:
        return (period[:4] > active) - (period[:4] < active)
    return (period > active) - (period < active)


def policy_for(period, *, now=None, active=None, interval=None, grace_days=None,
               history_enabled=None) -> dict:
    """Refresh cadence for one business period.

    ``recheckAfter`` is ``None`` when the period is frozen: the published
    result stays readable but the scheduler must not re-query or re-analyse it.
    """
    moment = _moment(now)
    active_period_value = normalise(active) or active_period(moment)
    interval = int(interval or os.getenv('COCKPIT_REFRESH_INTERVAL_SECONDS', DEFAULT_INTERVAL))
    grace = DEFAULT_GRACE_DAYS if grace_days is None else int(grace_days)
    period_value = normalise(period)
    if _flag('COCKPIT_PERIOD_REFRESH_ENABLED', True) is False:
        return dict(period=period_value, kind='current', recheckAfter=interval,
                    graceDays=grace, activePeriod=active_period_value)
    if not period_value:
        kind, recheck = 'unknown', interval
    elif period_value == active_period_value or (
            len(period_value) == 4 and period_value == active_period_value[:4]
            and len(active_period_value) == 7):
        kind, recheck = 'current', interval
    elif period_value == _previous(active_period_value) and moment.day <= grace:
        kind, recheck = 'grace', interval
    else:
        earlier = _compare(period_value, active_period_value) < 0
        history = _flag('COCKPIT_HISTORY_REFRESH_ENABLED', history_enabled or False)
        if earlier and history:
            kind = 'historical'
            recheck = int(os.getenv('COCKPIT_HISTORY_REFRESH_SECONDS', DEFAULT_HISTORY_INTERVAL))
        else:
            kind = 'historical' if earlier else 'future'
            recheck = None
    return dict(period=period_value, kind=kind, recheckAfter=recheck,
                graceDays=grace, activePeriod=active_period_value)
