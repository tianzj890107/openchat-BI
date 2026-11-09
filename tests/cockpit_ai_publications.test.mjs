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
  assert.match(source,/pageCache\.publish\(client,items,uiScope,undefined,true\)/);
  assert.match(source,/\[cockpit-page-publish\][\s\S]{0,220}error:'',refreshing:false,updateStatus:'waiting'/);
});

test('manual job progress polls quickly even while published cards remain ready', async () => {
  const jobs=[];
  const client=createAiPublicationClient({apiBase:'/api/cockpit',id:1,
    request:async()=>({ok:true,json:async()=>({version:'ready',updatingCount:0,manualUpdate:{status:'running'},slots:{}})}),
    schedule:(fn,ms)=>{jobs.push({fn,ms});return jobs.length;},clear:()=>{},activeMs:17,pollMs:99});
  client.start();
  await jobs.shift().fn();
  assert.equal(jobs.at(-1).ms,17);
  client.stop();
});


test('manifest polling fetches each changed stage once and preserves shared evidence',async()=>{
 const calls=[],updates=[];let orderVersion='o1';
 const manifest=()=>({transport:'stage-manifest-v1',version:orderVersion,
  stageVersions:{shipment:'s1',order:orderVersion},slots:{
   ship:{stage:'shipment',status:'ready'},order:{stage:'order',status:'ready'}},manualUpdate:{status:'running'}});
 const client=createAiPublicationClient({apiBase:'/api/cockpit',id:1,onUpdate:v=>updates.push(v),request:async url=>{
  calls.push(url);
  if(url.includes('?id=1&uiScope='))return {ok:true,json:async()=>manifest()};
  const stage=url.includes('/shipment?')?'shipment':'order',id=stage==='shipment'?'ship':'order';
  return {ok:true,status:200,json:async()=>({version:stage==='shipment'?'s1':orderVersion,evidence:{facts:[{id:'f',value:42}]},slots:{[id]:{payload:{id:stage,result:{summary:'ready'}}}}})};
 }});
 await client.load();await client.load();
 assert.equal(calls.filter(x=>x.includes('/stages/')).length,2);
 assert.equal(updates[0].slots.ship.payload,updates[1].slots.ship.payload);
 assert.equal(updates.at(-1).slots.ship.payload.evidence.facts[0].value,42);
 orderVersion='o2';await client.load();
 assert.equal(calls.filter(x=>x.includes('/stages/order?')).length,2);
 assert.equal(calls.filter(x=>x.includes('/stages/shipment?')).length,1);
 assert.equal(updates[0].slots.ship.payload,updates[2].slots.ship.payload);
});


test('hidden tabs do not fetch and terminal manual rounds return to slow polling',async()=>{
 const jobs=[];let hidden=true,calls=0;
 const client=createAiPublicationClient({apiBase:'/api/cockpit',id:1,isHidden:()=>hidden,
  schedule:(fn,ms)=>{jobs.push({fn,ms});return jobs.length;},clear:()=>{},
  request:async()=>{calls++;return {ok:true,json:async()=>({version:'done',slots:{},manualUpdate:{status:'partial'}})};}});
 client.start();await jobs.shift().fn();assert.equal(calls,0);
 hidden=false;await jobs.shift().fn();assert.equal(calls,1);assert.equal(jobs.at(-1).ms,60000);
 client.stop();
});


test('failed changed-stage fetch preserves the old payload and its timestamp',async()=>{
 let version='v1',fail=false;const updates=[];
 const client=createAiPublicationClient({apiBase:'/api/cockpit',id:1,onUpdate:v=>updates.push(v),request:async url=>{
  if(url.includes('/stages/'))return fail?{ok:false,status:502}:{ok:true,json:async()=>({version,evidence:{facts:[]},slots:{s:{stage:'shipment',status:'ready',generatedAt:1,payload:{id:'old'}}}})};
  return {ok:true,json:async()=>({transport:'stage-manifest-v1',version,stageVersions:{shipment:version},slots:{s:{stage:'shipment',status:'ready',generatedAt:version==='v1'?1:2}}})};
 }});
 await client.load();version='v2';fail=true;await client.load();
 assert.equal(updates.at(-1).slots.s.generatedAt,1);
 assert.equal(updates.at(-1).slots.s.payload,updates[0].slots.s.payload);
});
