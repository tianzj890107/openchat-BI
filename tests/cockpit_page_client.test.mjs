import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createPageCache} from '../bi_agent/web/static/cockpit/page-client.js';
const card=id=>({id,status:'limited',context:{dataFingerprint:'new'},result:{cardContract:'cockpit-cards-v1'}});
const snapshot={id:1,page:'analysis',uiScope:'default',version:'old',entries:[{kind:'analysis',payload:{filter:'A'},receiptId:'old-r'}],items:{shipment:card('old-s'),opportunity:card('old-o')}};
const ok=value=>({ok:true,json:async()=>value});
const fresh=()=>({read:async()=>{},ready:async()=>({chartQueries:['A'],apReceiptIds:['fresh-r']}),entries:()=>[{receiptId:'fresh-r'}]});
const setup=(options={})=>{const shown=[],states=[],bodies=[];return {shown,states,bodies,client:createPageCache({apiBase:'/api/cockpit',id:'1',page:'analysis',makeClient:fresh,bodyFor:stage=>({stage,engine:'main'}),onSnapshot:p=>shown.push(p),onState:s=>states.push(s),pause:async()=>{},request:async(path,opts)=>{const body=JSON.parse(opts.body);bodies.push({path,body});if(path.endsWith('/page'))return ok({accepted:true,snapshot:{...snapshot,version:'new'}});return ok({cached:card(body.stage),dataFingerprint:'new',analysis:null});},...options})};};

test('background publishes the whole matching page only after every slot is ready',async()=>{
 let resolve;const last=new Promise(r=>resolve=r);let count=0;
 const {client,shown,bodies}=setup({request:async(path,opts)=>{
  const body=JSON.parse(opts.body);bodies.push({path,body});
  if(path.endsWith('/page'))return ok({accepted:true,snapshot:{...snapshot,version:'new'}});
  if(++count===2)return last;
  return ok({cached:card(body.stage),dataFingerprint:'new'});
 }});
 const first=client.refresh(snapshot),duplicate=client.refresh(snapshot);assert.equal(first,duplicate);
 await new Promise(r=>setImmediate(r));assert.equal(shown.length,0);assert.equal(snapshot.version,'old');
 resolve(ok({cached:card('new-opportunity'),dataFingerprint:'new'}));await first;
 assert.equal(shown.length,1);assert.equal(shown[0].version,'new');
 assert.deepEqual(bodies.at(-1).body.analysisIds,{shipment:'shipment',opportunity:'new-opportunity'});
 assert.deepEqual(bodies.at(-1).body.apReceiptIds,['fresh-r']);
});

test('AP failure keeps old charts and cards together and never starts a model',async()=>{
 const {client,shown,states,bodies}=setup({makeClient:()=>({...fresh(),read:async()=>{throw new Error('AP failed');}})});
 await client.refresh(snapshot);assert.equal(shown.length,0);assert.equal(bodies.length,0);assert.equal(snapshot.version,'old');assert.match(states.find(s=>s.error)?.error,/AP failed/);
});

test('scope changes reject an old pending AP response and publication',async()=>{
 let resolve;const wait=new Promise(r=>resolve=r);
 const {client,shown,bodies}=setup({makeClient:()=>({...fresh(),read:()=>wait})});
 const run=client.refresh(snapshot);client.invalidate();resolve();await run;assert.equal(shown.length,0);assert.equal(bodies.length,0);
});

test('missing or partial card contract cannot publish a mixed page',async()=>{
 const {client,shown,states}=setup({request:async()=>ok({analysis:{id:'bad',status:'limited',result:{summary:'partial'}},dataFingerprint:'new'})});
 await client.refresh(snapshot);assert.equal(shown.length,0);assert.match(states.find(s=>s.error)?.error,/未完整交付/);
});

test('new filter lookup is exact and wrong-role snapshots are rejected',async()=>{
 const {client}=setup({request:async()=>ok({snapshot:{...snapshot,id:2}})});
 await assert.rejects(client.load('department-B'),/范围不匹配/);
 assert.equal(await client.refresh({...snapshot,id:2}),null);
});
