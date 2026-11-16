import os
import re
from pathlib import Path

from bi_agent.cockpit.query_capabilities import implemented_stage_requests

ROOT = Path(__file__).resolve().parents[1]


def _html(monkeypatch, **env):
    from bi_agent.web import app as web
    for key in ('COCKPIT_BUSINESS_YEAR', 'COCKPIT_ACTIVE_PERIOD', 'COCKPIT_SNAPSHOT_DATE'):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return web._cockpit_html('analysis').body.decode('utf-8')


def test_page_carries_the_configured_business_period(monkeypatch):
    html = _html(monkeypatch)
    assert '<meta name="cockpit-business-period" content="2025-10">' in html
    assert '@@' not in html
    assert '<meta name="cockpit-business-period" content="2024-10">' in _html(
        monkeypatch, COCKPIT_BUSINESS_YEAR='2024')


def test_page_carries_the_frozen_snapshot_date_for_the_header(monkeypatch):
    assert '<meta name="cockpit-snapshot-date" content="2025-10-31">' in _html(monkeypatch)
    assert '<meta name="cockpit-snapshot-date" content="2025-09-30">' in _html(
        monkeypatch, COCKPIT_SNAPSHOT_DATE='2025-09-30')


def test_first_paint_period_comes_from_the_server_not_the_browser_clock():
    source = (ROOT / 'bi_agent/web/static/cockpit/cockpit.js').read_text(encoding='utf-8')
    assert "meta[name=\"cockpit-business-period\"]" in source
    assert re.search(r"let defaultPeriod = /\^\\d\{4\}\(-\\d\{2\}\)\?\$/\.test\(configuredPeriod\)", source)


def test_asset_version_changes_when_a_card_component_changes(monkeypatch):
    shared = ROOT / 'bi_agent/web/static/cockpit/insight-components/shared.js'
    before = re.search(r'name="cockpit-version" content="(\d+)"', _html(monkeypatch)).group(1)
    stat = shared.stat()
    try:
        future = stat.st_mtime + 10_000_000
        os.utime(shared, (stat.st_atime, future))
        after = re.search(r'name="cockpit-version" content="(\d+)"', _html(monkeypatch)).group(1)
    finally:
        os.utime(shared, (stat.st_atime, stat.st_mtime))
    assert after != before


def test_annual_stage_queries_are_bounded_to_the_requested_year():
    plans = implemented_stage_requests('order', '2025')
    assert plans
    for plan in plans:
        dates = [child for child in plan['commonConfig']['filters']['children']
                 if child['operator'] == {'code': 'BETWEEN', 'type': 'DATE'}]
        assert len(dates) == 1
        assert dates[0]['value'] == ['2025-01-01', '2025-10-31']


def test_period_range_stops_at_the_delivery_snapshot():
    from bi_agent.cockpit.periods import period_range
    assert period_range('2025') == ('2025-01-01', '2025-10-31')
    assert period_range('2025-10') == ('2025-10-01', '2025-10-31')
    assert period_range('2025-09') == ('2025-09-01', '2025-09-30')
    assert period_range('2024') == ('2024-01-01', '2024-12-31')
    assert period_range('2025-11') is None
    assert period_range('2026') is None


def test_period_range_follows_the_snapshot_override(monkeypatch):
    from bi_agent.cockpit.periods import period_range
    monkeypatch.setenv('COCKPIT_SNAPSHOT_DATE', '2025-09-30')
    assert period_range('2025') == ('2025-01-01', '2025-09-30')
    assert period_range('2025-10') is None
    assert period_range('2025-09') == ('2025-09-01', '2025-09-30')
