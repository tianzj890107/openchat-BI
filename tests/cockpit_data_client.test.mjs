import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
const source = fs.readFileSync(new URL('../bi_agent/web/static/cockpit/data-client.js', import.meta.url), 'utf8');
const clientModule = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const {createAPDataClient, observeRuntimeFilters, observeActivationActions} = clientModule;
const query = {analysisConfig: {indicators: [{identifierCode:'M0001'}]}, commonConfig: {filters: {month:'2026-10'}}};
const ok = (receiptId, data = {rows:[{amount:42}]}) => ({ok:true, status:200, json:async()=>({receiptId,data,expiresAt:Date.now()/1000+60})});

test('concurrent duplicate widgets share the same upstream response and result receipt', async () => {
  const calls=[];
  const client=createAPDataClient({apiBase:'/prefix/api/cockpit',id:2,request:async(url,options)=>{calls.push({url,body:JSON.parse(options.body)});return ok('receipt1');}});
  const [a,b]=await Promise.all([client.biAdapters.postAnalysisDataQuery(query),client.biAdapters.postAnalysisDataQuery(query)]);
  assert.deepEqual(a,b);assert.equal(calls.length,1);
  assert.equal(calls[0].url,'/prefix/api/cockpit/data/query');assert.equal(calls[0].body.id,2);
  assert.deepEqual(client.scope().apReceiptIds,['receipt1']);
});

test('filter change replaces old scope and rejects the late old response', async () => {
  const resolves=[];
  const client=createAPDataClient({apiBase:'/api/cockpit',id:1,request:()=>new Promise(resolve=>resolves.push(resolve))});
  const old=client.biAdapters.postAnalysisDataQuery(query);
  client.clearScope(); // A committed SDK filter change invalidates the whole previous view.
  const changed=structuredClone(query);changed.commonConfig.filters.month='2026-09';
  const current=client.biAdapters.postAnalysisDataQuery(changed);
  assert.throws(()=>client.scope(),/加载/);
  const rejected=assert.rejects(old,/忽略旧AP响应/);
  resolves[0](ok('old'));resolves[1](ok('new'));
  await rejected;await current;
  assert.deepEqual(client.scope().apReceiptIds,['new']);
  assert.match(client.scope().chartQueries[0],/2026-09/);
  assert.doesNotMatch(client.scope().chartQueries[0],/2026-10/);
});

test('AP errors and expired receipts block analysis and cannot fall back to fixtures', async () => {
  let fail=true;
  const client=createAPDataClient({apiBase:'/api/cockpit',id:1,request:async()=>fail?{ok:false,status:502,json:async()=>({detail:'AP认证失效'})}:ok('retried')});
  await assert.rejects(client.biAdapters.postAnalysisDataQuery(query),/认证失效/);
  assert.throws(()=>client.scope(),/认证失效/);
  fail=false;await client.biAdapters.postAnalysisDataQuery(query);
  assert.deepEqual(client.scope().apReceiptIds,['retried']);
  const expired=createAPDataClient({apiBase:'/api/cockpit',id:1,request:async()=>({ok:true,status:200,json:async()=>({receiptId:'old',data:{},expiresAt:1})})});
  await expired.biAdapters.postAnalysisDataQuery(query);
  assert.throws(()=>expired.scope(),/已过期/);
});

test('browser query queue limits upstream traffic to two requests', async () => {
  let active=0,max=0,count=0;
  const client=createAPDataClient({apiBase:'/api/cockpit',id:1,request:async()=>{active++;max=Math.max(max,active);await new Promise(r=>setTimeout(r,5));active--;return ok('receipt'+(++count));}});
  await Promise.all(Array.from({length:7},(_,i)=>client.biAdapters.postAnalysisDataQuery({analysisConfig:{indicators:[{identifierCode:'M'+i}]}})));
  assert.equal(max,2);assert.equal(client.scope().apReceiptIds.length,7);
});

test('a queue-timeout response is retried instead of surfacing as an error', async () => {
  let calls=0;
  const client=createAPDataClient({apiBase:'/api/cockpit',id:1,request:async()=>++calls===1?{ok:false,status:504,json:async()=>({detail:'AP查询排队超时，请稍后重试'})}:ok('queued-once')});
  assert.deepEqual(await client.biAdapters.postAnalysisDataQuery(query),{rows:[{amount:42}]});
  assert.equal(calls,2);assert.deepEqual(client.scope().apReceiptIds,['queued-once']);
});

test('host utilities accept only the fixed read-only graph interface', async () => {
  let calls=0;
  const client=createAPDataClient({apiBase:'/api/cockpit',id:1,request:async()=>{calls++;return ok('graph',{nodes:[]});}});
  assert.ok((await client.utils.request({url:'http://foreign/admin/delete'}))[0]);
  assert.equal(calls,0);
  const [error,result]=await client.utils.request({url:'/x360/v1/graphs/helmet-view',params:{flowCode:'SALES_CALIBER'}});
  assert.equal(error,null);assert.deepEqual(result.data,{nodes:[]});
  assert.throws(()=>client.scope(),/加载/); // Graph metadata is not business evidence.
});

test('the host injects only the delivered single-query adapter',()=>{
 const client=createAPDataClient({apiBase:'/api/cockpit',id:1,request:async()=>ok('single')});
 assert.deepEqual(Object.keys(client.biAdapters),['postAnalysisDataQuery']);
 assert.equal('postAnalysisDataQueryBatch' in client.biAdapters,false);
});

test('activation actions expose tab and helmet selections to the host router',()=>{
 const calls=[];
 const runtime=observeActivationActions({
  setActiveTab(containerId,tabId){calls.push(['tab',containerId,tabId]);return 'tab';},
  setHelmetGraphSelection(componentId,selection,path){calls.push(['helmet',componentId,selection,path]);return 'helmet';},
 },{onTabChange:(...args)=>calls.push(['navigate',...args]),onHelmetSelection:(...args)=>calls.push(['remember',...args])});
 assert.equal(runtime.setActiveTab('tabs','analysis'),'tab');
 runtime.setHelmetGraphSelection('graph',{nodeId:'2109840325158682625'},{segments:[]});
 assert.deepEqual(calls,[
  ['tab','tabs','analysis'],['navigate','tabs','analysis'],
  ['helmet','graph',{nodeId:'2109840325158682625'},{segments:[]}],
  ['remember','graph',{nodeId:'2109840325158682625'},{segments:[]}],
 ]);
});

test('SDK filter change drops all previous-scope receipts before new requests',async()=>{
 const {observeRuntimeFilters}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
 let ready=false,changes=0;
 const client=createAPDataClient({apiBase:'/api/cockpit',id:1,request:async()=>ok('receipt-scope')});
 const runtime=observeRuntimeFilters({setFilterConditions(){},setButtonGrainSelection(){}},()=>{changes++;client.clearScope();},()=>ready);
 runtime.setFilterConditions('filter',[]);assert.equal(changes,0);
 await client.biAdapters.postAnalysisDataQuery(query);assert.equal(client.scope().apReceiptIds.length,1);
 ready=true;runtime.setFilterConditions('filter',[{department:'B'}]);
 assert.equal(changes,1);assert.throws(()=>client.scope(),/加载/);
 runtime.setFilterConditions('filter',[{department:'B'}]);assert.equal(changes,1);
});

 test('simultaneous graph widgets retain distinct status filters regardless of response order', async()=>{
  for(const reverse of [false,true]) {
   const resolves=[];
   const client=createAPDataClient({apiBase:'/api/cockpit',id:1,request:()=>new Promise(resolve=>resolves.push(resolve))});
   const first=structuredClone(query),second=structuredClone(query);
   first.commonConfig.filters={status:['overdue']};second.commonConfig.filters={status:['overdue','normal']};
   const a=client.biAdapters.postAnalysisDataQuery(first);
   const b=client.biAdapters.postAnalysisDataQuery(second);
   for(const i of reverse?[1,0]:[0,1]) resolves[i](ok('status-'+i));
   await Promise.all([a,b]);
   assert.deepEqual(client.scope().apReceiptIds,['status-0','status-1']);
   assert.equal(client.scope().chartQueries.length,2);
  }
 });

test('completed duplicate reads reuse the same receipt until short TTL or scope change',async()=>{
 let calls=0;
 const client=createAPDataClient({apiBase:'/api/cockpit',id:1,request:async()=>({...ok('r'+(++calls)),json:async()=>({receiptId:'r'+calls,data:{value:calls},receivedAt:Date.now()/1000,expiresAt:Date.now()/1000+60})})});
 await client.biAdapters.postAnalysisDataQuery(query);await client.biAdapters.postAnalysisDataQuery(query);
 assert.equal(calls,1);assert.equal(client.entries().length,1);
 client.clearScope();await client.biAdapters.postAnalysisDataQuery(query);assert.equal(calls,2);
});

test('full-page replay renders expired display data without inventing fresh analysis receipts',async()=>{
 let calls=0,misses=0;
 const snapshot={entries:[{kind:'analysis',payload:query,data:{value:42},receiptId:'old',receivedAt:1,expiresAt:2}]};
 const client=createAPDataClient({apiBase:'/api/cockpit',id:1,snapshot,request:async()=>{calls++;return ok('new');},onSnapshotMiss:()=>misses++});
 assert.deepEqual(await client.biAdapters.postAnalysisDataQuery(query),{value:42});assert.equal(calls,0);
 assert.throws(()=>client.scope(),/过期/);
 await assert.rejects(client.biAdapters.postAnalysisDataQuery({...query,commonConfig:{filters:{month:'other'}}}),/没有完整缓存/);
 await new Promise(r=>setImmediate(r));assert.equal(misses,1);assert.equal(calls,0);
});

test('a remounted SDK restores UI selections and preserves the original default scope',()=>{
 const values=new Map();let ready=false;const scopes=[];
 const raw=()=>({setButtonGrainSelection(id,v){values.set(id,v);},setActiveTab(){}});
 const first=observeRuntimeFiltersForTest(raw(),s=>scopes.push(s),()=>ready);
 first.setButtonGrainSelection('grain','YEAR');ready=true;first.setButtonGrainSelection('grain','MONTH');
 const monthly=scopes.at(-1);assert.notEqual(monthly,'default');
 const nextRaw=raw(),view=first.replayView(nextRaw);assert.equal(values.get('grain'),'MONTH');
 ready=false;const second=observeRuntimeFiltersForTest(nextRaw,s=>scopes.push(s),()=>ready,view);
 second.setButtonGrainSelection('grain','MONTH');ready=true;second.setButtonGrainSelection('grain','YEAR');
 assert.equal(scopes.at(-1),'default');second.setButtonGrainSelection('grain','MONTH');assert.equal(scopes.at(-1),monthly);
});
const {observeRuntimeFilters:observeRuntimeFiltersForTest}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));

test('delivered activate rules reach the host route and survive a remount replay', () => {
  const calls=[];
  const runtime={
    setActiveTab:(container,tab)=>calls.push(['tab',container,tab]),
    setHelmetGraphSelection:(component,selection)=>calls.push(['helmet',component,selection.nodeId]),
  };
  const tabs=[],helmets=[];
  const wrapped=observeRuntimeFilters(runtime,()=>{},()=>true,null,{
    onTabChange:tab=>tabs.push(tab),
    onHelmetSelect:(component,selection)=>helmets.push([component,selection.nodeId]),
  });
  wrapped.setHelmetGraphSelection('mini-cpgraph-93j6k86p',{nodeId:'2109840696539136002'});
  wrapped.setActiveTab('tab-container-zm9eyxne','tab-1suxx5hd');
  assert.deepEqual(helmets,[['mini-cpgraph-93j6k86p','2109840696539136002']]);
  assert.deepEqual(tabs,['tab-1suxx5hd']);
  assert.deepEqual(calls,[['helmet','mini-cpgraph-93j6k86p','2109840696539136002'],['tab','tab-container-zm9eyxne','tab-1suxx5hd']]);
  const replay=[];
  wrapped.replayView({
    setActiveTab:(container,tab)=>replay.push(['tab',container,tab]),
    setHelmetGraphSelection:(component,selection)=>replay.push(['helmet',component,selection.nodeId]),
  });
  assert.deepEqual(replay,[['helmet','mini-cpgraph-93j6k86p','2109840696539136002'],['tab','tab-container-zm9eyxne','tab-1suxx5hd']]);
});
