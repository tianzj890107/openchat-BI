/* Persistent last-successful cards and silent revalidation; never reuse another filter's result. */
const {canonical}=await import(new URL('./data-client.js'+new URL(import.meta.url).search,import.meta.url));
export const CARD_CONTRACT = 'cockpit-cards-v1';

export function createPublicationClient({apiBase, stateFor, bodyFor, request=fetch, queue=run=>run(), pause=ms=>new Promise(r=>setTimeout(r,ms)), pollMs=1500}) {
  let generation=0;
  const pending=new Map();
  const known=new Set();
  function preload(items) {
    for(const [stage,item] of Object.entries(items||{})) {
      if(item?.result?.cardContract===CARD_CONTRACT) {known.add(stage);Object.assign(stateFor(stage),{item,status:'done',refreshing:false,error:'',cached:true,stale:false,scopeNotice:''});}
    }
  }
  function invalidate(notice='') {
    generation++;
    pending.clear();
    // A different filter cannot borrow the previous result as evidence, but the
    // user should keep seeing it until the new scope finishes. The card is
    // marked stale and says which scope is loading; only a complete new result
    // replaces it.
    for(const stage of known) {
      const state=stateFor(stage);
      if(state.item) Object.assign(state,{status:'done',refreshing:true,stale:true,cached:false,error:'',
        progress:'正在加载新口径数据',
        scopeNotice:notice||'筛选口径已切换，正在加载新数据；以下仍为上次分析'});
      else Object.assign(state,{status:'running',refreshing:false,stale:false,scopeNotice:'',error:'',progress:'正在分析当前筛选范围'});
    }
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
    if(!response.ok) {
      const error=new Error(typeof body.detail==='string'?body.detail:'分析暂未完成');
      error.status=response.status;
      throw error;
    }
    return body;
  }
  function waitingInQueue(error) {
    return error?.status===429 || /并发|排队/.test(String(error?.message||''));
  }
  function refresh(stage,force=false,urgent=false) {
    stages.add(stage);known.add(stage);
    if(pending.has(stage)) return force?pending.get(stage).then(()=>refresh(stage,true,urgent)):pending.get(stage);
    const token=generation,state=stateFor(stage),current=()=>token===generation;
    state.status=state.item?'done':'running';state.refreshing=Boolean(state.item);state.error='';state.progress='正在加载分析数据';
    const promise=(async()=>{
      // Wait for the page data *before* claiming the analysis slot, so a slow
      // query cannot block an already-ready visible card.
      const body=await bodyFor(stage,force);
      if(!current())return null;
      state.progress='AI 正在分析';
      // Keep the previous scope on screen while the new one is being computed;
      // the freshness notice already tells the user it is not this scope's data.
      if(state.item && !compatible(state.item,body)) Object.assign(state,{status:'done',refreshing:true,stale:true,cached:false,
        scopeNotice:state.scopeNotice||'筛选口径已切换，正在加载新数据；以下仍为上次分析'});
      return queue(async()=>{
      for(let pass=0;pass<2;pass++) {
        let envelope;
        const queueDeadline=Date.now()+240000;
        for(;;) {
          try { envelope=await json(`${apiBase}/analyses/refresh?compact=true`,{method:'POST',headers:{'Content-Type':'application/json','Accept':'application/json'},body:JSON.stringify(body)});break; }
          catch(error) {
            // A full pool means queued, not failed: keep the card loading and
            // poll for a slot instead of showing a concurrency error.
            if(!waitingInQueue(error))throw error;
            if(Date.now()>queueDeadline)throw new Error('分析排队时间较长，请稍后重试');
            if(!current())return null;
            state.progress='排队中，等待分析资源';
            await pause(1500);
          }
        }
        if(!current())return null;
        if(envelope.cached && compatible(envelope.cached,body) && (!envelope.dataFingerprint || envelope.cached.context.dataFingerprint===envelope.dataFingerprint)) Object.assign(state,{item:envelope.cached,status:'done',cached:true});
        else if(envelope.dataFingerprint && state.item?.context.dataFingerprint!==envelope.dataFingerprint) Object.assign(state,{status:state.item?'done':'running',refreshing:Boolean(state.item),cached:false});
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
          item=await json(`${apiBase}/analyses/${encodeURIComponent(item.id)}?compact=true`,{headers:{'Accept':'application/json'}});
          if(!compatible(item,body))throw new Error('分析范围已变化，拒绝旧结果');
        }
        if(!current())return null;
        if(!['completed','limited'].includes(item.status)||item.result?.cardContract!==CARD_CONTRACT) throw new Error(item.error||item.progress||'主服务尚未交付完整卡片');
        // Replace a whole stage atomically, never one half-finished cause/action at a time.
        Object.assign(state,{item,status:'done',cached:false,error:'',progress:'',stale:false,scopeNotice:''});
        if(!envelope.dataFingerprint || item.context.dataFingerprint===envelope.dataFingerprint) return item;
        body.refresh=false; // An older in-flight job may finish first; revalidate the latest AP material once.
      }
      return state.item;
      },{stage,urgent});
    })().catch(error=>{
      if(current()) {
        const message=error.message||'分析更新失败';
        state.error=message;state.status=state.item?'done':'error';
        if(state.item&&state.stale) state.scopeNotice='新口径分析未完成，以下仍为上次分析：'+message;
      }
      return null;
    }).finally(()=>{if(current()){state.refreshing=false;pending.delete(stage);}});
    pending.set(stage,promise);return promise;
  }
  return {preload,invalidate,refresh,stages};
}
