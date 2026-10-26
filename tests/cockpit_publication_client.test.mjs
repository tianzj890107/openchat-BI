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
 const {client,states}=setup({request:async url=>url.endsWith('/refresh')?ok({cached:item('old','上次结果'),analysis:{...item('job'),status:'running'},dataFingerprint:'A'}):poll});
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

test('new filter clears old cards immediately and late completion cannot paint it',async()=>{
 let resolve;const poll=new Promise(r=>resolve=r);
 const {client,states}=setup({request:async url=>url.endsWith('/refresh')?ok({cached:item('old'),analysis:{...item('old-job'),status:'running'}}):poll});
 client.preload({shipment:item('old')});const run=client.refresh('shipment');await new Promise(r=>setImmediate(r));
 client.invalidate();assert.equal(states.shipment.item,null);assert.equal(states.shipment.status,'running');
 resolve(ok(item('old-job','不能显示的旧范围结果')));await run;
 assert.equal(states.shipment.item,null);assert.equal(states.shipment.status,'running');
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
 client.invalidate();assert.equal(states.shipment.item,null);assert.equal(states.order.item,null);
});
