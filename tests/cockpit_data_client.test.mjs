import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
const source = fs.readFileSync(new URL('../bi_agent/web/static/cockpit/data-client.js', import.meta.url), 'utf8');
const {createAPDataClient} = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
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

test('host utilities accept only the fixed read-only graph interface', async () => {
  let calls=0;
  const client=createAPDataClient({apiBase:'/api/cockpit',id:1,request:async()=>{calls++;return ok('graph',{nodes:[]});}});
  assert.ok((await client.utils.request({url:'http://foreign/admin/delete'}))[0]);
  assert.equal(calls,0);
  const [error,result]=await client.utils.request({url:'/x360/v1/graphs/helmet-view',params:{flowCode:'SALES_CALIBER'}});
  assert.equal(error,null);assert.deepEqual(result.data,{nodes:[]});
  assert.throws(()=>client.scope(),/加载/); // Graph metadata is not business evidence.
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
   const a=client.biAdapters.postAnalysisDataQueryBatch([first]);
   const b=client.biAdapters.postAnalysisDataQueryBatch([second]);
   for(const i of reverse?[1,0]:[0,1]) resolves[i](ok('status-'+i));
   await Promise.all([a,b]);
   assert.deepEqual(client.scope().apReceiptIds,['status-0','status-1']);
   assert.equal(client.scope().chartQueries.length,2);
  }
 });
