/* No AP endpoint or upstream credential is accepted from the browser. */
export function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value && typeof value === 'object') return `{${Object.keys(value).filter(k => value[k] !== undefined).sort().map(k => `${JSON.stringify(k)}:${canonical(value[k])}`).join(',')}}`;
  return JSON.stringify(value);
}

export function createAPDataClient({apiBase, id, request = fetch, onInvalidate = () => {}}) {
  const active = new Map(), inflight = new Map(), queue = [];
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
    // A filter/page change replaces the previous response for the same query definition.
    return kind + ':' + canonical(Array.isArray(payload) ? payload.map(p => p.analysisConfig) : payload.analysisConfig || payload);
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
    const slot = shape(kind, payload);
    const state = {key: canonical(payload), pending: true, error: '', receiptId: '', expiresAt: 0};
    if (kind !== 'helmet') { const previous=active.get(slot); active.set(slot, state); onInvalidate({replacement:Boolean(previous && previous.key!==state.key)}); }
    const promise = limit(() => proxy(kind, payload)).then(body => {
      if (kind !== 'helmet' && active.get(slot) !== state) throw new Error('查询条件已变化，忽略旧AP响应');
      Object.assign(state, {pending: false, receiptId: body.receiptId, expiresAt: body.expiresAt});
      return body.data;
    }).catch(error => { state.pending = false; state.error = error.message || 'AP查询失败'; throw error; })
      .finally(() => { if(inflight.get(key)===promise) inflight.delete(key); });
    inflight.set(key, promise);
    return promise;
  }
  function scope() {
    const states = [...active.values()];
    if (!states.length || states.some(s => s.pending)) throw new Error('看板AP查询仍在加载，请稍后分析');
    const error = states.find(s => s.error);
    if (error) throw new Error(error.error);
    if (states.some(s => s.expiresAt * 1000 <= Date.now())) throw new Error('看板数据凭据已过期，请刷新页面重新取数');
    return {chartQueries: [...new Set(states.map(s => s.key))].sort(), apReceiptIds: states.map(s => s.receiptId).sort()};
  }
  async function ready() {
    let stable = 0, previous = '';
    for (let attempt = 0; attempt < 450; attempt++) {
      await pause(100);
      const signature = [...active.values()].map(s => `${s.key}:${s.receiptId}:${s.pending}`).join('|');
      stable = signature && signature === previous ? stable + 1 : 0;
      previous = signature;
      if (stable >= 3 && ![...active.values()].some(s => s.pending)) return scope();
    }
    return scope();
  }
  function clearScope() { active.clear(); inflight.clear(); onInvalidate({replacement:true}); }
  return {scope, ready, clearScope, biAdapters: {
    postAnalysisDataQuery: payload => query('analysis', payload),
    postAnalysisDataQueryBatch: payload => query('batch', payload),
  }, utils: {request: async req => {
    try {
      const url = new URL(req.url, globalThis.location?.origin || 'http://localhost');
      if (!['/x360/v1/graphs/helmet-view', '/api/gateway2/x360/v1/graphs/helmet-view'].includes(url.pathname) || (req.method || 'get').toLowerCase() !== 'get') throw new Error('不支持的看板只读接口');
      const data = await query('helmet', req.params || Object.fromEntries(url.searchParams));
      return [null, {data, success: true}];
    } catch (error) { return [error, null]; }
  }}};
}

// Observe committed SDK filter changes, not clicks that merely open a filter editor.
export function observeRuntimeFilters(runtime,onChange,isReady=()=>true) {
  const seen=new Map();
  for(const method of ['setFilterConditions','setButtonGrainSelection']) {
    const original=runtime[method];
    if(typeof original!=='function')continue;
    runtime[method]=function(...args) {
      const key=method+':'+args[0]+':'+canonical(args[2]||null),value=canonical(args[1]);
      const changed=seen.has(key)?seen.get(key)!==value:isReady();
      seen.set(key,value);
      if(changed)onChange();
      return original.apply(this,args);
    };
  }
  return runtime;
}
