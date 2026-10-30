import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
const source = fs.readFileSync(new URL('../bi_agent/web/static/cockpit/data-client.js', import.meta.url), 'utf8');
const clientModule = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const {createAPDataClient, observeRuntimeFilters, observeActivationActions, AP_QUERY_CONCURRENCY} = clientModule;
const query = {analysisConfig: {indicators: [{identifierCode:'M0001'}]}, commonConfig: {filters: {month:'2026-10'}}};
const ok = (receiptId, data = {rows:[{amount:42}]}) => ({ok:true, status:200, json:async()=>({receiptId,data,receivedAt:Date.now()/1000,expiresAt:Date.now()/1000+60})});

test('concurrent duplicate widgets share the same upstream response and result receipt', async () => {
  const calls=[];
  const client=createAPDataClient({apiBase:'/prefix/api/cockpit',id:2,request:async(url,options)=>{calls.push({url,body:JSON.parse(options.body)});return ok('receipt1');}});
  const [a,b]=await Promise.all([client.biAdapters.postAnalysisDataQuery(query),client.biAdapters.postAnalysisDataQuery(query)]);
  assert.deepEqual(a,b);assert.equal(calls.length,1);
  assert.equal(calls[0].url,'/prefix/api/cockpit/data/query');assert.equal(calls[0].body.id,2);
  assert.deepEqual(client.scope().apReceiptIds,['receipt1']);
});

test('a newer server snapshot advances receipts in place without fetching or clearing the mounted scope', async () => {
  let calls = 0;
  const client = createAPDataClient({apiBase:'/api/cockpit', id:1,
    request:async()=>{calls+=1; return ok('receipt-old');}});
  await client.biAdapters.postAnalysisDataQuery(query);
  const updated = client.applySnapshot([{kind:'analysis', payload:query, data:{rows:[{amount:99}]},
    receiptId:'receipt-new', receivedAt:Date.now()/1000, expiresAt:Date.now()/1000+120}]);
  assert.equal(updated, 1);
  assert.equal(calls, 1);
  assert.deepEqual(client.scope().apReceiptIds, ['receipt-new']);
  assert.deepEqual(client.entries()[0].data, {rows:[{amount:99}]});
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

test('browser query queue bounds upstream traffic without serialising every query', async () => {
  let active=0,max=0,count=0;
  const client=createAPDataClient({apiBase:'/api/cockpit',id:1,request:async()=>{active++;max=Math.max(max,active);await new Promise(r=>setTimeout(r,5));active--;return ok('receipt'+(++count));}});
  await Promise.all(Array.from({length:7},(_,i)=>client.biAdapters.postAnalysisDataQuery({analysisConfig:{indicators:[{identifierCode:'M'+i}]}})));
  assert.equal(max,AP_QUERY_CONCURRENCY);assert.equal(client.scope().apReceiptIds.length,7);
});

test('queries for the visible stage jump ahead of queued offscreen work', async () => {
  const started=[], releases=new Map();
  const payload=n=>({analysisConfig:{indicators:[{identifierCode:'M'+n}]}});
  const client=createAPDataClient({apiBase:'/api/cockpit',id:1,concurrency:1,
    priorityFor:(kind,value)=>({visible:value.analysisConfig.indicators[0].identifierCode==='M2',heavy:false}),
    request:async(_url,options)=>{
      const code=JSON.parse(options.body).payload.analysisConfig.indicators[0].identifierCode;
      started.push(code);
      await new Promise(resolve=>releases.set(code,resolve));
      return ok('receipt-'+code);
    }});
  const first=client.biAdapters.postAnalysisDataQuery(payload(0));
  const hidden=client.biAdapters.postAnalysisDataQuery(payload(1));
  const visible=client.biAdapters.postAnalysisDataQuery(payload(2));
  assert.deepEqual(started,['M0']);
  releases.get('M0')();await first;await new Promise(resolve=>setTimeout(resolve,0));
  assert.deepEqual(started,['M0','M2']);
  releases.get('M2')();await visible;await new Promise(resolve=>setTimeout(resolve,0));
  assert.deepEqual(started,['M0','M2','M1']);
  releases.get('M1')();await hidden;
});

test('heavy queries cannot occupy every AP execution slot', async () => {
  const started=[], releases=new Map();let activeHeavy=0,maxHeavy=0;
  const payload=n=>({analysisConfig:{indicators:[{identifierCode:n}]}});
  const client=createAPDataClient({apiBase:'/api/cockpit',id:1,
    priorityFor:(kind,value)=>({heavy:value.analysisConfig.indicators[0].identifierCode.startsWith('H')}),
    request:async(_url,options)=>{
      const code=JSON.parse(options.body).payload.analysisConfig.indicators[0].identifierCode;
      if(code.startsWith('H')){activeHeavy++;maxHeavy=Math.max(maxHeavy,activeHeavy);}
      started.push(code);
      await new Promise(resolve=>releases.set(code,resolve));
      if(code.startsWith('H'))activeHeavy--;
      return ok('receipt-'+code);
    }});
  const heavy=[0,1,2].map(n=>client.biAdapters.postAnalysisDataQuery(payload('H'+n)));
  const light=client.biAdapters.postAnalysisDataQuery(payload('L0'));
  assert.deepEqual(started,['H0','H1','L0']);
  assert.equal(maxHeavy,2);
  releases.get('L0')();await light;await new Promise(resolve=>setTimeout(resolve,0));
  releases.get('H0')();await heavy[0];await new Promise(resolve=>setTimeout(resolve,0));
  assert.deepEqual(started,['H0','H1','L0','H2']);
  assert.equal(maxHeavy,2);
  releases.get('H1')();releases.get('H2')();
  await Promise.all(heavy);
});

test('AI waits only for the current stage rather than the whole page', async () => {
  let releaseShip;
  const client=createAPDataClient({apiBase:'/api/cockpit',id:1,readyTimeoutMs:2000,
    stageFor:(kind,value)=>value.analysisConfig.indicators[0].identifierCode==='SHIP'?'shipment':'opportunity',
    request:async(_url,options)=>{
      const code=JSON.parse(options.body).payload.analysisConfig.indicators[0].identifierCode;
      if(code==='SHIP')return new Promise(resolve=>{releaseShip=resolve;});
      return ok('receipt-opportunity');
    }});
  const shipment=client.biAdapters.postAnalysisDataQuery({analysisConfig:{indicators:[{identifierCode:'SHIP'}]}});
  await client.biAdapters.postAnalysisDataQuery({analysisConfig:{indicators:[{identifierCode:'OPP'}]}});
  const scope=await client.ready({partial:true,stages:['opportunity']});
  assert.deepEqual(scope.apReceiptIds,['receipt-opportunity']);
  assert.match(scope.chartQueries[0],/OPP/);
  assert.doesNotMatch(scope.chartQueries.join('|'),/SHIP/);
  releaseShip(ok('receipt-shipment'));await shipment;
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

test('node selection keeps the loaded data scope without replaying a completed response',async()=>{
 let ready=true,calls=0,changes=0;
 const client=createAPDataClient({apiBase:'/api/cockpit',id:1,request:async()=>{calls++;return {...ok('node-scope',{value:42}),json:async()=>({receiptId:'node-scope',data:{value:42},receivedAt:Date.now()/1000,expiresAt:Date.now()/1000+60})};}});
 const runtime=observeRuntimeFilters({setFilterConditions(){},setButtonGrainSelection(){},setContainerActiveNode(){},setHelmetGraphSelection(){}},()=>{changes++;client.clearScope();},()=>ready);
 await client.biAdapters.postAnalysisDataQuery(query);
 const receipt=client.scope().apReceiptIds[0];
 runtime.setContainerActiveNode('quote-container',{nodeId:'quote-node'});
 runtime.setHelmetGraphSelection('graph',{nodeId:'quote-node'},{segments:[]});
 assert.equal(changes,0);
 assert.equal(client.scope().apReceiptIds[0],receipt);
 await client.biAdapters.postAnalysisDataQuery(query);
 assert.equal(calls,2);
 runtime.setFilterConditions('filter',[{label:'时间',value:'2026'}]);
 assert.equal(changes,1);
});

test('clearing a scope rejects queued requests instead of leaving them running',async()=>{
 let queued=0;
 const client=createAPDataClient({apiBase:'/api/cockpit',id:1,concurrency:1,request:async(url,options)=>{
   queued++;
   return new Promise((resolve,reject)=>{
     options.signal.addEventListener('abort',()=>{const error=new Error('aborted');error.name='AbortError';reject(error);},{once:true});
   });
 }});
 const first=client.biAdapters.postAnalysisDataQuery(query);
 const second=client.biAdapters.postAnalysisDataQuery({...query,commonConfig:{filters:{month:'other'}}});
 await new Promise(resolve=>setTimeout(resolve,10));
 assert.equal(queued,1);
 client.clearScope();
 await assert.rejects(first,/超时|取消|aborted/);
 await assert.rejects(second,/超时|取消|aborted/);
 assert.equal(queued,1);
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

test('completed duplicate reads reach the server again when response replay is disabled',async()=>{
 let calls=0;
 const client=createAPDataClient({apiBase:'/api/cockpit',id:1,request:async()=>({...ok('r'+(++calls)),json:async()=>({receiptId:'r'+calls,data:{value:calls},receivedAt:Date.now()/1000,expiresAt:Date.now()/1000+60})})});
 await client.biAdapters.postAnalysisDataQuery(query);await client.biAdapters.postAnalysisDataQuery(query);
 assert.equal(calls,2);assert.equal(client.entries().length,1);
 client.clearScope();await client.biAdapters.postAnalysisDataQuery(query);assert.equal(calls,3);
});

test('full-page replay renders expired display data without inventing fresh analysis receipts',async()=>{
 let calls=0,misses=0;
 const snapshot={entries:[{kind:'analysis',payload:query,data:{value:42},receiptId:'old',receivedAt:1,expiresAt:2}]};
 const client=createAPDataClient({apiBase:'/api/cockpit',id:1,snapshot,request:async()=>{calls++;return ok('new');},onSnapshotMiss:()=>misses++});
 assert.deepEqual(await client.biAdapters.postAnalysisDataQuery(query),{value:42});assert.equal(calls,0);
 assert.throws(()=>client.scope(),/过期/);
 const missedQuery={...query,commonConfig:{filters:{month:'other'}}};
 assert.deepEqual(await client.biAdapters.postAnalysisDataQuery(missedQuery),{rows:[{amount:42}]});
 assert.deepEqual(await client.biAdapters.postAnalysisDataQuery(missedQuery),{rows:[{amount:42}]});
 await new Promise(r=>setImmediate(r));assert.equal(misses,1);assert.equal(calls,2);
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
test('SDK default filters do not restart the page before the first user filter action',()=>{
 const scopes=[];let ready=false,userAction=false;
 const runtime={setButtonGrainSelection(){},setFilterConditions(){}};
 const wrapped=observeRuntimeFiltersForTest(runtime,s=>scopes.push(s),()=>ready,null,
   {isUserAction:()=>userAction});
 wrapped.setButtonGrainSelection('grain','YEAR');
 wrapped.setFilterConditions('date',{value:'2025-10'});
 ready=true;
 assert.equal(wrapped.flushPendingScope(),false);
 assert.deepEqual(scopes,[]);
 userAction=true;wrapped.setButtonGrainSelection('grain','MONTH');
 assert.equal(scopes.length,1);assert.notEqual(scopes[0],'default');
 userAction=false;wrapped.setButtonGrainSelection('grain','MONTH');
 assert.equal(scopes.length,1,'a programmatic replay must not create another scope change');
 userAction=true;wrapped.setButtonGrainSelection('grain','YEAR');
 assert.equal(scopes.at(-1),'default');
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

test('failed query reports metric labels and a later success clears the live error', async () => {
  let fail = true;
  const errors = [], details = [], recovers = [];
  const withAlias = {analysisConfig: {indicators: [{identifierCode:'YWLN_M0022', alias:'商机获取电量'}]}};
  const client = createAPDataClient({apiBase:'/api/cockpit', id:1,
    request: async () => fail
      ? {ok:false, status:502, json:async()=>({detail:'SQL 超时且没有 mock 数据'})}
      : ok('receipt-recovered'),
    onError: (message, detail) => { errors.push(message); details.push(detail); },
    onRecover: () => recovers.push(1)});
  await assert.rejects(client.biAdapters.postAnalysisDataQuery(withAlias), /SQL 超时/);
  assert.equal(errors.length, 1);
  assert.deepEqual(details[0], {kind:'analysis'});
  assert.match(errors[0], /商机获取电量/);
  assert.match(errors[0], /SQL 超时/);
  assert.deepEqual(client.failures().length, 1);
  fail = false;
  await client.biAdapters.postAnalysisDataQuery(withAlias);
  assert.ok(recovers.length >= 1);
  assert.deepEqual(client.failures(), []);
});

test('a transient 504 is retried once while a deterministic 502 is not', async () => {
  const statuses = [];
  const transient = createAPDataClient({apiBase:'/api/cockpit', id:1, request: async () => {
    statuses.push(504);
    if (statuses.length === 1) return {ok:false, status:504, json:async()=>({detail:'AP请求超时或不可达'})};
    return ok('receipt-after-retry');
  }});
  await transient.biAdapters.postAnalysisDataQuery(query);
  assert.equal(statuses.length, 2);
  const failed = [];
  const deterministic = createAPDataClient({apiBase:'/api/cockpit', id:1, request: async () => {
    failed.push(502);
    return {ok:false, status:502, json:async()=>({detail:'AP未返回成功的数据结果'})};
  }});
  await assert.rejects(deterministic.biAdapters.postAnalysisDataQuery(query), /AP未返回成功/);
  assert.equal(failed.length, 1);
});

test('partial scope keeps successful queries and reports failed ones for stage disclosure', async () => {
  const failed = {analysisConfig: {indicators: [{identifierCode:'FAIL'}]}, commonConfig: {filters: {month:'2026-10'}}};
  const client = createAPDataClient({apiBase:'/api/cockpit', id:1, request:async (url, options) => {
    const body = JSON.parse(options.body);
    if (body.payload.analysisConfig.indicators[0].identifierCode === 'FAIL')
      return {ok:false, status:502, json:async () => ({detail:'AP未返回成功的数据结果：SQL 超时'})};
    return ok('receipt-ok');
  }});
  await assert.rejects(client.biAdapters.postAnalysisDataQuery(failed), /SQL 超时/);
  await client.biAdapters.postAnalysisDataQuery(query);
  assert.throws(() => client.scope(), /SQL 超时/);
  await assert.rejects(client.ready(), /SQL 超时/);
  const partial = await client.ready({partial:true});
  assert.deepEqual(partial.apReceiptIds, ['receipt-ok']);
  assert.equal(partial.chartQueries.length, 1);
  assert.equal(partial.unavailable.length, 1);
  assert.match(partial.unavailable[0].query, /FAIL/);
  assert.match(partial.unavailable[0].error, /SQL 超时/);
});

test('empty vertex config is stopped before it reaches the AP gateway', async () => {
  let calls = 0;
  const client = createAPDataClient({apiBase:'/api/cockpit', id:1, request:async () => { calls++; return ok('r'); }});
  await assert.rejects(client.biAdapters.postAnalysisDataQuery({analysisConfig:{vertex:[]}, commonConfig:{filters:{}}}), /未配置实体查询字段/);
  assert.equal(calls, 0);
  assert.deepEqual(client.failures(), ['看板组件未配置实体查询字段，已跳过空查询']);
});

test('the browser waits longer than the three-minute AP budget and never replays a spent 504',async()=>{
 const {AP_QUERY_TIMEOUT_MS,SCOPE_READY_TIMEOUT_MS}=clientModule;
 assert.ok(AP_QUERY_TIMEOUT_MS>=180000,'browser request timeout must outlast the AP budget');
 assert.ok(SCOPE_READY_TIMEOUT_MS>AP_QUERY_TIMEOUT_MS,'scope preparation must outlast one slow AP query');
 let calls=0;
 const client=createAPDataClient({apiBase:'/api/cockpit',id:1,retryWindowMs:0,
  request:async()=>{calls++;return {ok:false,status:504,json:async()=>({detail:'AP请求超时或不可达；未切换到其他数据源'})};}});
 await assert.rejects(client.biAdapters.postAnalysisDataQuery(query),/超时/);
 assert.equal(calls,1,'a 504 that consumed the long budget must not be retried immediately');
});

test('scope preparation stops at its own budget instead of spinning forever',async()=>{
 const started=Date.now();
 const client=createAPDataClient({apiBase:'/api/cockpit',id:1,readyTimeoutMs:250,timeoutMs:500,
  request:()=>new Promise(()=>{})});
 client.biAdapters.postAnalysisDataQuery(query).catch(()=>{});
 await assert.rejects(client.ready({partial:true}),/仍在加载/);
 assert.ok(Date.now()-started<2000);
});

test('the first user filter change is not swallowed as the default scope',async()=>{
 let ready=false;const scopes=[];
 const runtime=observeRuntimeFilters({setFilterConditions(){}},scope=>scopes.push(scope),()=>ready);
 runtime.setFilterConditions('filter',[{label:'时间',value:'2025'}]);
 ready=true;
 runtime.setFilterConditions('filter',[{label:'时间',value:'2026'}]);
 runtime.setFilterConditions('filter',[{label:'时间',value:'2025'}]);
 assert.equal(scopes.length,2);
 assert.notEqual(scopes[0],'default','the first change must load the new scope');
 assert.equal(scopes[1],'default','going back to the loaded default keeps the default scope');
});

test('a filter change made while the page is still loading is applied after readiness',async()=>{
 let ready=false;const scopes=[];
 const runtime=observeRuntimeFilters({setFilterConditions(){}},(scope,detail)=>scopes.push([scope,detail]),()=>ready);
 runtime.setFilterConditions('filter',[{label:'时间',value:'2025'}]);
 runtime.setFilterConditions('filter',[{label:'时间',value:'2026-01-01'}]);
 assert.equal(scopes.length,0);
 assert.equal(runtime.flushPendingScope(),false,'a pending change cannot fire before readiness');
 ready=true;
 assert.equal(runtime.flushPendingScope(),true);
 assert.equal(scopes.length,1);
 assert.notEqual(scopes[0][0],'default');
 assert.match(scopes[0][1],/时间：2026-01-01/);
 runtime.setFilterConditions('filter',[{label:'时间',value:'2026-01-01'}]);
 assert.equal(scopes.length,1,'replaying the same value must not re-trigger analysis');
});

test('filter changes produce a readable scope hint without internal identifier codes',()=>{
 const describe=clientModule.summarizeFilterChange;
 assert.match(describe('setFilterConditions',['f',[{label:'时间',value:['2026-01-01','2026-12-31']}]]),/时间：2026-01-01 至 2026-12-31/);
 assert.equal(describe('setFilterConditions',['f',[{field:'YWLN_D044',value:['2026']}]]),'');
 assert.equal(describe('setButtonGrainSelection',['f','YEAR']),'');
});

test('a page that never starts a query does not hold the long AP budget',async()=>{
 const started=Date.now();
 const client=createAPDataClient({apiBase:'/api/cockpit',id:1,idleMs:300});
 await assert.rejects(client.ready({partial:true}),/仍在加载/);
 assert.ok(Date.now()-started<1500,'an idle page must fail fast, not wait for the three-minute budget');
});

test('all failed page queries still produce a partial scope for the PG fallback',async()=>{
 const client=createAPDataClient({apiBase:'/api/cockpit',id:1,
  request:async()=>({ok:false,status:502,json:async()=>({detail:'AP请求超时或不可达'})})});
 await assert.rejects(client.biAdapters.postAnalysisDataQuery(query),/超时/);
 const scope=await client.ready({partial:true});
 assert.deepEqual(scope.chartQueries,[]);
 assert.deepEqual(scope.apReceiptIds,[]);
 assert.equal(scope.unavailable.length,1);
 assert.match(scope.unavailable[0].query,/M0001/);
 // A whole-page publish still needs real AP material; only analysis may proceed.
 assert.throws(()=>client.scope(),/AP请求超时/);
});
