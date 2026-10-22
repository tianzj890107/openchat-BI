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
    assert 'pro-bi-ui.min.js?v=011269f8' in html

def test_imported_metadata_hashes_and_three_tabs():
    folder=ROOT/'metadata/iba-demo-1021'
    source=json.loads((folder/'source.json').read_text())
    assert source['branch']=='feature/demo_1021'
    assert source['commit']=='37975c7a03719c037b4acca70c38b50fb68f4516'
    for file in source['files']:
        assert hashlib.sha256((folder/file['file']).read_bytes()).hexdigest()==file['sha256']
    roots=json.loads((folder/'components.json').read_text())
    registry=json.loads((folder/'template-registry.json').read_text())
    tabs=next(c for c in roots if c['type']=='tab-container')['baseConfig']['tabs']
    assert [t['label'] for t in tabs]==['经营看板','运营360整体分析','穿透式问题分析']
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
    assert set(runtime['pages'])=={'overview','operations','analysis'}
    assert runtime['pages']['overview']['title']=='经营看板'
    assert len(runtime['templates'])==13
    prohibited={'cockpit-gap','cockpit-risk-list'}
    html=(ROOT/'index.html').read_text()
    js=(ROOT/'cockpit.js').read_text()
    assert 'prototype.css' not in html
    assert 'views.json' not in html and 'views.json' not in js
    assert 'ProBiDashboard' in js
    assert 'installSnapshots' in js and 'data-snapshots.json' in js
    for spec in list(runtime['pages'].values()) + list(runtime['templates'].values()):
        assert all(c['type'] not in prohibited for c in spec['components'])


def test_fuxi_identity_and_missing_risk_actions_are_wired():
    js=(ROOT/'cockpit.js').read_text()
    html=(ROOT/'index.html').read_text()
    assert "params.get('id')" in js
    assert 'new URLSearchParams({id: identityId})' in js
    assert '?${search}' in js
    assert "params.get('role')" not in js
    assert '"role"' not in js and "'role'" not in js
    assert '@@COCKPIT_VERSION@@' in html
    assert 'pdt-release-2109836674373566465' in js
    assert 'insight-components/index.js' in js
    assert 'window.InsightComponents' in js
    assert ':bi-adapters="biAdapters"' in html
    assert 'layout/' not in js and 'views.json' not in js


def test_three_top_tabs_and_static_proui_dashboard_are_present():
    js=(ROOT/'cockpit.js').read_text()
    html=(ROOT/'index.html').read_text()
    runtime=json.loads((ROOT/'metadata/runtime.json').read_text())
    assert 'class="pro-tabs pro-tabs--top cockpit-tabs"' not in html
    assert ':is="dashboardComponent"' in html
    for label in ('经营看板','运营360整体分析','穿透式问题分析'):
        assert label in js
    assert "return PAGES[page] ? page : 'overview'" in js
    assert "fetch(url" in js
    assert "ProUIBi?.ProBiDashboard" in js
    assert ':components="dashboard.components"' in html
    assert ":template-registry=\"runtime.templates\"" in html
    assert ':title="dashboard.name"' in html and 'show-header-title' in html
    assert 'mode="build"' not in html
    assert 'mode="release"' in html
    assert runtime['dashboard']['components'][1]['type']=='tab-container'
    assert [t['label'] for t in runtime['dashboard']['components'][1]['baseConfig']['tabs']]==[
        '经营看板','运营360整体分析','穿透式问题分析',
    ]
    assert runtime['pages']['operations']['components']
    assert runtime['pages']['analysis']['components']
    assert sum(len(page['insights']) for page in runtime['pages'].values())==12
    assert len(runtime['pages']['operations']['insights'])==4
    assert len(runtime['pages']['analysis']['insights'])==8
    assert ':insights="pageInsights"' in html
    assert 'v-slot:[slot_name(insight)]' in html
    assert "app.component('cockpit-insight', DeliveredInsight)" in js
