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
export const AP_QUERY_CONCURRENCY = 3;
/* A node switch is a view change, not a new data scope. Keep already loaded
 * chart/table responses available long enough for the user to move between
 * nodes without repeating the same AP queries. */
export const DATA_REUSE_WINDOW_MS = 5 * 60 * 1000;

export function createAPDataClient({apiBase, id, request = fetch, onInvalidate = () => {}, snapshot = null, onSnapshotMiss = () => {}, onError = () => {}, onRecover = () => {},
  timeoutMs = AP_QUERY_TIMEOUT_MS, readyTimeoutMs = SCOPE_READY_TIMEOUT_MS, retryWindowMs = TRANSIENT_RETRY_WINDOW_MS,
  idleMs = 3000, concurrency = AP_QUERY_CONCURRENCY, stageFor = () => '', priorityFor = () => ({})}) {
  const active = new Map(), all = new Map(), completed = new Map(), inflight = new Map(), queue = [];
  const controllers = new Set();
  const replay = new Map((snapshot?.entries || []).map(e => [e.kind + ':' + canonical(e.payload), e]));
  let replaying = Boolean(snapshot), missed = false;
  let blocked = '';
  let running = 0, heavyRunning = 0, sequence = 0, generation = 0;
  const limitCount = Math.max(1, Math.min(4, Number(concurrency) || AP_QUERY_CONCURRENCY));
  const heavyLimit = Math.max(1, limitCount - 1);
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  const clock = () => (typeof performance !== 'undefined' && performance.now ? performance.now() : Date.now());
  function hint(job) {
    try { return priorityFor(job.kind, job.payload) || {}; } catch (_) { return {}; }
  }
  function compareJobs(left, right) {
    const a = hint(left), b = hint(right);
    const visible = Number(Boolean(b.visible)) - Number(Boolean(a.visible));
    if (visible) return visible;
    const rank = Number(a.rank || 0) - Number(b.rank || 0);
    if (rank) return rank;
    const heavy = Number(Boolean(a.heavy)) - Number(Boolean(b.heavy));
    if (heavy) return heavy;
    return left.sequence - right.sequence;
  }
  function pump() {
    while (running < limitCount && queue.length) {
      queue.sort(compareJobs);
      const index = queue.findIndex(job => !hint(job).heavy || heavyRunning < heavyLimit);
      if (index < 0) break;
      const [job] = queue.splice(index, 1);
      if (job.generation !== generation) { job.reject(new Error('查询已取消')); continue; }
      const heavy = Boolean(hint(job).heavy);
      running += 1; if (heavy) heavyRunning += 1;
      job.run().then(job.resolve, job.reject).finally(() => {
        running -= 1; if (heavy) heavyRunning -= 1; if (job.controller) controllers.delete(job.controller); pump();
      });
    }
  }
  const limit = (run, kind, payload, controller) => new Promise((resolve, reject) => {
    queue.push({run, resolve, reject, kind, payload, controller, generation, sequence: sequence++}); pump();
  });
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
  function selectedStates(stages) {
    const values = [...active.values()];
    const wanted = new Set((stages || []).filter(Boolean));
    return wanted.size ? values.filter(state => wanted.has(state.stage)) : values;
  }
  async function proxy(kind, payload, controller) {
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
    const state = {key: canonical(payload), pending: true, error: '', labels, receiptId: '', expiresAt: 0,
      stage: stageFor(kind, payload) || '', timings: null};
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
    const queuedAt = clock();
    const jobGeneration = generation;
    const controller = new AbortController();
    const work = replaying ? Promise.resolve({body:{data:entry.data,receiptId:entry.receiptId,receivedAt:entry.receivedAt,expiresAt:entry.expiresAt},timings:{clientQueueMs:0,clientResponseMs:0,replay:true}}) :
      reused && Math.min(reused.expiresAt * 1000, reused.receivedAt * 1000 + DATA_REUSE_WINDOW_MS) > Date.now() ? Promise.resolve({body:reused,timings:{clientQueueMs:0,clientResponseMs:0,reused:true}}) :
        limit(async () => {
          if (jobGeneration !== generation) throw new Error('查询已取消');
          const startedAt = clock();
          const body = await proxy(kind, payload, controller);
          return {body, timings:{clientQueueMs:Math.round(startedAt-queuedAt), clientResponseMs:Math.round(clock()-startedAt)}};
        }, kind, payload, controller);
    if (!replaying && !(reused && Math.min(reused.expiresAt * 1000, reused.receivedAt * 1000 + DATA_REUSE_WINDOW_MS) > Date.now())) {
      controllers.add(controller);
    }
    const promise = work.then(result => {
      const body = result.body;
      if (kind !== 'helmet' && active.get(slot) !== state) throw new Error('查询条件已变化，忽略旧AP响应');
      if (all.get(slot) !== state) throw new Error('查询条件已变化，忽略旧AP响应');
      completed.set(key, body);
      const timings = {...(body.timings || {}), ...(result.timings || {})};
      Object.assign(state, {pending: false, error: '', receiptId: body.receiptId, expiresAt: body.expiresAt, timings,
        entry:{kind,payload,data:body.data,receiptId:body.receiptId,receivedAt:body.receivedAt,expiresAt:body.expiresAt,timings}});
      if (typeof console !== 'undefined' && console.debug) {
        console.debug('[cockpit-ap-timing]', {kind, stage: state.stage, key: state.key, ...timings});
      }
      recovered();
      return body.data;
    }).catch(error => {
      // A cleared scope aborts its old requests. Their late rejection must not
      // re-open an error banner for the new, already-rendered view.
      if (jobGeneration === generation && error.name !== 'AbortError') {
        state.pending = false;
        const detail = error.message || 'AP查询失败';
        state.error = (labels.length ? '指标 ' + labels.join('、') + '：' : '') + detail;
        notify(state.error, kind);
      }
      throw error;
    })
      .finally(() => { if(inflight.get(key)===promise) inflight.delete(key); });
    inflight.set(key, promise);
    return promise;
  }
  function scope(options=false) {
    const {allowExpired=false, partial=false, stages=[]} = typeof options === 'object' ? options : {allowExpired: Boolean(options)};
    if(blocked)throw new Error(blocked);
    const states = selectedStates(stages);
    if (!states.length) throw new Error(stages.length ? '当前环节尚无看板查询数据，请稍后重试' : '看板AP查询仍在加载，请稍后分析');
    if (states.some(s => s.pending)) throw new Error('看板AP查询仍在加载，请稍后分析');
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
    const {allowExpired=false, partial=false, stages=[]} = typeof options === 'boolean' ? {allowExpired: options} : options;
    let stable = 0, previous = '', idle = 0;
    const deadline = Date.now() + readyTimeoutMs;
    while (Date.now() < deadline) {
      await pause(100);
      const current = selectedStates(stages);
      // A page that never starts a query must not hold the caller for the
      // whole long-AP budget; give the components a short settle window.
      if (!current.length) { if (++idle >= Math.max(1, Math.ceil(idleMs / 100))) break; continue; }
      idle = 0;
      const signature = current.map(s => `${s.key}:${s.receiptId}:${s.pending}`).join('|');
      stable = signature && signature === previous ? stable + 1 : 0;
      previous = signature;
      if (stable >= 3 && !current.some(s => s.pending)) {
        if (!partial) {
          const failed=current.find(s=>s.error);
          if(failed)throw new Error(failed.error);
        }
        return scope({allowExpired, partial, stages});
      }
    }
    // Data preparation may legitimately take as long as the AP budget itself;
    // falling through only reports what is actually ready, never a timeout error.
    return scope({allowExpired, partial, stages});
  }
  function clearScope() {
    generation += 1;
    for (const controller of controllers) { try { controller.abort(); } catch (_) {} }
    controllers.clear();
    for (const job of queue.splice(0)) { try { job.reject(new Error('查询已取消')); } catch (_) {} }
    active.clear(); all.clear(); completed.clear(); inflight.clear(); replay.clear(); replaying=false;
    onInvalidate({replacement:true});
  }
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
  // ProUI emits its delivered default filters (for example YEAR grain while a
  // page is mounting).  Those calls are configuration, not a user scope
  // change.  Treating them as a real filter change cleared the data client and
  // remounted the board, which started the whole page over again.  Keep a
  // separate initialization phase until the first genuine user interaction.
  let phase=restored?.phase||(hooks.isUserAction?'initializing':'armed');
  // A committed filter change can land while the page is still loading its
  // data. Keep only the latest one and apply it once the client is ready;
  // dropping it made the first user change look like no change at all.
  let pending=null;
  // Helmet/container node selection is a view choice, not a new business
  // filter.  Treating it as a scope change cleared the data client and rebuilt
  // the whole board, so switching from 投标 to 报价 repeated every AP query.
  // Keep node calls in the replay map, but only real filter methods feed the
  // data-scope key.
  const observed=new Set(['setFilterConditions','setButtonGrainSelection']);
  const viewMethods=['setHelmetGraphSelection','setContainerActiveNode'];
  for(const method of [...observed,...viewMethods,'setFilterUiSelection','setTemplateState','setTabTemplateOverrides','setActiveTab','setSelectionGroupActive','clearHelmetGraphSelection','clearContainerActiveNode']) {
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
      const changed=seen.has(key)?seen.get(key)!==value:true;
      seen.set(key,value);
      const scope=canonical([...seen].sort());
      const detail=summarizeFilterChange(method,args);
      const userAction=hooks.isUserAction?Boolean(hooks.isUserAction()):true;
      if(phase==='initializing'&&!userAction)return original.apply(this,args);
      if(phase==='initializing')phase='armed';
      if(changed&&userAction&&isReady()) {
        if(baseline===null)baseline=before;
        onChange(scope===baseline?'default':scope,detail);
      } else if(changed&&userAction) {
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
    return {seen:[...seen],baseline,calls:[...calls],phase};
  };
  return runtime;
}
