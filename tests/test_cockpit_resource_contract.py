"""Integrity checks for externally published artifacts and frozen hand-off metadata."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]/'bi_agent/web/static/cockpit'

def test_vendor_manifest_matches_local_artifacts():
    vendor=ROOT/'vendor'
    manifest=json.loads((vendor/'resources.json').read_text())
    assert manifest['sourceCommit']=='ebe55d0dce39212f6b1b31c62a1ae485b6bf8da5'
    assert manifest['metadataCommit']=='cd8d71fd6278dcf9630043d00bb95e62d97b347a'
    for r in manifest['resources']:
        data=(vendor/r['file']).read_bytes()
        assert hashlib.sha256(data).hexdigest()==r['sha256']
        assert len(data)==r['bytes']
    html=(ROOT/'index.html').read_text()
    assert 'pro-ui.min.css?v=b1ee836d' in html
    assert 'pro-bi-ui.min.js?v=10f624d9' in html
    sdk=(vendor/'pro-bi-ui.min.js').read_text()
    assert 'if(!t||!t.get("group"))return;t.fitView(' in sdk
    assert 'updateComponentMeta' in sdk and 'setTemplateRegistry' in sdk
    assert 'data-dashboard-theme="white"' in html
    css=(ROOT/'cockpit.css').read_text()
    assert '--dashboard-canvas-bg:#fff' in css
    assert '--dashboard-component-bg:#fff' in css

def test_imported_metadata_hashes_and_three_tabs():
    folder=ROOT/'metadata/iba-demo-1021'
    source=json.loads((folder/'source.json').read_text())
    assert source['branch']=='feature/demo_1021'
    assert source['commit']=='cd8d71fd6278dcf9630043d00bb95e62d97b347a'
    assert source['umdCommit']=='ebe55d0dce39212f6b1b31c62a1ae485b6bf8da5'
    assert source['activateRules']==6
    for file in source['files']:
        assert hashlib.sha256((folder/file['file']).read_bytes()).hexdigest()==file['sha256']
    roots=json.loads((folder/'components.json').read_text())
    registry=json.loads((folder/'template-registry.json').read_text())
    tabs=next(c for c in roots if c['type']=='tab-container')['baseConfig']['tabs']
    assert [t['label'] for t in tabs]==['经营看板','运营360整体分析','穿透式问题分析']
    assert all(t['templateId'] in registry for t in tabs)
    assert source['totalComponents']==len(roots)+sum(len(t['components']) for t in registry.values())
    rules=json.loads((folder/'activate-rules.json').read_text())
    assert len(rules)==6
    sales=next(rule for rule in rules if rule['id']=='activate-luv1ff6x')
    assert sales['source']['actionKey']=='1793158849339'
    assert sales['actions'][1]['nodeId']=='2109840325158682625'
    assert sales['actions'][1]['nodeName']=='商机获取'


def test_risk_header_counts_follow_published_detail_cards():
    source=(ROOT/'cockpit.js').read_text()
    targets={
        'progress-y5dumxio': ('opportunity-risk','tab-bc6wp3k2','2112001069107167233'),
        'progress-91j3rt9a': ('shipment-risk-summary','tab-bc6wp3k2','2112001069107167233'),
        'progress-ynh9zsng': ('opportunity-risk','tab-211tc4o0','2112434004503347202'),
        'progress-zl0egumz': ('shipment-risk-summary','tab-211tc4o0','2112434004503347202'),
    }
    for component_id,(slot_id,tab_id,template_id) in targets.items():
        assert component_id in source
        assert slot_id in source
        assert tab_id in source
        assert template_id in source
    assert "const RISK_COUNT_PATH = ['headerActions', 0, 'label']" in source
    assert 'const causes=slot.payload.result.causes' in source
    assert '`${count}条风险`' in source
    assert 'runtime.updateComponentMeta(target.componentId,RISK_COUNT_PATH,label' in source

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
    reported={(i['templateId'],i['componentId'],i['missingChildId'])
              for i in source['knownIssues'] if i.get('missingChildId')}
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
    assert 'new URLSearchParams({id: identityId, engine: analysisEngine})' in js
    assert '?${search}' in js
    assert "params.get('role')" not in js
    assert '"role"' not in js and "'role'" not in js
    assert '@@COCKPIT_VERSION@@' in html
    assert 'pdt-release-2109836674373566465' in js
    assert '`${apiBase}/analyses`' in js
    assert "source: analysisEngine === 'main' || baselineId ? 'service' : 'prototype'" in js
    assert 'ensureAnalysis' in js and 'requestIdleCallback' in js
    assert 'PREFETCH_STAGES' in js
    assert ':bi-adapters="biAdapters"' in html
    assert ':activate-rules="runtime.activateRules"' in html
    assert 'postAnalysisDataQueryBatch' not in js
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
    assert sum(len(page['insights']) for page in runtime['pages'].values())==15
    assert len(runtime['pages']['operations']['insights'])==5
    assert len(runtime['pages']['analysis']['insights'])==10
    assert ':insights="pageInsights"' in html
    assert 'v-slot:[slot_name(insight)]' in html
    assert "app.component('cockpit-insight', CockpitInsight)" in js


def test_delivered_insight_slots_use_live_analysis_instead_of_static_copy():
    js=(ROOT/'cockpit.js').read_text()
    assert 'insightBundleUrl' in js
    assert 'import(insightBundleUrl)' in js
    assert ':analysis="slotAnalysis"' in js
    assert 'slotPublication(props.insight.id)' in js
    assert ':status="state.status"' in js
    assert '@retry="reload"' in js
    components=ROOT/'insight-components'
    bundle=(components/'index.js').read_text()
    assert 'new URL(import.meta.url).search' in bundle
    assert 'window.InsightRuntime' in bundle
    shared=(components/'shared.js').read_text()
    assert 'export function createStageRiskComponent' in shared
    for marker in ('stage-risk-analysis__overview','stage-risk-analysis__tag--cause',
                   'stage-risk-analysis__owner','stage-risk-analysis__time'):
        assert marker in shared
    stage_risk={'opportunity-risk':'商机获取','order-risk-summary':'订单接收','shipment-risk-summary':'发货'}
    tables={'star-product-order-list','affected-order-list','overdue-order-list'}
    for name in ('bid-status-note','quote-summary','bid-summary','order-sign-summary',
                 'sales-shipment-issues','opportunity-risk','opportunity-coverage-note',
                 'order-risk-summary','shipment-risk-summary','shipment-overdue-note',
                 'shipment-cause-breakdown','shipment-task-order',*tables):
        source=(components/name/'index.js').read_text()
        assert 'window.InsightRuntime' in source
        if name in tables:
            assert "from '../table-runtime.js'" in source
            assert source.count("from '../") == 1
        else:
            assert "from '../" not in source
        assert '静态文案' not in source
        if name in tables:
            assert 'createTableInsight' in source
            assert 'tableKey:' in source
        elif name in stage_risk:
            assert 'createStageRiskComponent' in source
            assert f"fallbackStage: '{stage_risk[name]}'" in source
        else:
            assert 'insight-runtime-state' in source
            assert 'props: insightProps' in source
            assert 'useInsight(props, emit)' in source


def test_analysis_flow_preserves_delivered_graph_and_shared_risk_markup():
    runtime=json.loads((ROOT/'metadata/runtime.json').read_text())
    graph=next(component for component in runtime['pages']['analysis']['components']
               if component['id']=='mini-cpgraph-93j6k86p')
    assert graph['title']=='销售额口径 · 三节点头盔图（商机获取 → 订单接收 → 发货）'
    assert {rule['nodeId'] for rule in graph['graphConfig']['graphTemplateSwitchRules']}=={
        '2109840325158682625','2109840573998350338','2109840696539136002',
    }

    captured=json.loads((ROOT/'metadata/pdt-release-2109836674373566465/data-snapshots.json').read_text())
    sales=[value for key,value in captured['requests'].items()
           if 'SALES_CALIBER' in key and '/api/gateway2/x360/v1/graphs/helmet-view' in key]
    assert len(sales)==1
    assert [node['name'] for node in sales[0]['response']['data']['nodes']]==[
        '商机获取','订单接收','发货',
    ]

    js=(ROOT/'cockpit.js').read_text()
    assert "params.flowCode === 'SALES_CALIBER'" in js
    css=(ROOT/'cockpit.css').read_text()
    for selector in ('stage-risk-analysis__card--risk','stage-risk-analysis__card--cause',
                     'stage-risk-analysis__card--suggest','stage-risk-analysis__action',
                     'stage-risk-analysis__overview','stage-risk-analysis__tag--cause'):
        assert selector in css
    assert 'padding:14px 16px 12px' in css
    assert 'border-left:3px solid #cf1322' in css
