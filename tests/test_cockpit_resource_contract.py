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
    assert 'pro-ui.min.css?v=ba407022' in html
    assert 'pro-bi-ui.min.js?v=981e7d98' in html

def test_imported_metadata_hashes_and_three_tabs():
    folder=ROOT/'metadata/iba-demo-1021'
    source=json.loads((folder/'source.json').read_text())
    assert source['branch']=='feature/demo_1021'
    for file in source['files']:
        assert hashlib.sha256((folder/file['file']).read_bytes()).hexdigest()==file['sha256']
    roots=json.loads((folder/'components.json').read_text())
    registry=json.loads((folder/'template-registry.json').read_text())
    tabs=next(c for c in roots if c['type']=='tab-container')['baseConfig']['tabs']
    assert [t['label'] for t in tabs]==['全局经营看板','运营360整体分析','穿透式问题分析']
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


def test_prototype_layout_manifest_is_traceable_and_shell_free():
    fixture=json.loads((ROOT.parents[2]/'cockpit/fixtures/v3-prototype.json').read_text())
    manifest=json.loads((ROOT/'layout/views.json').read_text())
    assert manifest['source']=={
        'file': fixture['_source']['file'],
        'sha256': fixture['_source']['sha256'],
    }
    expected={'overview','overview-sales','overview-volume','operations','analysis-shipment'}
    assert expected<=set(manifest['views'])
    assert len(manifest['gaps'])==119
    assert all(manifest['views'][name] for name in expected)
    for name,html in manifest['views'].items():
        assert 'onclick=' not in html
        assert 'javascript:' not in html
        assert '<aside' not in html
        assert '<nav' not in html
        assert '<iframe' not in html
        ids=[gap['id'] for gap in manifest['gaps'] if gap['view']==name]
        assert len(ids)==len(set(ids))
    assert any(gap['key']=='helmet' for gap in manifest['gaps'])
    assert any(gap['key']=='stage-tile' and gap['view']=='operations' for gap in manifest['gaps'])
    assert any(gap['key']=='ai-card' and gap['view']=='analysis-shipment' for gap in manifest['gaps'])
