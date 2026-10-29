import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createPublicationClient,CARD_CONTRACT} from '../bi_agent/web/static/cockpit/publication-client.js';
const query='{"analysisConfig":{"indicators":[{"identifierCode":"M1"}]}}';
const body={id:1,engine:'main',stage:'shipment',page:'analysis',chartQueries:[query],clarifications:{},apReceiptIds:['new']};
const item=(id,summary='已完成卡片')=>({id,status:'limited',context:{...body,dataFingerprint:'A'},result:{summary,causes:[],recommendations:[],limitations:[],cardContract:CARD_CONTRACT}});
const ok=value=>({ok:true,json:async()=>value});
const setup=options=>{const states={};const stateFor=stage=>states[stage]||(states[stage]={status:'idle',item:null});return {states,stateFor,client:createPublicationClient({apiBase:'/api/cockpit',stateFor,bodyFor:async()=>({...body}),pollMs:0,pause:async()=>{},...options})};};

test('first paint uses persistent cards; silent refresh atomically replaces after delivery',async()=>{
 let resolve;const poll=new Promise(r=>resolve=r);
 const {client,states}=setup({request:async url=>url.split('?')[0].endsWith('/refresh')?ok({cached:item('old','上次结果'),analysis:{...item('job'),status:'running'},dataFingerprint:'A'}):poll});
 client.preload({shipment:item('old','上次结果')});
 assert.equal(states.shipment.item.result.summary,'上次结果');
 const run=client.refresh('shipment');await new Promise(r=>setImmediate(r));
 assert.equal(states.shipment.status,'done');assert.equal(states.shipment.item.id,'old');assert.equal(states.shipment.refreshing,true);
 resolve(ok(item('job','新完成结果')));await run;
 assert.equal(states.shipment.item.result.summary,'新完成结果');assert.equal(states.shipment.refreshing,false);
});

test('background failure keeps the last successful full cards',async()=>{
 const {client,states}=setup({request:async()=>ok({cached:item('old'),analysis:{...item('failure'),status:'failed',error:'模型暂不可用'}})});
 client.preload({shipment:item('old')});await client.refresh('shipment');
 assert.equal(states.shipment.item.id,'old');assert.equal(states.shipment.status,'done');assert.match(states.shipment.error,/模型暂不可用/);
});

test('a new filter keeps the previous cards visible and a late old result cannot paint them',async()=>{
 let release;const gate=new Promise(r=>release=r);
 const {client,states}=setup({request:async url=>{
   if(url.split('?')[0].endsWith('/refresh')){await gate;return ok({cached:item('old'),analysis:{...item('old-job'),status:'running'}});}
   return ok(item('old-job','不能显示的旧范围结果'));
 }});
 client.preload({shipment:item('old','上次结果')});const run=client.refresh('shipment');await new Promise(r=>setImmediate(r));
 client.invalidate('筛选口径已切换（时间：2026），正在加载新数据；以下仍为上次分析');
 // The old scope stays on screen, clearly labelled as stale, until the new one is whole.
 assert.equal(states.shipment.item.result.summary,'上次结果');
 assert.equal(states.shipment.status,'done');assert.equal(states.shipment.stale,true);
 assert.match(states.shipment.scopeNotice,/口径已切换/);
 release();await run;
 assert.equal(states.shipment.item.result.summary,'上次结果');
 assert.equal(states.shipment.status,'done');assert.equal(states.shipment.stale,true);
});

test('a completed new scope replaces the stale card and clears the notice atomically',async()=>{
 let settle;const waiting=new Promise(r=>settle=r);
 const fresh={...item('new-job','新口径结果'),context:{...body,dataFingerprint:'B'}};
 const {client,states}=setup({request:async url=>{
   if(url.split('?')[0].endsWith('/refresh'))return ok({cached:item('old','上次结果'),analysis:{...item('job'),status:'running'},dataFingerprint:'B'});
   await waiting;return ok(fresh);
 }});
 client.preload({shipment:item('old','上次结果')});
 client.invalidate('筛选口径已切换，正在加载新数据；以下仍为上次分析');
 const run=client.refresh('shipment');await new Promise(r=>setImmediate(r));
 assert.equal(states.shipment.item.result.summary,'上次结果');
 settle();await run;
 assert.equal(states.shipment.item.result.summary,'新口径结果');
 assert.equal(states.shipment.stale,false);assert.equal(states.shipment.scopeNotice,'');
 assert.equal(states.shipment.refreshing,false);
});

test('a failed new scope keeps the previous cards and explains the failure',async()=>{
 const {client,states}=setup({request:async url=>url.split('?')[0].endsWith('/refresh')
   ?ok({cached:null,analysis:{...item('job'),status:'failed',error:'模型暂不可用'}}):ok({})});
 client.preload({shipment:item('old','上次结果')});
 client.invalidate('筛选口径已切换，正在加载新数据；以下仍为上次分析');
 await client.refresh('shipment');
 assert.equal(states.shipment.item.result.summary,'上次结果');
 assert.equal(states.shipment.status,'done');assert.equal(states.shipment.stale,true);
 assert.match(states.shipment.scopeNotice,/新口径分析未完成/);
});

test('a preloaded snapshot for the new scope replaces stale cards without a notice',async()=>{
 const {client,states}=setup({request:async()=>ok({})});
 client.preload({shipment:item('old','上次结果')});
 client.invalidate('筛选口径已切换，正在加载新数据；以下仍为上次分析');
 assert.equal(states.shipment.stale,true);
 client.preload({shipment:item('snapshot','新口径快照结果')});
 assert.equal(states.shipment.item.result.summary,'新口径快照结果');
 assert.equal(states.shipment.stale,false);assert.equal(states.shipment.scopeNotice,'');
});

test('uncached filters show loading while duplicates share one background job',async()=>{
 let resolve,count=0;const post=new Promise(r=>resolve=r);
 const {client,states}=setup({request:async()=>{count++;return post;}});
 const a=client.refresh('shipment'),b=client.refresh('shipment');
 assert.equal(a,b);assert.equal(states.shipment.item,null);assert.equal(states.shipment.status,'running');
 resolve(ok({cached:item('cached'),analysis:null}));await a;
 assert.equal(count,1);assert.equal(states.shipment.status,'done');assert.equal(states.shipment.item.id,'cached');
});

test('a cached result for another filter is rejected',async()=>{
 const wrong=item('wrong');wrong.context={...body,chartQueries:['different']};
 const {client,states}=setup({request:async()=>ok({cached:wrong,analysis:{...wrong,status:'running'}})});
 await client.refresh('shipment');assert.equal(states.shipment.item,null);assert.equal(states.shipment.status,'error');
});

test('filter changes invalidate preloaded cards even when their graph node has not mounted',()=>{
 const {client,states}=setup({request:async()=>ok({})});
 client.preload({shipment:item('shipment-old'),order:{...item('order-old'),context:{...body,stage:'order'}}});
 assert.equal(client.stages.size,0); // Preloading must not trigger five hidden analyses.
 client.invalidate();assert.equal(states.shipment.stale,true);assert.equal(states.order.stale,true);
 assert.equal(states.shipment.item.id,'shipment-old');assert.equal(states.order.item.id,'order-old');
});

test('a full analysis pool keeps the card loading instead of failing',async()=>{
 let calls=0;const paused=[];
 const states={};
 const stateFor=stage=>states[stage]||(states[stage]={status:'idle',item:null,progress:''});
 const client=createPublicationClient({apiBase:'/api/cockpit',stateFor,bodyFor:async()=>({...body}),pollMs:0,
   pause:async()=>{paused.push(states.shipment.progress);},
   request:async()=>{
     calls+=1;
     if(calls<3) return {ok:false,status:429,json:async()=>({detail:'分析并发已满，请稍后重试'})};
     return ok({cached:item('queued'),analysis:null});
   }});
 await client.refresh('shipment');
 assert.equal(calls,3);
 assert.equal(states.shipment.status,'done');
 assert.equal(states.shipment.item.id,'queued');
 assert.equal(states.shipment.error,'');
 assert.ok(paused.includes('排队中，等待分析资源'));
});

test('queue receives the stage and the user-retry priority',async()=>{
 const seen=[];
 const {client}=setup({queue:(run,options)=>{seen.push(options);return run();},request:async()=>ok({cached:item('x'),analysis:null})});
 await client.refresh('shipment',true,true);
 await client.refresh('order',false,false);
 assert.deepEqual(seen,[{stage:'shipment',urgent:true},{stage:'order',urgent:false}]);
});
