"""Period identity and refresh cadence for cockpit AI publications.

The cockpit keeps one published analysis per business range.  Historical
year/month ranges are analysed once and then frozen; the active range keeps
being re-checked on the configured interval, and the range that just ended
stays refreshable for a short grace window.

"Active" is the period the delivery is currently working on.  Live deployments
follow the customer's business timezone; an explicit ``COCKPIT_ACTIVE_PERIOD``
or ``COCKPIT_PERIOD_MODE=backfill`` may replay a historical range.  The page's
empty delivered filter represents the current business year, while both the
current year and current month are kept warm by the scheduler.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re

DEFAULT_INTERVAL = 900
DEFAULT_HISTORY_INTERVAL = 24 * 60 * 60
DEFAULT_GRACE_DAYS = 7

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


_GRAINS = {'YEAR': 'year', 'Y': 'year', 'ANNUAL': 'year', '年': 'year',
           'MONTH': 'month', 'M': 'month', 'MONTHLY': 'month', '月': 'month'}


def _entries(ui_scope):
    if isinstance(ui_scope, dict):
        return list(ui_scope.items())
    if not isinstance(ui_scope, str):
        return []
    text = ui_scope.strip()
    if text[:1] not in {'[', '{'}:
        return []
    try:
        value = json.loads(text)
    except ValueError:
        return []
    if isinstance(value, dict):
        return list(value.items())
    if isinstance(value, list):
        return [item if isinstance(item, (list, tuple)) and len(item) == 2 else ('', item)
                for item in value]
    return []


def _period_leaves(node, out):
    """Collect (grain, period) for every date-like value in the filter state."""
    if isinstance(node, str):
        found = normalise(node)
        if found:
            out.append(('year' if len(found) == 4 else 'month', found))
    elif isinstance(node, dict):
        for value in node.values():
            _period_leaves(value, out)
    elif isinstance(node, list):
        for value in node:
            _period_leaves(value, out)


def _date_only(value) -> bool:
    """Whether a committed filter value contains dates and nothing else."""
    if isinstance(value, str):
        text = value.strip()
        if text[:1] in {'[', '{'}:
            try:
                return _date_only(json.loads(text))
            except ValueError:
                return False
        return bool(normalise(text))
    if isinstance(value, list):
        return bool(value) and all(_date_only(item) for item in value)
    if isinstance(value, dict):
        # A delivered filter is normally {"label": "时间", "value": "2026-01"}.
        if 'value' in value:
            return _date_only(value.get('value'))
        return False
    return False


def scope_is_period(ui_scope) -> bool:
    """Whether a UI scope changes only the business period/grain.

    A cached period-stage card is a default-filter card.  Returning it for a
    scope that also filters by customer, department or product would silently
    reuse a different business range, so callers must not use the period index
    for those scopes.
    """
    if ui_scope in (None, '', 'default'):
        return True
    entries = _entries(ui_scope)
    if not entries:
        return False
    saw_value = False
    for key, value in entries:
        method = str(key).split(':', 1)[0]
        if method == 'setButtonGrainSelection':
            raw = value.get('value') if isinstance(value, dict) else value
            if isinstance(raw, str):
                try:
                    decoded = json.loads(raw)
                except ValueError:
                    decoded = raw
                if isinstance(decoded, str):
                    raw = decoded
            if not isinstance(raw, str) or str(raw).strip().upper() not in _GRAINS:
                return False
            saw_value = True
            continue
        if method != 'setFilterConditions' or not _date_only(value):
            return False
        saw_value = True
    return saw_value


def period_state(ui_scope, fallback='') -> dict:
    """Resolve the effective (periodType, period) from committed filter state.

    The last grain selection decides whether a year or a month wins; a stale
    month left in the filter map must not override a later year choice.
    """
    candidates, grain = [], ''
    for key, value in _entries(ui_scope):
        method = str(key).split(':', 1)[0]
        if method == 'setButtonGrainSelection':
            raw = value
            if isinstance(raw, dict):
                raw = raw.get('value') or raw.get('code') or raw.get('grain') or ''
            if isinstance(raw, str):
                try:
                    decoded = json.loads(raw)
                except ValueError:
                    decoded = raw
                if isinstance(decoded, str):
                    raw = decoded
            found = _GRAINS.get(str(raw).strip().upper()) if isinstance(raw, str) else ''
            if found:
                grain = found
        _period_leaves(value, candidates)
    for wanted in ([grain] if grain else ['month', 'year']):
        picked = [period for item_grain, period in candidates if item_grain == wanted]
        if picked:
            period = picked[-1]
            if wanted == 'year' and len(period) == 7:
                period = period[:4]
            return dict(period=period, periodType=wanted, grain=grain, source='scope')
    fallback_period = normalise(fallback)
    if fallback_period:
        return dict(period=fallback_period,
                    periodType='year' if len(fallback_period) == 4 else 'month',
                    grain=grain, source='fallback')
    return dict(period='', periodType='', grain=grain, source='none')


def period_range(period):
    """Inclusive ISO date range for a period key, or ``None``."""
    value = normalise(period)
    try:
        if len(value) == 7:
            year, month = int(value[:4]), int(value[5:])
            start = dt.date(year, month, 1)
            end = dt.date(year + (month == 12), month % 12 + 1, 1) - dt.timedelta(days=1)
            return start.isoformat(), end.isoformat()
        if len(value) == 4:
            return f'{value}-01-01', f'{value}-12-31'
    except ValueError:
        return None
    return None


def period_of_scope(ui_scope, fallback='') -> str:
    """Business period implied by the committed filter scope."""
    return period_state(ui_scope, fallback)['period']


DEFAULT_BUSINESS_YEAR = '2025'


def business_year() -> str:
    """Business year the delivery is scoped to.

    The cockpit is delivered against one closed business year.  Wall-clock
    rollover must not silently move the default range into a later year, so
    the year is fixed here and can only be changed explicitly through
    ``COCKPIT_BUSINESS_YEAR``.
    """
    match = _YEAR_RE.search(os.getenv('COCKPIT_BUSINESS_YEAR', '') or '')
    return match.group(1) if match else DEFAULT_BUSINESS_YEAR


def default_period(now=None, period_type: str = '') -> str:
    """Period used when the delivered date filter is empty.

    The delivered dashboard ships an empty filter.  An empty filter resolves
    to the fixed business year rather than the wall-clock year.  A month-grain
    selection without an explicit date resolves to the last month of that
    year.  An explicit backfill period still wins so operators can replay a
    named range without changing the delivered metadata.
    """
    override = normalise(os.getenv('COCKPIT_ACTIVE_PERIOD', ''))
    grain = str(period_type or '').strip().lower()
    if grain == 'month':
        return override if len(override) == 7 else f'{business_year()}-12'
    if override:
        return override[:4] if len(override) == 7 else override
    return business_year()


def period_mode() -> str:
    """``live`` maintains the business current period; ``backfill`` replays one."""
    value = (os.getenv('COCKPIT_PERIOD_MODE') or 'live').strip().lower()
    return 'backfill' if value == 'backfill' else 'live'


def active_period(now=None) -> str:
    """The period the deployment is currently responsible for.

    The delivery is pinned to :func:`business_year` instead of the wall clock,
    so a 2026 wall-clock date cannot pull the cockpit onto a later year.
    ``COCKPIT_ACTIVE_PERIOD`` still wins when an operator replays a range.
    """
    override = normalise(os.getenv('COCKPIT_ACTIVE_PERIOD', ''))
    if override:
        return override
    return business_year()


def business_timezone():
    name = os.getenv('COCKPIT_BUSINESS_TIMEZONE', 'Asia/Shanghai')
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:  # pragma: no cover - missing tz database on minimal images
        return dt.timezone(dt.timedelta(hours=8))


def _moment(now):
    zone = business_timezone()
    if now is None:
        return dt.datetime.now(zone)
    if isinstance(now, dt.datetime):
        return now if now.tzinfo else now.replace(tzinfo=zone)
    return dt.datetime.fromtimestamp(float(now), zone)


def _flag(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def previous_periods(active: str) -> list[str]:
    """Periods that just ended and may still be settling.

    A new month needs both the previous month and, in January, the previous
    year: a monthly and an annual analysis are separate cache entries.
    """
    try:
        if len(active) == 7:
            year, month = int(active[:4]), int(active[5:])
            if month == 1:
                return [f'{year - 1:04d}-12', f'{year - 1:04d}']
            return [f'{year:04d}-{month - 1:02d}']
        if len(active) == 4:
            return [f'{int(active) - 1:04d}']
    except ValueError:
        return []
    return []


def _previous(active: str) -> str:
    values = previous_periods(active)
    return values[0] if values else ''


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
    if grace_days is None:
        raw = os.getenv('COCKPIT_PERIOD_GRACE_DAYS')
        grace_days = int(raw) if raw not in (None, '') else DEFAULT_GRACE_DAYS
    grace = int(grace_days)
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
    elif period_value in previous_periods(active_period_value) and moment.day <= grace:
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


def period_catalog(now=None) -> list[str]:
    """Periods the deployment must keep warm.

    ``COCKPIT_PREHEAT_PERIODS`` is a comma separated list (``2025,2025-01``).
    The active business month and its year are always included, followed by
    the settling period inside the grace window and then explicit backfill
    periods.  A month rollover therefore does not require an environment
    change or a browser visit before the new range is prepared.
    """
    values = []
    moment = _moment(now)
    active = normalise(active_period(moment))
    if active:
        values.append(active)
        if len(active) == 7:
            values.append(active[:4])
        for previous in previous_periods(active):
            policy = policy_for(previous, now=moment, active=active)
            if policy['kind'] == 'grace' and previous not in values:
                values.append(previous)
    for raw in (os.getenv('COCKPIT_PREHEAT_PERIODS') or '').split(','):
        period = normalise(raw)
        if period and period not in values:
            values.append(period)
    return values
