"""Integrity checks for externally published artifacts and frozen hand-off metadata."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]/'bi_agent/web/static/cockpit'

def test_vendor_manifest_matches_local_artifacts():
    vendor=ROOT/'vendor'
    manifest=json.loads((vendor/'resources.json').read_text())
    for r in manifest['resources']:
        data=(vendor/r['file']).read_bytes()
        assert hashlib.sha256(data).hexdigest()==r['sha256']
        assert len(data)==r['bytes']
    html=(ROOT/'index.html').read_text()
    assert 'pro-ui.min.css?v=b1ee836d' in html
    assert 'pro-bi-ui.min.js?v=c38cbf36' in html

def test_imported_metadata_hashes_and_four_tabs():
    folder=ROOT/'metadata/iba-demo-1021'
    source=json.loads((folder/'source.json').read_text())
    assert source['branch']=='feature/demo_1021'
    assert source['commit']=='7e45062deaebde11bb267539ff9a32f324bac4c6'
    for file in source['files']:
        assert hashlib.sha256((folder/file['file']).read_bytes()).hexdigest()==file['sha256']
    roots=json.loads((folder/'components.json').read_text())
    registry=json.loads((folder/'template-registry.json').read_text())
    tabs=next(c for c in roots if c['type']=='tab-container')['baseConfig']['tabs']
    assert [t['label'] for t in tabs]==['储能产品线整体经营分析','全局经营看板','运营360整体分析','穿透式问题分析']
    assert all(t['templateId'] in registry for t in tabs)
    assert source['totalComponents']==len(roots)+sum(len(t['components']) for t in registry.values())

def test_upstream_missing_children_are_reported_without_mutating_metadata():
    folder=ROOT/'metadata/iba-demo-1021'
    source=json.loads((folder/'source.json').read_text())
    registry=json.loads((folder/'template-registry.json').read_text())
    actual=set()
    for tid,t in registry.items():
        ids={c['id'] for c in t['components']}
        for c in t['components']:
            for child in c.get('children',[]):
                if child not in ids:actual.add((tid,c['id'],child))
    reported={(i['templateId'],i['componentId'],i['missingChildId']) for i in source['knownIssues']}
    assert actual==reported


def test_prototype_layout_is_retired_and_runtime_contains_native_components():
    assert not (ROOT/'layout').exists()
    runtime=json.loads((ROOT/'metadata/runtime.json').read_text())
    assert runtime['renderer']=='ProBiDashboard'
    assert set(runtime['pages'])=={'home','overview','operations','analysis'}
    assert runtime['pages']['overview']['title']=='全局经营看板'
    assert len(runtime['templates'])==15
    prohibited={'cockpit-gap','cockpit-risk-list'}
    html=(ROOT/'index.html').read_text()
    js=(ROOT/'cockpit.js').read_text()
    assert 'prototype.css' not in html
    assert 'views.json' not in html and 'views.json' not in js
    assert 'ProBiDashboard' in js
    assert 'mockData' not in js
    for spec in list(runtime['pages'].values()) + list(runtime['templates'].values()):
        assert all(c['type'] not in prohibited for c in spec['components'])


def test_fuxi_identity_and_missing_risk_actions_are_wired():
    js=(ROOT/'cockpit.js').read_text()
    html=(ROOT/'index.html').read_text()
    assert "params.get('id')" in js
    assert "new URLSearchParams({id: identityId, ...extra})" in js
    assert 'proui-dashboard-v4' in html
    assert "source: 'prototype'" in js
    assert 'layout/' not in js and 'views.json' not in js


def test_four_top_tabs_and_static_proui_dashboard_are_present():
    js=(ROOT/'cockpit.js').read_text()
    html=(ROOT/'index.html').read_text()
    runtime=json.loads((ROOT/'metadata/runtime.json').read_text())
    assert 'class="pro-tabs pro-tabs--top cockpit-tabs"' in html
    for label in ('首页','全局经营看板','运营 360 整体分析','穿透式问题分析'):
        assert label in js
    assert "{id: 'home', title: '首页'}" in js
    assert "return PAGE_BY_ID[declared] ? declared : 'overview'" in js
    assert 'homePageSpec' not in js
    assert 'pro-tabs__active-bar' in html
    assert "fetchJson(runtimeUrl)" in js
    assert "window.ProUIBi?.ProBiDashboard" in js
    assert ':components="boardPage.components"' in html
    assert ":template-registry=\"runtime.templates\"" in html
    assert ':insights="pageInsights"' in html
    assert 'cockpit-insight' in html and 'cockpit-insight' in js
    assert "mode=\"build\"" in html
    assert runtime['pages']['home']['id']=='home'
    assert runtime['pages']['overview']['id']=='overview'
    assert runtime['pages']['operations']['components']
    assert runtime['pages']['analysis']['components']
    assert [s['id'] for s in runtime['pages']['home']['insights']]==['focus-risks']
    assert len(runtime['pages']['operations']['insights'])==7
    assert len(runtime['pages']['analysis']['insights'])==9
