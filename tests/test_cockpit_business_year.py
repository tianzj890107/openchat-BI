import os
import re
from pathlib import Path

from bi_agent.cockpit.query_capabilities import implemented_stage_requests

ROOT = Path(__file__).resolve().parents[1]


def _html(monkeypatch, **env):
    from bi_agent.web import app as web
    for key in ('COCKPIT_BUSINESS_YEAR', 'COCKPIT_ACTIVE_PERIOD'):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return web._cockpit_html('analysis').body.decode('utf-8')


def test_page_carries_the_configured_business_year(monkeypatch):
    html = _html(monkeypatch)
    assert '<meta name="cockpit-business-year" content="2025">' in html
    assert '@@' not in html
    assert '<meta name="cockpit-business-year" content="2024">' in _html(
        monkeypatch, COCKPIT_BUSINESS_YEAR='2024')


def test_first_paint_year_comes_from_the_server_not_the_browser_clock():
    source = (ROOT / 'bi_agent/web/static/cockpit/cockpit.js').read_text(encoding='utf-8')
    assert "meta[name=\"cockpit-business-year\"]" in source
    assert re.search(r"let defaultPeriod = /\^\\d\{4\}\$/\.test\(configuredYear\) \? configuredYear", source)


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
        assert dates[0]['value'][0].startswith('2025-01-01')
        assert '2026' not in dates[0]['value'][0]
