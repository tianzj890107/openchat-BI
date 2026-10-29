/* A page is replaced only after all AP data and visible AI slots form one version. */
export function createPageCache({apiBase,id,page,makeClient,bodyFor,onSnapshot=()=>{},onState=()=>{},request=fetch,pause=ms=>new Promise(r=>setTimeout(r,ms))}) {
  let generation=0, pending=null;
  const current=token=>token===generation;
  async function json(path,body) {
    const response=await request(apiBase+path,{headers:{Accept:'application/json',...(body?{'Content-Type':'application/json'}:{})},...(body?{method:'POST',body:JSON.stringify(body)}:{})});
    let value;try{value=await response.json();}catch{throw new Error('完整看板响应无效');}
    if(!response.ok){const error=new Error(typeof value.detail==='string'?value.detail:'完整看板更新失败');error.status=response.status;throw error;}
    return value;
  }
  function invalidate(){generation++;pending=null;}
  async function load(uiScope) {
    const token=generation;
    const value=await json('/page/lookup',{id:Number(id),page,uiScope});
    const snapshot=value.snapshot||value.displaySnapshot||null;
    if(snapshot&&(snapshot.id!==Number(id)||snapshot.page!==page||snapshot.uiScope!==uiScope))throw new Error('完整看板范围不匹配');
    return current(token)?snapshot:null;
  }
  async function status(uiScope) {
    const query=new URLSearchParams({id:String(id),page,uiScope});
    return json('/publications/status?'+query.toString());
  }
  async function publish(client,items,uiScope,token=generation) {
    await client.ready();if(!current(token))return null;
    const entries=client.entries();
    const value=await json('/page',{id:Number(id),page,uiScope,apReceiptIds:entries.map(e=>e.receiptId),analysisIds:Object.fromEntries(Object.entries(items).map(([k,v])=>[k,v.id]))});
    if(!current(token))return null;
    if(value.accepted===false)throw new Error('更新已被较新的完整看板取代');
    return value.snapshot;
  }
  async function analysis(body,token) {
    for(let pass=0;pass<2;pass++) {
      let envelope;
      const queueDeadline=Date.now()+240000;
      for(;;) {
        try { envelope=await json('/analyses/refresh?compact=true',body);break; }
        catch(error) {
          // Full analysis pool = queued, never a card error; wait for a slot.
          if(error.status!==429&&!/并发|排队/.test(String(error.message||'')))throw error;
          if(Date.now()>queueDeadline)throw new Error('后台分析排队超时，保留上次完整看板');
          await pause(1500);if(!current(token))return null;
        }
      }
      if(!current(token))return null;
      if(envelope.cached?.context.dataFingerprint===envelope.dataFingerprint)return envelope.cached;
      let item=envelope.analysis;
      const deadline=Date.now()+240000;
      while(item&&['queued','running'].includes(item.status)) {
        if(Date.now()>deadline)throw new Error('后台分析更新超时，保留上次完整看板');
        await pause(1500);if(!current(token))return null;
        item=await json(`/analyses/${encodeURIComponent(item.id)}?compact=true`);
      }
      if(!item||!['completed','limited'].includes(item.status)||item.result?.cardContract!=='cockpit-cards-v1')throw new Error(item?.error||'后台AI未完整交付，保留上次完整看板');
      if(item.context.dataFingerprint===envelope.dataFingerprint)return item;
      body.refresh=false;
    }
    throw new Error('后台分析数据版本变化，保留上次完整看板');
  }
  function refresh(snapshot,force=false) {
    if(snapshot.id!==Number(id)||snapshot.page!==page)return Promise.resolve(null);
    if(pending)return pending;
    const token=generation;onState({refreshing:true,error:''});
    const work=(async()=>{
      const client=makeClient();
      await Promise.all(snapshot.entries.map(e=>client.read(e.kind,e.payload)));
      const dataScope=await client.ready();if(!current(token))return null;
      const graphs=client.entries().filter(e=>e.kind==='helmet');
      if(snapshot.entries.some(e=>e.kind==='helmet'&&!graphs.some(g=>JSON.stringify(g.payload)===JSON.stringify(e.payload)&&JSON.stringify(g.data)===JSON.stringify(e.data))))throw new Error('流程配置已变化，请刷新页面加载新版本');
      const items={};
      for(const stage of Object.keys(snapshot.items)) {
        items[stage]=await analysis({...bodyFor(stage,force),...dataScope,defaultView:snapshot.uiScope==='default'},token);
        if(!current(token))return null;
      }
      const result=await publish(client,items,snapshot.uiScope,token);
      if(result&&current(token))onSnapshot(result);
      return result;
    })().catch(error=>{if(current(token))onState({error:error.message||'后台更新失败'});return null;})
      .finally(()=>{if(current(token)){pending=null;onState({refreshing:false});}});
    pending=work;return work;
  }
  return {invalidate,load,status,publish,refresh};
}
