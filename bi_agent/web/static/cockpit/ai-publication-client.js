/* Server-owned AI slot publications.
 *
 * This client only reads persisted cards.  It never waits for AP queries,
 * metrics or a model job, and a failed poll leaves the last payloads in place.
 */
export const AI_PUBLICATION_REGISTRY = 'cockpit-ai-slots-v1';

export function createAiPublicationClient({
  apiBase, id, request = fetch, onUpdate = () => {}, onError = () => {},
  pollMs = 60000, activeMs = 5000, hiddenMs = 30000,
  isHidden = () => typeof document !== 'undefined' && document.hidden,
  schedule = (fn, ms) => setTimeout(fn, Math.max(250, ms)),
  clear = token => clearTimeout(token),
}) {
  let timer = null, running = false, stopped = true, generation = 0;
  let currentScope = 'default', lastVersion = '';
  const stageCache = new Map();

  function url(scope) {
    const query = new URLSearchParams({id: String(id), uiScope: scope, format:'manifest'});
    return `${apiBase}/ai-publications?${query}`;
  }

  async function load({uiScope = currentScope, preserve = true, force = false} = {}) {
    const token = ++generation;
    const scope = String(uiScope || 'default');
    try {
      const response = await request(url(scope), {headers: {Accept: 'application/json'}});
      let body;
      try { body = await response.json(); } catch (_) { throw new Error('AI 卡片响应无效'); }
      if (!response.ok) throw new Error(typeof body?.detail === 'string' ? body.detail : 'AI 卡片读取失败');
      if (token !== generation) return null;
      if(body.transport==='stage-manifest-v1') {
        const stages=Object.entries(body.stageVersions||{});
        await Promise.all(stages.map(async ([stage,version])=>{
          if(stageCache.get(stage)?.version===version)return;
          const previous=stageCache.get(stage);
          const query=new URLSearchParams({id:String(id)});
          try {
            const r=await request(`${apiBase}/ai-publications/stages/${encodeURIComponent(stage)}?${query}`,{headers:{Accept:'application/json',...(previous?{'If-None-Match':`"${previous.version}"`}:{})}});
            if(r.status===304)return;
            if(!r.ok)throw new Error('环节卡片读取失败');
            const value=await r.json();
            if(token===generation && value.version===version){
              value.slots=Object.fromEntries(Object.entries(value.slots||{}).map(([id,slot])=>[id,{...slot,payload:{...slot.payload,evidence:value.evidence}}]));
              stageCache.set(stage,value);
            }
          }catch(error){if(token===generation)onError(error);}
        }));
        if(token!==generation)return null;
        const slots={};
        for(const [id,meta] of Object.entries(body.slots||{})) {
          const group=stageCache.get(meta.stage), slot=group?.slots?.[id];
          slots[id]=slot?{...(group.version===body.stageVersions[meta.stage]?meta:slot),payload:slot.payload}:{...meta,status:'missing'};
        }
        body={...body,slots};
      }
      const unchanged = !force && body.version === lastVersion && currentScope === scope;
      currentScope = scope;
      lastVersion = body.version || '';
      onUpdate(body, {unchanged, preserve, scope});
      return body;
    } catch (error) {
      if (token !== generation) return null;
      onError(error);
      return null;
    }
  }

  function plan(delay) {
    if (stopped) return;
    if (timer !== null) clear(timer);
    timer = schedule(tick, delay);
  }

  async function tick() {
    timer = null;
    if (stopped || running) return;
    if (isHidden()) { plan(hiddenMs); return; }
    running = true;
    try {
      const value = await load({uiScope: currentScope, preserve: true});
      plan(value?.updatingCount || value?.manualUpdate?.status==='running' ? activeMs : pollMs);
    } finally {
      running = false;
      if (!stopped && timer === null) plan(pollMs);
    }
  }

  return {
    load,
    start(scope = currentScope) {
      currentScope = String(scope || 'default');
      stopped = false;
      plan(0);
    },
    poke(delay = 0, scope = currentScope) {
      currentScope = String(scope || currentScope);
      plan(delay);
    },
    stop() {
      stopped = true;
      generation += 1;
      if (timer !== null) { clear(timer); timer = null; }
    },
    get scope() { return currentScope; },
    get version() { return lastVersion; },
  };
}
