/* No AP endpoint or upstream credential is accepted from the browser. */
export function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value && typeof value === 'object') return `{${Object.keys(value).filter(k => value[k] !== undefined).sort().map(k => `${JSON.stringify(k)}:${canonical(value[k])}`).join(',')}}`;
  return JSON.stringify(value);
}

/* The AP backend now allows a three-minute SQL budget, so every layer between
 * the browser and the upstream has to wait longer than the old 35 s page
 * timeout. Keep a margin for network and receipt handling. */
export const AP_QUERY_TIMEOUT_MS = 200000;
export const SCOPE_READY_TIMEOUT_MS = 220000;
export const TRANSIENT_RETRY_WINDOW_MS = 30000;

export function createAPDataClient({apiBase, id, request = fetch, onInvalidate = () => {}, snapshot = null, onSnapshotMiss = () => {}, onError = () => {}, onRecover = () => {},
  timeoutMs = AP_QUERY_TIMEOUT_MS, readyTimeoutMs = SCOPE_READY_TIMEOUT_MS, retryWindowMs = TRANSIENT_RETRY_WINDOW_MS,
  idleMs = 3000}) {
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
  function queryLabels(payload) {
    const labels = [], codes = [], stack = [payload];
    while (stack.length) {
      const value = stack.pop();
      if (Array.isArray(value)) { stack.push(...value); continue; }
      if (!value || typeof value !== 'object') continue;
      for (const key of ['alias', 'label', 'name']) {
        if (typeof value[key] === 'string' && value[key].trim()) labels.push(value[key].trim());
      }
      if (typeof value.identifierCode === 'string' && value.identifierCode.trim()) codes.push(value.identifierCode.trim());
      for (const child of Object.values(value)) {
        if (child && typeof child === 'object') stack.push(child);
      }
    }
    const unique = [...new Set(labels.length ? labels : codes)];
    return unique.slice(0, 6);
  }
  function notify(error, kind) { try { onError(error, {kind}); } catch (_) {} }
  function recovered() {
    if (![...all.values()].some(state => state.error)) { try { onRecover(); } catch (_) {} }
  }
  function shape(kind, payload) {
    // Different widgets may share measures but use different status filters.
    // Keep each full query; committed SDK filter changes clear the whole scope.
    return kind + ':' + canonical(payload);
  }
  async function proxy(kind, payload) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    try {
      let response, body;
      for (let attempt = 0; attempt < 3; attempt++) {
        const attemptStarted = Date.now();
        response = await request(`${apiBase}/data/query`, {method: 'POST', signal: controller.signal,
          headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
          body: JSON.stringify({id: Number(id), kind, payload})});
        try { body = await response.json(); } catch (_) { body = null; }
        const queued = response.status === 429 || (response.status === 504 && /排队/.test(String(body?.detail || '')));
        // One bounded retry for an early transient failure; never retry a
        // deterministic 502, and never replay a 504 that already consumed the
        // long AP budget - that would silently double the user's wait.
        const transientTimeout = response.status === 504 && !queued && attempt === 0 &&
          Date.now() - attemptStarted < retryWindowMs;
        if ((!queued && !transientTimeout) || attempt === 2) break;
        await pause(queued ? 300 * (attempt + 1) : 600);
      }
      if (!body) throw new Error('看板AP代理响应无效');
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
    const labels = queryLabels(payload);
    const state = {key: canonical(payload), pending: true, error: '', labels, receiptId: '', expiresAt: 0};
    all.set(slot, state);
    if (kind !== 'helmet') { const previous=active.get(slot); active.set(slot, state); onInvalidate({replacement:Boolean(previous && previous.key!==state.key)}); }
    const config = payload && payload.analysisConfig;
    if (kind === 'analysis' && config && Array.isArray(config.vertex) && !config.vertex.length
        && !(config.indicators || []).length && !(config.dimensions || []).length) {
      // Delivered metadata with an empty vertex block cannot become a valid
      // AP query; stop before the upstream returns a misleading gateway error.
      const error = new Error('看板组件未配置实体查询字段，已跳过空查询');
      state.pending = false; state.error = error.message; notify(state.error, kind);
      const rejected = Promise.reject(error);
      rejected.catch(() => {});
      inflight.set(key, rejected);
      return rejected;
    }
    const reused = completed.get(key);
    const entry = replay.get(key);
    const work = replaying ? Promise.resolve({data:entry.data,receiptId:entry.receiptId,receivedAt:entry.receivedAt,expiresAt:entry.expiresAt}) :
      reused && Math.min(reused.expiresAt * 1000, reused.receivedAt * 1000 + 15000) > Date.now() ? Promise.resolve(reused) : limit(() => proxy(kind, payload));
    const promise = work.then(body => {
      if (kind !== 'helmet' && active.get(slot) !== state) throw new Error('查询条件已变化，忽略旧AP响应');
      if (all.get(slot) !== state) throw new Error('查询条件已变化，忽略旧AP响应');
      completed.set(key, body);
      Object.assign(state, {pending: false, error: '', receiptId: body.receiptId, expiresAt: body.expiresAt,
        entry:{kind,payload,data:body.data,receiptId:body.receiptId,receivedAt:body.receivedAt,expiresAt:body.expiresAt}});
      recovered();
      return body.data;
    }).catch(error => {
      state.pending = false;
      const detail = error.message || 'AP查询失败';
      state.error = (labels.length ? '指标 ' + labels.join('、') + '：' : '') + detail;
      notify(state.error, kind);
      throw error;
    })
      .finally(() => { if(inflight.get(key)===promise) inflight.delete(key); });
    inflight.set(key, promise);
    return promise;
  }
  function scope(options=false) {
    const {allowExpired=false, partial=false} = typeof options === 'object' ? options : {allowExpired: Boolean(options)};
    if(blocked)throw new Error(blocked);
    const states = [...active.values()];
    if (!states.length || states.some(s => s.pending)) throw new Error('看板AP查询仍在加载，请稍后分析');
    if (!partial) {
      const error = states.find(s => s.error);
      if (error) throw new Error(error.error);
      if (!allowExpired && states.some(s => s.expiresAt * 1000 <= Date.now())) throw new Error('看板数据凭据已过期，请刷新页面重新取数');
      return {chartQueries: [...new Set(states.map(s => s.key))].sort(), apReceiptIds: states.map(s => s.receiptId).sort()};
    }
    const now = Date.now(), usable = [], unavailable = [];
    for (const state of states) {
      if (state.error) unavailable.push({query: state.key, labels: state.labels, error: state.error});
      else if (!allowExpired && state.expiresAt * 1000 <= now) unavailable.push({query: state.key, labels: state.labels, error: '看板数据凭据已过期，请刷新页面重新取数'});
      else if (!state.receiptId) unavailable.push({query: state.key, labels: state.labels, error: '看板AP响应缺少服务端结果凭据'});
      else usable.push(state);
    }
    if (!usable.length) {
      if (!unavailable.length) throw new Error('看板AP查询仍在加载，请稍后分析');
      // Every page query failed. The main service may still answer the
      // registered subset from PostgreSQL, so hand it the failed queries as
      // the declared unavailable scope instead of blocking the analysis here.
      return {chartQueries: [], apReceiptIds: [], unavailable};
    }
    return {chartQueries: [...new Set(usable.map(s => s.key))].sort(), apReceiptIds: [...new Set(usable.map(s => s.receiptId))].sort(), unavailable};
  }
  async function ready(options={}) {
    const {allowExpired=false, partial=false} = typeof options === 'boolean' ? {allowExpired: options} : options;
    let stable = 0, previous = '', idle = 0;
    const deadline = Date.now() + readyTimeoutMs;
    while (Date.now() < deadline) {
      await pause(100);
      // A page that never starts a query must not hold the caller for the
      // whole long-AP budget; give the components a short settle window.
      if (!all.size) { if (++idle >= Math.max(1, Math.ceil(idleMs / 100))) break; continue; }
      idle = 0;
      const signature = [...all.values()].map(s => `${s.key}:${s.receiptId}:${s.pending}`).join('|');
      stable = signature && signature === previous ? stable + 1 : 0;
      previous = signature;
      if (stable >= 3 && ![...all.values()].some(s => s.pending)) {
        if (!partial) {
          const failed=[...all.values()].find(s=>s.error);
          if(failed)throw new Error(failed.error);
        }
        return scope({allowExpired, partial});
      }
    }
    // Data preparation may legitimately take as long as the AP budget itself;
    // falling through only reports what is actually ready, never a timeout error.
    return scope({allowExpired, partial});
  }
  function clearScope() { active.clear(); all.clear(); completed.clear(); inflight.clear(); replay.clear(); replaying=false; onInvalidate({replacement:true}); }
  function failures() {
    return [...new Set([...all.values()].filter(state => state.error).map(state => state.error))];
  }
  function entries() {
    if(!all.size || [...all.values()].some(s=>s.pending||s.error||!s.entry))throw new Error('看板数据未完整加载');
    return JSON.parse(JSON.stringify([...all.values()].map(s=>s.entry)));
  }
  return {scope, ready, clearScope, entries, failures, read:query, block:message=>{blocked=message;}, biAdapters: {
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

/* Turn a committed filter condition list into a short, human-readable scope
 * hint for the card notice. Unknown shapes simply yield '' and the UI falls
 * back to the generic notice; internal codes are never shown. */
export function summarizeFilterChange(method,args) {
  if(method!=='setFilterConditions')return '';
  const parts=[],pushed=new Set();
  const emit=(label,values)=>{
    if(!label||!values.length||parts.length>=3)return;
    const text=`${label}：${values.join(' 至 ')}`;
    if(!pushed.has(text)){pushed.add(text);parts.push(text);}
  };
  const scalars=value=>{
    const list=Array.isArray(value)?value:[value],out=[];
    for(const item of list){
      if(item===null||item===undefined||item==='')continue;
      if(typeof item==='string'||typeof item==='number'){out.push(String(item));continue;}
      if(typeof item==='object')for(const key of ['label','name','text','value','title']){
        const text=item[key];
        if(typeof text==='string'||typeof text==='number'){out.push(String(text));break;}
      }
    }
    return [...new Set(out)].slice(0,4);
  };
  const walk=(value,label)=>{
    if(Array.isArray(value)){value.forEach(item=>walk(item,label));return;}
    if(!value||typeof value!=='object')return;
    const own=[value.label,value.labelName,value.alias,value.title,value.dimension?.label,value.dim?.label]
      .find(text=>typeof text==='string'&&text.trim());
    const next=own||label,values=[];
    for(const key of ['value','values','selected','selectedValues','range','conditionValues']){
      const picked=scalars(value[key]);
      if(picked.length){values.push(...picked);break;}
    }
    if(own&&values.length)emit(own,values);
    for(const child of Object.values(value))if(child&&typeof child==='object')walk(child,next);
  };
  walk(args?.[1]);
  return parts.join('；');
}

// Observe committed SDK filter changes, not clicks that merely open a filter editor.
export function observeRuntimeFilters(runtime,onChange,isReady=()=>true,restored=null,hooks={}) {
  const seen=new Map(restored?.seen||[]),calls=new Map(restored?.calls||[]);
  let baseline=restored?.baseline??null;
  // A committed filter change can land while the page is still loading its
  // data. Keep only the latest one and apply it once the client is ready;
  // dropping it made the first user change look like no change at all.
  let pending=null;
  const observed=new Set(['setFilterConditions','setButtonGrainSelection','setHelmetGraphSelection','setContainerActiveNode']);
  for(const method of [...observed,'setFilterUiSelection','setTemplateState','setTabTemplateOverrides','setActiveTab','setSelectionGroupActive','clearHelmetGraphSelection','clearContainerActiveNode']) {
    const original=runtime[method];
    if(typeof original!=='function')continue;
    runtime[method]=function(...args) {
      const key=method+':'+args[0]+':'+canonical(method==='setFilterUiSelection'?[args[1],args[3]||null]:args[2]||null);
      calls.delete(key);calls.set(key,[method,JSON.parse(JSON.stringify(args))]);
      if(!observed.has(method)){
        const made=original.apply(this,args);
        // Delivered activate rules drive tabs and helmet nodes through the runtime;
        // the host mirrors them so the route, its data scope and its cards stay aligned.
        if(method==='setActiveTab')hooks.onTabChange?.(args[1]);
        else if(method==='setHelmetGraphSelection')hooks.onHelmetSelect?.(args[0],args[1]);
        return made;
      }
      if(method==='setHelmetGraphSelection')hooks.onHelmetSelect?.(args[0],args[1]);
      const selection=method==='setContainerActiveNode'?{nodeId:args[1]?.nodeId}:args[1];
      const value=canonical(selection);
      // The baseline is the scope *before* the first observed change; keeping
      // the pre-change map is what makes "switch back to default" detectable.
      const before=baseline===null?canonical([...seen].sort()):baseline;
      const changed=seen.has(key)?seen.get(key)!==value:isReady();
      seen.set(key,value);
      const scope=canonical([...seen].sort());
      const detail=summarizeFilterChange(method,args);
      if(changed&&isReady()) {
        if(baseline===null)baseline=before;
        onChange(scope===baseline?'default':scope,detail);
      } else if(changed) {
        pending={scope,detail,before};
      }
      return original.apply(this,args);
    };
  }
  runtime.flushPendingScope=()=>{
    if(!pending||!isReady())return false;
    const {scope,detail,before}=pending;pending=null;
    if(baseline===null)baseline=before;
    onChange(scope===baseline?'default':scope,detail);
    return true;
  };
  runtime.replayView=target=>{
    for(const [method,args] of calls.values())if(typeof target[method]==='function')target[method](...args);
    return {seen:[...seen],baseline,calls:[...calls]};
  };
  return runtime;
}
