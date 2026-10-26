/* Persistent last-successful cards and silent revalidation; never reuse another filter's result. */
const {canonical}=await import(new URL('./data-client.js'+new URL(import.meta.url).search,import.meta.url));
export const CARD_CONTRACT = 'cockpit-cards-v1';

export function createPublicationClient({apiBase, stateFor, bodyFor, request=fetch, queue=run=>run(), pause=ms=>new Promise(r=>setTimeout(r,ms)), pollMs=1500}) {
  let generation=0;
  const pending=new Map();
  const known=new Set();
  function preload(items) {
    for(const [stage,item] of Object.entries(items||{})) {
      if(item?.result?.cardContract===CARD_CONTRACT) {known.add(stage);Object.assign(stateFor(stage),{item,status:'done',refreshing:false,error:'',cached:true});}
    }
  }
  function invalidate() {
    generation++;
    pending.clear();
    // A different filter cannot borrow even a successful result from the previous scope.
    for(const stage of known) Object.assign(stateFor(stage),{item:null,status:'running',refreshing:false,error:'',progress:'正在分析当前筛选范围'});
  }
  const stages=new Set();
  function compatible(item,body) {
    const c=item?.context||{};
    return c.id===body.id && c.engine===body.engine && c.stage===body.stage && c.page===body.page &&
      canonical(c.chartQueries||[])===canonical(body.chartQueries||[]) && canonical(c.clarifications||{})===canonical(body.clarifications||{});
  }
  async function json(url,options) {
    const response=await request(url,options);let body;
    try {body=await response.json();} catch (_) {throw new Error('分析响应无效');}
    if(!response.ok) throw new Error(typeof body.detail==='string'?body.detail:'分析暂未完成');
    return body;
  }
  function refresh(stage,force=false) {
    stages.add(stage);known.add(stage);
    if(pending.has(stage)) return force?pending.get(stage).then(()=>refresh(stage,true)):pending.get(stage);
    const token=generation,state=stateFor(stage),current=()=>token===generation;
    state.status=state.item?'done':'running';state.refreshing=Boolean(state.item);state.error='';
    const promise=queue(async()=>{
      const body=await bodyFor(stage,force);
      if(!current())return null;
      if(state.item && !compatible(state.item,body)) Object.assign(state,{item:null,status:'running',cached:false});
      for(let pass=0;pass<2;pass++) {
        let envelope;
        for(let attempt=0;attempt<4;attempt++) {
          try { envelope=await json(`${apiBase}/analyses/refresh`,{method:'POST',headers:{'Content-Type':'application/json','Accept':'application/json'},body:JSON.stringify(body)});break; }
          catch(error) { if(!/并发/.test(error.message)||attempt===3)throw error;await pause(1000);if(!current())return null; }
        }
        if(!current())return null;
        if(envelope.cached && compatible(envelope.cached,body)) Object.assign(state,{item:envelope.cached,status:'done',cached:true});
        let item=envelope.analysis;
        if(!item)return state.item;
        if(!compatible(item,body)) throw new Error('分析范围不一致，拒绝回填');
        state.jobId=item.id;state.refreshing=Boolean(state.item);
        const deadline=Date.now()+240000;
        while(['queued','running'].includes(item.status)) {
          if(!current())return null;
          if(Date.now()>deadline)throw new Error('分析更新超时');
          state.progress=item.progress||'正在分析当前筛选范围';
          await pause(pollMs);if(!current())return null;
          item=await json(`${apiBase}/analyses/${encodeURIComponent(item.id)}`,{headers:{'Accept':'application/json'}});
          if(!compatible(item,body))throw new Error('分析范围已变化，拒绝旧结果');
        }
        if(!current())return null;
        if(!['completed','limited'].includes(item.status)||item.result?.cardContract!==CARD_CONTRACT) throw new Error(item.error||item.progress||'主服务尚未交付完整卡片');
        // Replace a whole stage atomically, never one half-finished cause/action at a time.
        Object.assign(state,{item,status:'done',cached:false,error:'',progress:''});
        if(!envelope.dataFingerprint || item.context.dataFingerprint===envelope.dataFingerprint) return item;
        body.refresh=false; // An older in-flight job may finish first; revalidate the latest AP material once.
      }
      return state.item;
    }).catch(error=>{
      if(current()) {state.error=error.message||'分析更新失败';state.status=state.item?'done':'error';}
      return null;
    }).finally(()=>{if(current()){state.refreshing=false;pending.delete(stage);}});
    pending.set(stage,promise);return promise;
  }
  return {preload,invalidate,refresh,stages};
}
