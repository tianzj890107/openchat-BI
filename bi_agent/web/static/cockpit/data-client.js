/* No AP endpoint or upstream credential is accepted from the browser. */
export function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value && typeof value === 'object') return `{${Object.keys(value).filter(k => value[k] !== undefined).sort().map(k => `${JSON.stringify(k)}:${canonical(value[k])}`).join(',')}}`;
  return JSON.stringify(value);
}

export function createAPDataClient({apiBase, id, request = fetch, onInvalidate = () => {}, snapshot = null, onSnapshotMiss = () => {}}) {
  const active = new Map(), all = new Map(), completed = new Map(), inflight = new Map(), queue = [];
  const replay = new Map((snapshot?.entries || []).map(e => [e.kind + ':' + canonical(e.payload), e]));
  let replaying = Boolean(snapshot), missed = false;
  let blocked = '';
  let running = 0;
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  function pump() {
    while (running < 2 && queue.length) {
      const job = queue.shift(); running++;
      job.run().then(job.resolve, job.reject).finally(() => { running--; pump(); });
    }
  }
  const limit = run => new Promise((resolve, reject) => { queue.push({run, resolve, reject}); pump(); });
  function shape(kind, payload) {
    // Different widgets may share measures but use different status filters.
    // Keep each full query; committed SDK filter changes clear the whole scope.
    return kind + ':' + canonical(payload);
  }
  async function proxy(kind, payload) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 35000);
    try {
      let response;
      for (let attempt = 0; attempt < 3; attempt++) {
        response = await request(`${apiBase}/data/query`, {method: 'POST', signal: controller.signal,
          headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
          body: JSON.stringify({id: Number(id), kind, payload})});
        if (response.status !== 429 || attempt === 2) break;
        await pause(300 * (attempt + 1));
      }
      let body;
      try { body = await response.json(); } catch (_) { throw new Error('看板AP代理响应无效'); }
      if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : '看板AP查询失败');
      if (!body.receiptId || body.data === undefined) throw new Error('看板AP响应缺少服务端结果凭据');
      return body;
    } catch (error) {
      if (error.name === 'AbortError') throw new Error('看板AP请求超时，请重试');
      throw error;
    } finally { clearTimeout(timeout); }
  }
  function query(kind, payload) {
    // Freeze ProUI's input; reactive filters may mutate it while a request is pending.
    payload = JSON.parse(JSON.stringify(payload));
    const key = kind + ':' + canonical(payload);
    if (inflight.has(key)) return inflight.get(key);
    if (replaying && !replay.has(key)) {
      if (!missed) {missed = true; queueMicrotask(onSnapshotMiss);}
      return Promise.reject(new Error('当前范围没有完整缓存，正在重新取数'));
    }
    const slot = shape(kind, payload);
    const state = {key: canonical(payload), pending: true, error: '', receiptId: '', expiresAt: 0};
    all.set(slot, state);
    if (kind !== 'helmet') { const previous=active.get(slot); active.set(slot, state); onInvalidate({replacement:Boolean(previous && previous.key!==state.key)}); }
    const reused = completed.get(key);
    const entry = replay.get(key);
    const work = replaying ? Promise.resolve({data:entry.data,receiptId:entry.receiptId,receivedAt:entry.receivedAt,expiresAt:entry.expiresAt}) :
      reused && Math.min(reused.expiresAt * 1000, reused.receivedAt * 1000 + 15000) > Date.now() ? Promise.resolve(reused) : limit(() => proxy(kind, payload));
    const promise = work.then(body => {
      if (kind !== 'helmet' && active.get(slot) !== state) throw new Error('查询条件已变化，忽略旧AP响应');
      if (all.get(slot) !== state) throw new Error('查询条件已变化，忽略旧AP响应');
      completed.set(key, body);
      Object.assign(state, {pending: false, receiptId: body.receiptId, expiresAt: body.expiresAt,
        entry:{kind,payload,data:body.data,receiptId:body.receiptId,receivedAt:body.receivedAt,expiresAt:body.expiresAt}});
      return body.data;
    }).catch(error => { state.pending = false; state.error = error.message || 'AP查询失败'; throw error; })
      .finally(() => { if(inflight.get(key)===promise) inflight.delete(key); });
    inflight.set(key, promise);
    return promise;
  }
  function scope(allowExpired=false) {
    if(blocked)throw new Error(blocked);
    const states = [...active.values()];
    if (!states.length || states.some(s => s.pending)) throw new Error('看板AP查询仍在加载，请稍后分析');
    const error = states.find(s => s.error);
    if (error) throw new Error(error.error);
    if (!allowExpired && states.some(s => s.expiresAt * 1000 <= Date.now())) throw new Error('看板数据凭据已过期，请刷新页面重新取数');
    return {chartQueries: [...new Set(states.map(s => s.key))].sort(), apReceiptIds: states.map(s => s.receiptId).sort()};
  }
  async function ready({allowExpired=false}={}) {
    let stable = 0, previous = '';
    for (let attempt = 0; attempt < 450; attempt++) {
      await pause(100);
      const signature = [...all.values()].map(s => `${s.key}:${s.receiptId}:${s.pending}`).join('|');
      stable = signature && signature === previous ? stable + 1 : 0;
      previous = signature;
      if (stable >= 3 && ![...all.values()].some(s => s.pending)) {
        const failed=[...all.values()].find(s=>s.error);
        if(failed)throw new Error(failed.error);
        return scope(allowExpired);
      }
    }
    return scope(allowExpired);
  }
  function clearScope() { active.clear(); all.clear(); completed.clear(); inflight.clear(); replay.clear(); replaying=false; onInvalidate({replacement:true}); }
  function entries() {
    if(!all.size || [...all.values()].some(s=>s.pending||s.error||!s.entry))throw new Error('看板数据未完整加载');
    return JSON.parse(JSON.stringify([...all.values()].map(s=>s.entry)));
  }
  return {scope, ready, clearScope, entries, read:query, block:message=>{blocked=message;}, biAdapters: {
    postAnalysisDataQuery: payload => query('analysis', payload),
  }, utils: {request: async req => {
    try {
      const url = new URL(req.url, globalThis.location?.origin || 'http://localhost');
      if (!['/x360/v1/graphs/helmet-view', '/api/gateway2/x360/v1/graphs/helmet-view'].includes(url.pathname) || (req.method || 'get').toLowerCase() !== 'get') throw new Error('不支持的看板只读接口');
      const data = await query('helmet', req.params || Object.fromEntries(url.searchParams));
      return [null, {data, success: true}];
    } catch (error) { return [error, null]; }
  }}};
}

// The host renders one tab per route. ProUI emits activation actions into the
// shared runtime; translate the committed tab/node selection into host state.
export function observeActivationActions(runtime, {onTabChange=()=>{},onHelmetSelection=()=>{}}={}) {
  for(const [method,callback] of [['setActiveTab',onTabChange],['setHelmetGraphSelection',onHelmetSelection]]) {
    const original=runtime[method];
    if(typeof original!=='function')continue;
    runtime[method]=function(...args) {
      const result=original.apply(this,args);
      callback(...args);
      return result;
    };
  }
  return runtime;
}

// Observe committed SDK filter changes, not clicks that merely open a filter editor.
export function observeRuntimeFilters(runtime,onChange,isReady=()=>true,restored=null) {
  const seen=new Map(restored?.seen||[]),calls=new Map(restored?.calls||[]);
  let baseline=restored?.baseline??null;
  const observed=new Set(['setFilterConditions','setButtonGrainSelection','setHelmetGraphSelection','setContainerActiveNode']);
  for(const method of [...observed,'setFilterUiSelection','setTemplateState','setTabTemplateOverrides','setActiveTab','setSelectionGroupActive','clearHelmetGraphSelection','clearContainerActiveNode']) {
    const original=runtime[method];
    if(typeof original!=='function')continue;
    runtime[method]=function(...args) {
      const key=method+':'+args[0]+':'+canonical(method==='setFilterUiSelection'?[args[1],args[3]||null]:args[2]||null);
      calls.delete(key);calls.set(key,[method,JSON.parse(JSON.stringify(args))]);
      if(!observed.has(method))return original.apply(this,args);
      const selection=method==='setContainerActiveNode'?{nodeId:args[1]?.nodeId}:args[1];
      const value=canonical(selection);
      const changed=seen.has(key)?seen.get(key)!==value:isReady();
      if(changed&&isReady()&&baseline===null)baseline=canonical([...seen].sort());
      seen.set(key,value);
      if(changed&&isReady()) {
        const scope=canonical([...seen].sort());
        onChange(scope===baseline?'default':scope);
      }
      return original.apply(this,args);
    };
  }
  runtime.replayView=target=>{
    for(const [method,args] of calls.values())if(typeof target[method]==='function')target[method](...args);
    return {seen:[...seen],baseline,calls:[...calls]};
  };
  return runtime;
}
