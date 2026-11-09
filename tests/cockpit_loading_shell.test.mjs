import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const html = await readFile(new URL('../bi_agent/web/static/cockpit/index.html', import.meta.url), 'utf8');
const source = await readFile(new URL('../bi_agent/web/static/cockpit/cockpit.js', import.meta.url), 'utf8');

test('first paint has one board-shaped skeleton instead of duplicate loading text', () => {
  assert.equal((html.match(/id="cockpit-boot"/g) || []).length, 1);
  assert.match(html, /id="cockpit-boot" class="cockpit-loading"/);
  assert.match(html, /cockpit-loading__kpis/);
  assert.match(html, /cockpit-loading__card--chart/);
  assert.match(html, /<cockpit-loading v-else-if="loading"/);
  assert.doesNotMatch(html, /正在加载正式看板配置/);
  assert.doesNotMatch(html, /style="padding:24px;/);
});

test('layout configuration does not wait for startup history or status', () => {
  const start = source.indexOf('async function loadRuntime()');
  const end = source.indexOf('const retryRuntime', start);
  assert.notEqual(start, -1);
  assert.notEqual(end, -1);
  const block = source.slice(start, end);
  assert.match(block, /loadJson\(`\$\{apiBase\}\/engines`\)/);
  assert.match(block, /loadJson\(`\$\{apiBase\}\/data\/config`\)/);
  assert.doesNotMatch(block, /\/startup/);
  assert.doesNotMatch(block, /Promise\.all\(\[loadJson\(runtimeUrl\),loadJson/);
});

test('Vue removes the static shell before awaiting runtime configuration', () => {
  const start = source.indexOf('onMounted(() => {');
  const end = source.indexOf('onBeforeUnmount', start);
  assert.notEqual(start, -1);
  assert.notEqual(end, -1);
  const block = source.slice(start, end);
  assert.ok(block.indexOf("document.getElementById('cockpit-boot')?.remove()") < block.indexOf('bootRuntime()'));
  assert.doesNotMatch(block.slice(block.indexOf('bootRuntime()')), /cockpit-boot.*remove/);
});

test('history cards and publication status are background reads after the board mounts', () => {
  assert.match(source, /install\(null\);\s*\n\s*if\(analysisEngine==='main'\)\{\s*\n\s*loadCurrentHistoryCards\(\);\s*\n\s*if\(!frozenAnnualMode\)statusPoller\?\.start\(50\)/);
  assert.match(source, /const cards=await pageCache\.cards\(\)/);
  assert.match(source, /publications\?\.preload\(cards\.items\|\|\{\}\)/);
});

test('history-card loader stays in scope across the main-engine block', () => {
  const block = source.indexOf("if(analysisEngine==='main') {\n            pageCache=createPageCache");
  const declaration = source.indexOf('async function loadCurrentHistoryCards()');
  const call = source.indexOf("if(analysisEngine==='main'){\n            loadCurrentHistoryCards();");
  assert.notEqual(block, -1);
  assert.notEqual(declaration, -1);
  assert.notEqual(call, -1);
  assert.ok(declaration < block, 'loader declaration must not be block-scoped inside the main-engine branch');
  assert.ok(block < call);
});

test('configuration failure exposes a retry action instead of an endless loader', () => {
  assert.match(html, /class="cockpit-state__retry"/);
  assert.match(html, /@click="retryRuntime"/);
  assert.match(source, /const retryRuntime = \(\) => location\.reload\(\)/);
  assert.match(source, /error\.value = `看板配置加载失败：\$\{cause\.message \|\| cause\}`/);
});

test('host does not expose delivered metadata diagnostics in the dashboard UI', () => {
  assert.doesNotMatch(html, /元数据缺失与渲染限制/);
  assert.doesNotMatch(html, /cockpit-gap-report/);
  assert.doesNotMatch(source, /metadataSummary/);
  assert.doesNotMatch(source, /const gaps = computed/);
});

test('default SDK filters and repeated snapshots cannot remount the board in a loop', () => {
  assert.match(source, /isUserAction:isScopeUserAction/);
  assert.match(source, /event\?\.target\?\.closest\?\.\(SCOPE_CONTROL\)/);
  assert.match(source, /installedSnapshotKey/);
  assert.match(source, /incomingKey===installedSnapshotKey&&liveDataClient/);
  assert.match(source, /onSnapshotMiss:\(\)=>\{fullSnapshot=null;pageState\.cached=false;pageState\.displayStale=true;\}/);
  assert.doesNotMatch(source, /onSnapshotMiss:\(\)=>\{[\s\S]{0,300}changeScope\(currentUiScope,true\)/);
  assert.match(source, /scopeKey===lastScopeRequestKey&&now-lastScopeRequestAt/);
  assert.match(source, /settleMissingSlotStages\(\)/);
  assert.doesNotMatch(source, /尚无可用分析结果，服务端正在补充当前口径数据/);
  assert.match(source, /已取得部分AP数据，正在分析；未返回的查询会在卡片中列明/);
  assert.match(source, /slot\?\.update\?\.active\|\|/);
  assert.match(source, /当前口径暂无可用的已取数证据，等待下一次数据更新/);
});

test('only a committed page scope change starts analysis after its receipts are ready', () => {
  assert.match(source, /onInvalidate:\(\)=>\{\}/);
  assert.match(source, /scopeNeedsAnalysis=!frozenAnnualMode/);
  assert.match(source, /if\(scopeNeedsAnalysis\)\{[\s\S]{0,240}ensureAnalysis\(stage,true,true\)/);
  assert.doesNotMatch(source, /onInvalidate:[\s\S]{0,220}ensureAnalysis\(stage\)/);
});

test('combined analysis reuses every upstream stage query when AP is partial', () => {
  assert.match(source, /function analysisDataStages\(stage\) \{/);
  assert.match(source, /stage === 'combined' \? \['opportunity', 'order', 'shipment'\] : \[stage\]/);
  assert.match(source, /scope\(\{partial:true, stages:analysisDataStages\(stage\)\}\)/);
  assert.equal((source.match(/ready\(\{partial:true, ?stages:analysisDataStages\(stage\)\}\)/g) || []).length, 2);
  assert.doesNotMatch(source, /(?:scope|ready)\(\{partial:true, ?stages:\[stage\]\}\)/);
});

test('background publication updates replace cards in place instead of remounting the board', () => {
  assert.doesNotMatch(source, /onSnapshot:snapshot=>\{[\s\S]{0,500}install\(snapshot,true\)/)
  assert.doesNotMatch(source, /if\(status\.publicationVersion[\s\S]{0,700}install\(snapshot,true\)/)
  assert.match(source, /onSnapshot:snapshot=>\{[\s\S]{0,300}fullSnapshot=snapshot;[\s\S]{0,300}publications\?\.preload/)
  assert.match(source, /fullSnapshot=snapshot;\s*\n\s*if\(snapshot\.items\)publications\?\.preload/)
  assert.match(source, /updateSnapshotInPlace\(snapshot\)/)
  assert.match(source, /liveDataClient\.applySnapshot\?\.\(snapshot\.entries\|\|\[\]\)/)
  assert.match(source, /rawRuntime\.setComponentData\(component\.id,value,path\)/)
  assert.match(source, /kind:'tab',containerId:tabs\.id,tabId:tab,templateId/)
  assert.match(source, /pageCache\.publish\(client,items,uiScope,undefined,true\)/)
  assert.match(source, /\[cockpit-page-publish\][\s\S]{0,220}error:'',refreshing:false,updateStatus:'waiting'/)
})
