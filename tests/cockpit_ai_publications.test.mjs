import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createAiPublicationClient} from '../bi_agent/web/static/cockpit/ai-publication-client.js';

const envelope = slots => ({scopeKey:'default',requestedScope:'default',version:'v1',
  expectedCount:15,readyCount:Object.keys(slots).length,missingCount:15-Object.keys(slots).length,
  updatingCount:0,update:{status:'idle'},slots});

test('AI publication client reads persisted slots and never calls the analysis endpoint', async () => {
  const urls = [];
  const values = [];
  const client = createAiPublicationClient({apiBase:'/api/cockpit', id:1,
    request:async url => {urls.push(url);return {ok:true,json:async()=>envelope({})};},
    onUpdate:value=>values.push(value)});
  const value = await client.load({uiScope:'default',preserve:false,force:true});
  assert.equal(value.expectedCount,15);
  assert.equal(urls.length,1);
  assert.match(urls[0],/\/ai-publications\?/);
  assert.doesNotMatch(urls[0],/analyses|refresh/);
  assert.equal(values.length,1);
});

test('AI publication client keeps the caller store intact on read failure', async () => {
  let failure = null;
  const client = createAiPublicationClient({apiBase:'/api/cockpit', id:1,
    request:async()=>({ok:false,json:async()=>({detail:'数据库暂不可用'})}),
    onError:error=>{failure=error;}});
  const value = await client.load({uiScope:'default'});
  assert.equal(value,null);
  assert.match(failure.message,/数据库暂不可用/);
});

test('cockpit owns a slot store outside the board and skips analysis for ready slots', async () => {
  const source = await readFile(new URL('../bi_agent/web/static/cockpit/cockpit.js', import.meta.url),'utf8');
  assert.match(source,/aiPublicationStore = reactive/);
  assert.match(source,/ensureSlotAnalysis\(props\.insight\.id,stage\.value\)/);
  assert.match(source,/if\(hasPublishedSlot\(slotId\)\) return stateFor\(stage\)\.item;/);
  assert.match(source,/markAiPublicationsStale\(notice\)/);
  assert.doesNotMatch(source,/aiPublicationStore\.slots\s*=\s*\{\s*\}/);
});

test('persisted AI cards start before runtime and mark default fallback cards stale', async () => {
  const source = await readFile(new URL('../bi_agent/web/static/cockpit/cockpit.js', import.meta.url),'utf8');
  assert.match(source,/function startAiPublications\(\)/);
  assert.match(source,/startAiPublications\(\);\s*\n\s*document\.title/);
  assert.match(source,/scopeMismatch=value\.scopeMatch===false/);
  assert.match(source,/以下仍为上次默认口径分析/);
  assert.match(source,/scopeMatch:value\.scopeMatch!==false/);
});

test('helmet node deep links pass the ProUI path object', async () => {
  const source = await readFile(new URL('../bi_agent/web/static/cockpit/cockpit.js', import.meta.url),'utf8');
  assert.match(source,/function helmetPathArg\(path\)/);
  assert.match(source,/Array\.isArray\(path\).*\{segments: path\}/);
  assert.match(source,/pending\.componentId, pending\.selection, helmetPathArg\(pending\.path\)/s);
});

test('background-only page snapshot rejection does not become a load error', async () => {
  const source = await readFile(new URL('../bi_agent/web/static/cockpit/cockpit.js', import.meta.url),'utf8');
  assert.match(source,/cause\.backgroundOnly/);
  assert.match(source,/updateStatus:'waiting'/);
});
