/* The cockpit renders one delivered ProBiDashboard from iba-demo demo_1021.
 * Three tabs, their templates, component positions and insight placements are
 * used verbatim. The host only supplies the Fuxi identity (id=1|2), rewrites
 * the selected tab into the route path and consumes main-service AP results.
 */
(async () => {
  'use strict';
  const frozenAnnualMode = window.COCKPIT_FIXED_ANNUAL === true;

  const root = document.querySelector('meta[name="app-root"]').content.replace(/\/$/, '');
  const routeRoot = location.pathname.replace(/\/cockpit(?:\/(?:home|overview|operations|analysis))?\/?$/, '');
  const assetVersion = document.querySelector('meta[name="cockpit-version"]')?.content || '1';
  const {taskProgressText,newStageFailures}=await import(`./task-progress.js?v=${assetVersion}`);
  const assetBase = document.querySelector('meta[name="cockpit-assets"]')?.content || `${root}/static/cockpit`;
  const {selectSlotAnalysis}=await import(`./publication-selection.js?v=${assetVersion}`);
  const runtimeUrl = `${assetBase}/metadata/runtime.json?v=${encodeURIComponent(assetVersion)}`;
  const snapshotsUrl = `${assetBase}/metadata/pdt-release-2109836674373566465/data-snapshots.json?v=${encodeURIComponent(assetVersion)}`;
  const insightBundleUrl = `${assetBase}/insight-components/index.js?v=${encodeURIComponent(assetVersion)}`;
  const apiBase = (document.querySelector('meta[name="cockpit-api-base"]')?.content || `${root}/api/cockpit`).replace(/\/$/, '');
  const DEPARTMENT = '全部产品部';
  const params = new URLSearchParams(location.search);
  let analysisEngine = params.get('engine') === 'standalone' ? 'standalone' : 'main';
  const baselineId = params.get('baseline') || '';
  let baselineItem = null;
  const identityId = ['1', '2'].includes(params.get('id')) ? params.get('id') : '1';
  let defaultPeriod = String(new Date().getFullYear());
  let activePeriod = defaultPeriod;
  let preheatPeriods = [defaultPeriod];

  function periodText(value) {
    const text = String(value ?? '').trim();
    if (!text) return '';
    const month = text.match(/(20\d{2})\s*[-/年.]\s*(\d{1,2})/);
    if (month) {
      const number = Number(month[2]);
      return number >= 1 && number <= 12 ? `${month[1]}-${String(number).padStart(2, '0')}` : '';
    }
    const year = text.match(/(?<!\d)(20\d{2})(?!\d)/);
    return year ? year[1] : '';
  }

  const PERIOD_FILTER_ID = 'YWLN_D044';
  const PERIOD_FILTER_YEAR = '2025';
  const PERIOD_FILTER_MONTHS = Array.from({length: 12},
    (_, index) => `${PERIOD_FILTER_YEAR}-${String(index + 1).padStart(2, '0')}`);

  function periodGrain(value) {
    let raw = value;
    if (raw && typeof raw === 'object') raw = raw.value || raw.code || raw.grain || '';
    if (typeof raw === 'string') {
      try {
        const decoded = JSON.parse(raw);
        if (typeof decoded === 'string') raw = decoded;
        else if (decoded && typeof decoded === 'object') raw = decoded.value || decoded.code || decoded.grain || raw;
      } catch (_) { /* plain YEAR/MONTH */ }
    }
    const text = String(raw || '').trim().toUpperCase();
    if (text.includes('MONTH') || text === 'M' || text === '月') return 'MONTH';
    if (text.includes('YEAR') || text === 'Y' || text === '年') return 'YEAR';
    return '';
  }

  function periodFilterOptions(grain) {
    const values = grain === 'MONTH' ? PERIOD_FILTER_MONTHS : [PERIOD_FILTER_YEAR];
    return values.map(value => ({label: value, value}));
  }

  // The delivered board pins its date filter to the 2025 business year.  The
  // grain button only changes which values are selectable: annual shows 2025,
  // monthly shows the twelve 2025 months.  Mutating the reactive delivered
  // metadata keeps the option list in sync without re-querying AP.
  function applyPeriodFilterOptions(payload, grain) {
    const components = payload?.dashboard?.components;
    if (!Array.isArray(components)) return;
    const filter = components.find(component => component?.type === 'composite-filter'
      && (component.dataConfig?.dimensions || []).some(dim => dim.identifierCode === PERIOD_FILTER_ID));
    const config = filter?.dataConfig;
    if (!config?.mockData) return;
    // Replace the mockData object instead of mutating it in place: the
    // delivered select reloads its options when the object identity changes.
    config.mockData = {...config.mockData, options: periodFilterOptions(grain)};
  }

  function formatAnalysisDuration(value) {
    const seconds = Math.round(Number(value) || 0);
    if (!(seconds > 0)) return '';
    const text = seconds < 60 ? `${seconds} 秒`
      : `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`;
    return ` · 耗时 ${text}`;
  }

  function scopePeriod(scope = currentUiScope) {
    if (!scope || scope === 'default') return defaultPeriod;
    let entries;
    try { entries = JSON.parse(scope); } catch (_) { return defaultPeriod; }
    if (!Array.isArray(entries)) return defaultPeriod;
    let grain = '', candidate = '';
    const visit = value => {
      if (typeof value === 'string' || typeof value === 'number') {
        const found = periodText(value);
        if (found) candidate = found;
        return;
      }
      if (Array.isArray(value)) { value.forEach(visit); return; }
      if (!value || typeof value !== 'object') return;
      for (const key of ['value', 'values', 'selected', 'selectedValues', 'range', 'conditionValues', 'label']) {
        if (key in value) visit(value[key]);
      }
      for (const child of Object.values(value)) if (child && typeof child === 'object') visit(child);
    };
    for (const change of entries) {
      if (!Array.isArray(change) || change.length !== 2) continue;
      const method = String(change[0] || '').split(':', 1)[0];
      let value = change[1];
      if (method === 'setButtonGrainSelection') {
        if (typeof value === 'string') {
          try { value = JSON.parse(value); } catch (_) { /* plain YEAR/MONTH */ }
        }
        if (value && typeof value === 'object') value = value.value || value.code || value.grain || '';
        if (typeof value === 'string') grain = value.trim().toUpperCase();
      } else if (method === 'setFilterConditions') {
        visit(value);
      }
    }
    if (candidate) return grain === 'YEAR' ? candidate.slice(0, 4) : candidate;
    if (grain === 'MONTH') return activePeriod;
    return defaultPeriod;
  }
  const PAGES = {
    overview: {title: '经营看板', tab: '经营看板'},
    operations: {title: '运营360整体分析', tab: '运营360整体分析'},
    analysis: {title: '穿透式问题分析', tab: '穿透式问题分析'},
  };
  const PAGE_ALIASES = {home: 'overview'};
  let currentPage = pageFromLocation();

  function showBootFailure(message) {
    document.getElementById('cockpit-boot')?.remove();
    const host = document.getElementById('app');
    if (!host) return;
    host.removeAttribute('v-cloak');
    host.replaceChildren();
    const main = document.createElement('main');
    main.className = 'cockpit-state error';
    main.setAttribute('aria-live', 'assertive');
    const text = document.createElement('p');
    text.textContent = message;
    const retry = document.createElement('button');
    retry.type = 'button';
    retry.className = 'cockpit-state__retry';
    retry.textContent = '重新加载';
    retry.addEventListener('click', () => location.reload());
    main.append(text, retry);
    host.append(main);
  }

  if (!window.Vue) {
    showBootFailure('Vue 资源加载失败，请重新加载页面。');
    return;
  }
  const ProUIBi = window.ProUIBi;
  const dashboard = ProUIBi?.ProBiDashboard;
  if (!dashboard || !ProUIBi.configureBi) {
    showBootFailure('ProUI 组件资源加载失败，请重新加载页面或检查静态资源。');
    return;
  }

  const {createApp, ref, computed, reactive, onMounted, onBeforeUnmount, onErrorCaptured, nextTick, shallowRef, markRaw, getCurrentInstance} = window.Vue;

  const dashboardDataMode = ref('ap');
  let liveDataClient = null;
  let publications = null;
  let defaultView = true;
  let filtersReady = false;
  let scopeNeedsAnalysis = false;
  // A filter callback without a recent user gesture is SDK initialization or
  // replay. It records the default scope but must not restart the board.
  let scopeActionUntil = 0;
  const SCOPE_CONTROL = '.pro-radio-button,.pro-bi-filter-chip,.pro-bi-composite-filter,.pro-date-filter,.pro-select-filter,.pro-button-group,.pro-bi-button-group,[class*="filter"]';
  const noteScopeAction = event => {
    if (event?.target?.closest?.(SCOPE_CONTROL)) scopeActionUntil = Date.now() + 2000;
  };
  const isScopeUserAction = () => Date.now() <= scopeActionUntil;
  const insightLoadError = ref('');
  let insightBundleReady;
  let fullSnapshot = null, pageCache = null, currentUiScope = 'default';
  const frozenAnnual = reactive({visible:true,running:false,period:defaultPeriod,basis:'',error:'',activeStage:'',pendingStages:[],completedStages:[],failedStages:[],stageProgress:{},progress:{}});
  function applyFrozenStatus(value) {
    const manual=value?.manualUpdate || (value?.status ? value : null);
    if(!frozenAnnualMode || !manual)return;
    frozenAnnual.running=manual.status==='running';
    frozenAnnual.stageProgress=manual.stageProgress||{};
    frozenAnnual.progress=manual.progress||{};
    for(const key of ['activeStage','pendingStages','completedStages','failedStages'])frozenAnnual[key]=manual[key]||(key==='activeStage'?'':[]);
    if(value.requestedPeriod)frozenAnnual.period=value.requestedPeriod;
    if(typeof value.basis==='string')frozenAnnual.basis=value.basis;
    frozenAnnual.error=manual.error||'';
    const failures=newStageFailures(manual,failureWatch);
    if(failures.length){
      failureDialog.items=[...failureDialog.items,...failures];
      failureDialog.open=true;
      nextTick(()=>document.getElementById('cockpit-failure-close')?.focus());
    }
  }
  // A stage that stops mid-analysis (for example the model call) is reported
  // once in a dialog; the card itself keeps the last published result.
  const failureWatch={runId:'',announced:new Set()};
  const failureDialog=reactive({open:false,items:[]});
  function closeFailureDialog(){failureDialog.open=false;failureDialog.items=[];}
  const visibleAiSlots = new Map();
  let priorityTimer=null;
  function frozenPriority(slotId) {
    const visibleSlots=[...visibleAiSlots.entries()].sort((a,b)=>a[1]-b[1]).map(([id])=>id);
    return {slotId:typeof slotId==='string'?slotId:undefined,page:currentPage,visibleSlots};
  }
  function queueFrozenPriority() {
    if(!frozenAnnualMode || !frozenAnnual.running)return;
    clearTimeout(priorityTimer);
    priorityTimer=setTimeout(()=>fetch(`${apiBase}/publications/priority`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(frozenPriority())}).catch(()=>{}),150);
  }
  async function refreshFrozenAnnual(slotId) {
    frozenAnnual.visible=true;
    frozenAnnual.error='';
    try {
      const response=await fetch(`${apiBase}/publications/refresh`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({manual:true,id:Number(identityId),...frozenPriority(slotId)})});
      if(!response.ok)throw new Error('后台更新未启动，继续展示发布版');
      const job=await response.json();
      applyFrozenStatus(job);
      aiPublicationClient?.poke(0,currentUiScope);
    } catch(error) {frozenAnnual.error=error.message;}
  }
  const pageState = reactive({cached:false,dataAsOf:0,analyzedAt:0,refreshing:false,updateStatus:'idle',displayStale:false,error:''});
  // Slot cards live outside the dashboard component lifecycle.  Tabs, node
  // switches and board remounts may change charts, but never clear this store.
  const aiPublicationStore = reactive({slots:{},expectedCount:15,readyCount:0,missingCount:0,
    updatingCount:0,version:'',scopeKey:'',requestedScope:'',displayScope:'',scopeMatch:true,status:'idle',error:'',riskCounts:{}});
  let aiPublicationClient=null, resolveAiPublicationReady=null;
  let aiPublicationBoot=null;
  let aiPublicationReady=new Promise(resolve=>{resolveAiPublicationReady=resolve;});
  const dashboardDescription = computed(() => {
    const parts = [];
    if (pageState.cached) parts.push('完整看板 · 数据时间 ' + new Date(pageState.dataAsOf * 1000).toLocaleString('zh-CN', {hour12:false}));
    if (pageState.analyzedAt) parts.push('分析更新于 ' + new Date(pageState.analyzedAt * 1000).toLocaleString('zh-CN', {hour12:false}));
    if (pageState.displayStale) parts.push('当前展示上次完整版本');
    if (pageState.refreshing) parts.push('正在后台更新');
    if (pageState.error) parts.push(pageState.cached ? '部分数据加载失败，继续展示上次完整内容' : '部分数据加载失败');
    return parts.join(' · ');
  });
  const visibleStages = new Map();
  let onPageActivity = () => {};

  /* Delivered slot positions, backed by live cockpit analyses instead of static copy. */
  const SLOT_STAGE = {
    'bid-status-note': 'bid',
    'quote-summary': 'quotation',
    'bid-summary': 'bid',
    'order-sign-summary': 'order',
    'star-product-order-list': 'order',
    'affected-order-list': 'order',
    'overdue-order-list': 'shipment',
    'sales-shipment-issues': 'combined',
    'opportunity-risk': 'opportunity',
    'opportunity-coverage-note': 'opportunity',
    'order-risk-summary': 'order',
    'shipment-risk-summary': 'shipment',
    'shipment-overdue-note': 'shipment',
    'shipment-cause-breakdown': 'shipment',
    'shipment-task-order': 'shipment',
  };
  const INDEPENDENT_SLOT_KEYS = new Set(['opportunity-risk']);
  function analysisDataStages(stage) {
    // The combined slot is derived from the three upstream nodes and has no
    // component query of its own.  Selecting only "combined" would discard
    // every successful opportunity/order/shipment query on an explicit
    // refresh and leave the card on an empty-state error.
    return stage === 'combined' ? ['opportunity', 'order', 'shipment'] : [stage];
  }
  const RISK_COUNT_TARGETS = [
    {componentId:'progress-y5dumxio', metric:'sales', tabId:'tab-bc6wp3k2', templateId:'2112001069107167233'},
    {componentId:'progress-91j3rt9a', metric:'shipment', tabId:'tab-bc6wp3k2', templateId:'2112001069107167233'},
    {componentId:'progress-ynh9zsng', metric:'sales', tabId:'tab-211tc4o0', templateId:'2112434004503347202'},
    {componentId:'progress-zl0egumz', metric:'shipment', tabId:'tab-211tc4o0', templateId:'2112434004503347202'},
  ];
  const RISK_COUNT_PATH = ['headerActions', 0, 'label'];
  let riskCountRuntime = null;
  const appliedRiskCountLabels = new Map();
  const riskMetricCounts = new Map();
  function validAiCard(item) {
    const result=item?.result;
    return result?.cardContract==='cockpit-cards-v1' && typeof result.summary==='string' &&
      result.summary.trim() && Array.isArray(result.causes) && Array.isArray(result.recommendations) &&
      Array.isArray(result.limitations);
  }
  function slotPublication(slotId) {
    return aiPublicationStore.slots[slotId] || null;
  }
  function applyRiskCounts(value) {
    const counts=value?.riskCounts||{};
    const next={...aiPublicationStore.riskCounts};
    for(const metric of ['sales','shipment']) {
      const item=counts[metric];
      const count=Number(item?.count);
      if(!Number.isFinite(count))continue;
      const current=value.scopeMatch!==false&&item.scopeMatch!==false;
      if(item.known===true&&current){
        riskMetricCounts.set(metric,count);
        next[metric]={...item,count};
      } else if(!riskMetricCounts.has(metric)&&item.complete===true){
        riskMetricCounts.set(metric,count);
        next[metric]={...item,count};
      } else if(riskMetricCounts.has(metric)){
        next[metric]={...(next[metric]||item),count:riskMetricCounts.get(metric)};
      }
    }
    aiPublicationStore.riskCounts=next;
  }
  function riskCountForMetric(metric) {
    return riskMetricCounts.has(metric) ? riskMetricCounts.get(metric) : null;
  }
  function syncRiskCountLabels(runtime) {
    if(!runtime?.updateComponentMeta)return;
    if(runtime!==riskCountRuntime) {
      riskCountRuntime=runtime;
      appliedRiskCountLabels.clear();
    }
    for(const target of RISK_COUNT_TARGETS) {
      const count=riskCountForMetric(target.metric);
      if(count===null)continue;
      const label=`${count}条风险`;
      if(appliedRiskCountLabels.get(target.componentId)===label)continue;
      const result=runtime.updateComponentMeta(target.componentId,RISK_COUNT_PATH,label,{
        embedPath:{segments:[{kind:'tab',containerId:'tab-container-zm9eyxne',
          tabId:target.tabId,templateId:target.templateId}]},
      });
      if(result?.ok!==false)appliedRiskCountLabels.set(target.componentId,label);
    }
  }
  function bindRiskCountRuntime(runtime) {
    riskCountRuntime=runtime||null;
    appliedRiskCountLabels.clear();
    if(riskCountRuntime)syncRiskCountLabels(riskCountRuntime);
  }
  function syncBoundRiskCountLabels() {
    if(riskCountRuntime)syncRiskCountLabels(riskCountRuntime);
  }
  function unbindRiskCountRuntime(runtime) {
    if(runtime&&riskCountRuntime!==runtime)return;
    riskCountRuntime=null;
    appliedRiskCountLabels.clear();
  }
  function hasPublishedSlot(slotId) {
    const slot=slotPublication(slotId);
    return analysisEngine==='main' && slot?.status==='ready' && validAiCard(slot.payload);
  }
  function applyServerCard(slotId, slot, {stale=false, notice=''}={}) {
    if(!slot || slot.status!=='ready' || !validAiCard(slot.payload))return;
    // Independent slots are read directly from their own publication entry.
    // Writing them into the shared stage state is what allowed a later shared
    // opportunity result to replace opportunity-risk by timestamp.
    if(INDEPENDENT_SLOT_KEYS.has(slotId))return;
    const stage=slot.stage || SLOT_STAGE[slotId];
    if(!stage)return;
    const state=stateFor(stage);
    // An explicit user analysis is authoritative until it settles.  A polled
    // card can replace an older successful card, but never interrupt work the
    // user just started.
    if(state.status==='running' && !state.item && !state.stale)return;
    if(!state.stale && state.item && Number(state.item.updatedAt||0)>Number(slot.payload.updatedAt||0))return;
    Object.assign(state,{item:slot.payload,status:'done',progress:'',cached:true,
      refreshing:Boolean(slot.update?.active),stale,error:'',scopeNotice:stale?notice:''});
  }
  function applyAiPublications(value, {preserve=true, notice=''}={}) {
    if(frozenAnnualMode)applyFrozenStatus(value);
    if(!value?.slots)return;
    // A slower read for the previous filter must never repaint the current
    // scope.  Keep the visible cards and let the newest request win.
    if(value.requestedScope && value.requestedScope!==currentUiScope){
      resolveAiPublicationReady?.();resolveAiPublicationReady=null;
      return;
    }
    const incoming=value.slots, previous=aiPublicationStore.slots, next={};
    const scopeMismatch=value.scopeMatch===false;
    const mismatchNotice='右上角筛选已切换，正在加载新口径；以下仍为上次默认口径分析';
    for(const [slotId,slot] of Object.entries(incoming)) {
      const prior=previous[slotId];
      if(slot.status==='ready') {
        const stale=scopeMismatch||slot.scopeMatch===false||value.requestedScope!==currentUiScope;
        const slotNotice=stale?(notice||mismatchNotice):'';
        next[slotId]={...slot,stale,scopeNotice:slotNotice};
        applyServerCard(slotId,slot,{stale,notice:slotNotice});
      } else if(preserve && prior?.status==='ready') {
        // Missing means "no usable card for this scope", not "clear the card".
        // Keep the last successful payload explicitly labelled as old scope.
        next[slotId]={...prior,refreshing:Boolean(slot.update?.active),stale:true,
          refreshStatus:slot.refreshStatus,lastRefreshError:slot.lastRefreshError,update:slot.update,
          scopeNotice:notice||'当前展示上次分析，后台正在更新'};
        applyServerCard(slotId,prior,{stale:true,notice:next[slotId].scopeNotice});
      } else {
        next[slotId]=slot;
      }
    }
    aiPublicationStore.slots=next;
    Object.assign(aiPublicationStore,{
      expectedCount:Number(value.expectedCount||Object.keys(incoming).length||15),
      readyCount:Number(value.readyCount||0),missingCount:Number(value.missingCount||0),
      updatingCount:Number(value.updatingCount||0),version:value.version||'',
      scopeKey:value.scopeKey||'',requestedScope:value.requestedScope||'',
      displayScope:value.displayScope||'',scopeMatch:value.scopeMatch!==false,
      status:value.update?.status||'idle',
      error:'',
    });
    applyRiskCounts(value);
    syncBoundRiskCountLabels();
    settleMissingSlotStages();
    resolveAiPublicationReady?.();resolveAiPublicationReady=null;
  }
  function markAiPublicationsStale(notice) {
    for(const [slotId,slot] of Object.entries(aiPublicationStore.slots)) {
      if(slot.status!=='ready')continue;
      aiPublicationStore.slots[slotId]={...slot,stale:true,refreshing:true,
        scopeNotice:notice||'筛选口径已切换，正在加载新数据；以下仍为上次分析'};
      applyServerCard(slotId,slot,{stale:true,notice:aiPublicationStore.slots[slotId].scopeNotice});
    }
  }
  function failureAiPublications(error) {
    aiPublicationStore.error=String(error?.message||error||'AI卡片读取失败');
    if(!Object.keys(aiPublicationStore.slots).length)aiPublicationStore.status='unavailable';
    resolveAiPublicationReady?.();resolveAiPublicationReady=null;
  }
  function startAiPublications() {
    if(analysisEngine!=='main'||aiPublicationClient)return Promise.resolve(aiPublicationClient);
    if(!aiPublicationBoot)aiPublicationBoot=import(`${assetBase}/ai-publication-client.js?v=${encodeURIComponent(assetVersion)}`)
      .then(({createAiPublicationClient})=>{
        if(analysisEngine!=='main')return null;
        aiPublicationClient=createAiPublicationClient({apiBase,id:identityId,
          onUpdate:(value,meta)=>applyAiPublications(value,{preserve:meta?.preserve!==false}),
          onError:failureAiPublications});
        aiPublicationClient.start('default');
        return aiPublicationClient;
      }).catch(error=>{failureAiPublications(error);aiPublicationBoot=null;return null;});
    return aiPublicationBoot;
  }
  function settleMissingSlotStages() {
    const readyStages=new Set();
    for(const slot of Object.values(aiPublicationStore.slots)) {
      if(slot?.status==='ready'&&validAiCard(slot.payload))readyStages.add(slot.stage||SLOT_STAGE[slot.slotId]);
    }
    for(const stage of new Set(Object.values(SLOT_STAGE))) {
      if(!stage||readyStages.has(stage))continue;
      const state=stateFor(stage);
      if(state.item||state.status==='running')continue;
      const active=Object.values(aiPublicationStore.slots).some(slot=>{
        const slotStage=slot?.stage||SLOT_STAGE[slot?.slotId];
        return slotStage===stage&&(slot?.update?.active||['running','checking','queued','waiting','retry_wait'].includes(String(slot?.refreshStatus||'')));
      });
      if(active) {
        Object.assign(state,{status:'running',progress:'已取得部分AP数据，正在分析；未返回的查询会在卡片中列明',refreshing:true,error:''});
      } else {
        Object.assign(state,{status:'error',progress:'',refreshing:false,error:'当前口径暂无可用的已取数证据，等待下一次数据更新'});
      }
    }
  }
  async function ensureSlotAnalysis(slotId, stage, refresh=false, urgent=false) {
    if(analysisEngine!=='main') return ensureAnalysis(stage,refresh,urgent);
    if(refresh && INDEPENDENT_SLOT_KEYS.has(slotId)) return refreshFrozenAnnual(slotId);
    if(refresh) return ensureAnalysis(stage,true,urgent);
    if(hasPublishedSlot(slotId)) return slotPublication(slotId).payload;
    // Opening, refreshing or scrolling a page only reads published cards; it
    // must not start a model job.  Give the independent publication read a
    // brief head start so an already-saved card wins the race.  Missing cards
    // are filled by the server preheat scheduler, while the explicit retry
    // action above remains available to the user.
    await Promise.race([aiPublicationReady,new Promise(resolve=>setTimeout(resolve,2500))]);
    if(hasPublishedSlot(slotId)) return slotPublication(slotId).payload;
    return null;
  }
  const QUERY_STAGE_CODES = {
    opportunity: ['YWLN_M0022','YWLN_M0023','YWLN_M0024','YWLN_M0038','YWLN_M0039','YWLN_M0140','YWLN_D015','YWLN_D020'],
    guidance: ['YWLN_M0028','YWLN_D017'],
    quotation: ['YWLN_M0031','YWLN_M0050','YWLN_M0051','YWLN_M0131','YWLN_M0137','YWLN_D021'],
    technical: ['YWLN_D018'],
    bid: ['YWLN_M0027','YWLN_M0030','YWLN_M0034','YWLN_M0047','YWLN_M0048','YWLN_M0168','YWLN_D022'],
    order: ['YWLN_M0032','YWLN_M0033','YWLN_M0142','YWLN_M0179','YWLN_M0194','YWLN_M0198','YWLN_D016','YWLN_D023'],
    shipment: ['YWLN_M0006','YWLN_M0007','YWLN_M0008','YWLN_M0010','YWLN_M0011','YWLN_M0012','YWLN_M0035','YWLN_M0036','YWLN_M0037','YWLN_D024'],
  };
  const QUERY_STAGE_LABELS = {
    opportunity: ['商机'], guidance: ['方案引导','方案'], quotation: ['报价'], technical: ['技术方案','技术'],
    bid: ['投标','中标','丢标','弃标'], order: ['订单接收','订单','签单','接收'],
    shipment: ['发货','出货','履约','超期未发'],
  };
  function queryStage(payload) {
    const text = canonical(payload);
    for (const [stage, codes] of Object.entries(QUERY_STAGE_CODES)) {
      if (codes.some(code => text.includes(code))) return stage;
    }
    for (const [stage, labels] of Object.entries(QUERY_STAGE_LABELS)) {
      if (labels.some(label => text.includes(label))) return stage;
    }
    return '';
  }
  function queryPriority(kind, payload) {
    const stage = queryStage(payload);
    const visible = Boolean(stage && stageViewport.get(stage)?.visibleCount);
    const encoded = JSON.stringify(payload || {});
    const config = payload?.analysisConfig || {};
    const indicators = Array.isArray(config.indicators) ? config.indicators.length : 0;
    const dimensions = Array.isArray(config.dimensions) ? config.dimensions.length : 0;
    const heavy = kind === 'batch' || encoded.length > 12000 || indicators > 8 || dimensions > 5;
    return {stage, visible, heavy, rank: visible ? 0 : 1};
  }
  const STAGE_NAMES = {
    opportunity: '商机获取',
    guidance: '方案引导',
    quotation: '报价',
    technical: '技术方案',
    bid: '投标',
    order: '订单接收',
    shipment: '发货',
    combined: '销售额与出货量共同分析',
  };
  const PREFETCH_STAGES = [...new Set(Object.values(SLOT_STAGE))];
  const insightState = reactive({});
  const analysisPromises = new Map();
  const clarificationAnswers = new Map();
  const MAX_CONCURRENT = 3;
  const analysisQueue = [];
  const stageViewport = new Map();
  let runningAnalyses = 0;
  let jobSequence = 0;

  /* What the user is looking at runs first. A stage only becomes "visible"
   * after IntersectionObserver says so, not when Vue merely mounts it. Running
   * jobs are never pre-empted; only the waiting order changes. */
  function jobRank(job) {
    if (job.urgent) return 0;
    const view = stageViewport.get(job.stage);
    return view && view.visibleCount > 0 ? 1 : 2;
  }
  function jobOrder(job) {
    const view = stageViewport.get(job.stage);
    return view && Number.isFinite(view.order) ? view.order : Number.MAX_SAFE_INTEGER;
  }
  function compareJobs(left, right) {
    const rank = jobRank(left) - jobRank(right);
    if (rank) return rank;
    if (jobRank(left) === 1) {
      const order = jobOrder(left) - jobOrder(right);
      if (order) return order;
    }
    return left.sequence - right.sequence;
  }
  function slotLimit() { return analysisEngine === 'main' ? 1 : MAX_CONCURRENT; }

  function pumpAnalysisQueue() {
    while (runningAnalyses < slotLimit() && analysisQueue.length) {
      analysisQueue.sort(compareJobs);
      const job = analysisQueue.shift();
      runningAnalyses += 1;
      job.run().then(job.resolve, job.reject).finally(() => {
        runningAnalyses -= 1;
        pumpAnalysisQueue();
      });
    }
  }

  function reprioritiseAnalyses() {
    if (analysisQueue.length && runningAnalyses < slotLimit()) pumpAnalysisQueue();
  }

  function withAnalysisSlot(run, options = {}) {
    const {stage = '', urgent = false} = typeof options === 'string' ? {stage: options} : (options || {});
    if (urgent && stage) {
      // A retry must jump an already-queued (not yet started) job for the same
      // stage instead of leaving a stale low-priority entry ahead of it.
      const queued = analysisQueue.find(job => job.stage === stage);
      if (queued) queued.urgent = true;
    }
    return new Promise((resolve, reject) => {
      analysisQueue.push({run, resolve, reject, stage, urgent, sequence: jobSequence++});
      pumpAnalysisQueue();
    });
  }

  function noteStageVisibility(stage, visible, order) {
    const view = stageViewport.get(stage) || {visibleCount: 0, order: Number.MAX_SAFE_INTEGER};
    view.visibleCount = Math.max(0, (view.visibleCount || 0) + (visible ? 1 : -1));
    if (visible) view.order = Math.min(view.order, order);
    stageViewport.set(stage, view);
    reprioritiseAnalyses();
  }

  function stateFor(stage) {
    if (!insightState[stage]) insightState[stage] = {status: 'idle', progress: '', item: null, error: '', stale: false, scopeNotice: ''};
    return insightState[stage];
  }

  function publicProgress(message) {
    if (!message) return '正在更新分析';
    // Routing, evidence assembly and delivery checks are server internals; the
    // AI slot only needs a stable user-facing state.
    return /主服务|路由|取证|交付校验|质量闸门/.test(String(message)) ? '正在更新分析' : String(message);
  }

  async function responseError(response) {
    try {
      const body = await response.json();
      if (body?.detail) return typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
    } catch (_) { /* non-JSON error body */ }
    return `${response.status} ${response.statusText}`;
  }

  function checkedAnalysis(item, stage) {
    const context=item.context || {};
    if (analysisEngine === 'main') {
      const current = liveDataClient ? liveDataClient.scope({partial:true, stages:analysisDataStages(stage)}) : {chartQueries: [...displayedQueries].sort(), apReceiptIds: []};
      if (dashboardQueryError || canonical(context.chartQueries||[])!==canonical(current.chartQueries) || canonical(context.apReceiptIds||[])!==canonical(current.apReceiptIds)) throw new Error(dashboardQueryError || '看板查询范围已变化，请重新分析');
    }
    if(context.engine!==analysisEngine || context.id!==Number(identityId) || context.stage!==stage ||
       context.period!==(baselineItem?.context.period||scopePeriod()) || context.department!==(baselineItem?.context.department||DEPARTMENT) ||
       canonical(context.filters||{})!==canonical(baselineItem?.context.filters||{})) {
      throw new Error('分析结果与当前引擎或范围不一致，拒绝回填');
    }
    return item;
  }

  async function startAnalysis(stage, refresh) {
    const state = stateFor(stage);
    if(baselineItem && baselineItem.context.stage!==stage)throw new Error('当前对照基线属于'+STAGE_NAMES[baselineItem.context.stage]+'，请切换至该节点');
    state.status = 'running';
    state.item = null;
    state.progress = '正在加载分析数据';
    let dataScope = {chartQueries: [], apReceiptIds: []};
    if (analysisEngine === 'main' && liveDataClient) {
      dataScope = await liveDataClient.ready({partial:true, stages:analysisDataStages(stage)});
    } else if (analysisEngine === 'main') {
      let previous = -1, stable = 0;
      for (let attempt = 0; attempt < 20 && stable < 3; attempt++) {
        await new Promise(resolve => setTimeout(resolve, 100));
        stable = displayedQueries.size && previous === displayedQueries.size ? stable + 1 : 0;
        previous = displayedQueries.size;
      }
      if (dashboardQueryError) throw new Error(dashboardQueryError);
      if (!displayedQueries.size) throw new Error('当前看板尚无成功展示的 AP 查询，不能开始分析');
      dataScope.chartQueries = [...displayedQueries].sort();
    }
    state.progress = '正在更新分析';
    state.error = '';
    const body = JSON.stringify({
      id: Number(identityId),
      engine: analysisEngine,
      clarifications: clarificationAnswers.get(stage) || {},
      chartSnapshotId: 'pdt-release-2109836674373566465',
      chartQueries: dataScope.chartQueries,
      apReceiptIds: dataScope.apReceiptIds,
      unavailableQueries: (dataScope.unavailable || []).map(entry => entry.query),
      period: baselineItem?.context.period || scopePeriod(),
      department: baselineItem?.context.department || DEPARTMENT,
      filters: baselineItem?.context.filters || {},
      repositoryId: baselineItem?.context.repositoryId || '',
      baselineAnalysisId: baselineId,
      stage,
      source: analysisEngine === 'main' || baselineId ? 'service' : 'prototype',
      refresh: Boolean(refresh),
    });
    let response;
    const queueDeadline = Date.now() + 240000;
    for (let attempt = 0; ; attempt += 1) {
      response = await fetch(`${apiBase}/analyses`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
        body,
      });
      if (response.status !== 429) break;
      // A full execution pool means "queued", never "failed": keep the card
      // loading and retry until a slot frees.
      state.progress = '排队中，等待分析资源';
      if (Date.now() > queueDeadline) throw new Error('分析排队时间较长，请稍后重试');
      await new Promise(resolve => setTimeout(resolve, Math.min(1000 * (attempt + 1), 5000)));
    }
    if (!response?.ok) throw new Error(response ? await responseError(response) : '分析请求失败');
    let item = checkedAnalysis(await response.json(), stage);
    state.item = item;
    state.progress = publicProgress(item.progress || '正在更新分析');
    const deadline = Date.now() + 240000;
    while (item.status === 'queued' || item.status === 'running') {
      if (Date.now() > deadline) throw new Error('模型分析超时，请重试');
      await new Promise(resolve => setTimeout(resolve, 1500));
      const poll = await fetch(`${apiBase}/analyses/${encodeURIComponent(item.id)}`, {headers: {'Accept': 'application/json'}});
      if (!poll.ok) throw new Error(await responseError(poll));
      item = checkedAnalysis(await poll.json(), stage);
      state.item = item;
      state.progress = publicProgress(item.progress || '正在更新分析');
    }
    if (!['completed', 'limited', 'needs_input'].includes(item.status)) throw new Error(item.progress || '分析未完成');
    state.status = 'done';
    state.item = item;
    state.progress = '';
    return item;
  }

  function ensureAnalysis(stage, refresh = false, urgent = false) {
    const state = stateFor(stage);
    if(frozenAnnualMode) return refresh ? refreshFrozenAnnual() : Promise.resolve(state.item);
    if (analysisEngine === 'main' && !refresh && !state.stale && state.status === 'done' && state.item) {
      return Promise.resolve(state.item);
    }
    if (analysisEngine === 'main' && fullSnapshot && !state.stale && state.item) {
      if (refresh) return pageCache.refresh(fullSnapshot,true);
      return Promise.resolve(state.item);
    }
    if (analysisEngine === 'main' && publications) return publications.refresh(stage, refresh, urgent).finally(onPageActivity);
    if (!refresh && state.status === 'done' && state.item) {
      try { return Promise.resolve(checkedAnalysis(state.item, stage)); } catch (_) { analysisPromises.delete(stage); }
    }
    if (!refresh && analysisPromises.has(stage)) return analysisPromises.get(stage);
    const promise = withAnalysisSlot(() => startAnalysis(stage, refresh), {stage, urgent}).catch(cause => {
      state.status = 'error';
      state.error = cause.message || '模型分析失败';
      analysisPromises.delete(stage);
      throw cause;
    });
    analysisPromises.set(stage, promise);
    return promise;
  }

  function prefetchAnalyses() {
    // Warm every stage used by a delivered slot while the page is idle.
    PREFETCH_STAGES.forEach(stage => ensureAnalysis(stage).catch(() => {}));
  }

  function schedulePrefetch() {
    if (analysisEngine === 'main' || baselineId) return; // Compare on demand; do not warm five full main-service tasks.
    if (typeof window.requestIdleCallback === 'function') {
      window.requestIdleCallback(prefetchAnalyses, {timeout: 1500});
    } else {
      setTimeout(prefetchAnalyses, 800);
    }
  }

  function baseMainBody(stage,refresh) {
    return {id:Number(identityId),engine:'main',source:'service',page:currentPage,defaultView:currentUiScope==='default' && !clarificationAnswers.has(stage),
      stage,period:scopePeriod(),department:DEPARTMENT,filters:{},repositoryId:'',chartSnapshotId:'pdt-release-2109836674373566465',
      clarifications:clarificationAnswers.get(stage)||{},refresh:Boolean(refresh)};
  }
  async function mainBody(stage,refresh) {
    let dataScope;
    if(liveDataClient) dataScope=await liveDataClient.ready({partial:true,stages:analysisDataStages(stage)});
    else {for(let n=0;n<20 && !displayedQueries.size;n++) await new Promise(r=>setTimeout(r,100));if(dashboardQueryError)throw new Error(dashboardQueryError);dataScope={chartQueries:[...displayedQueries].sort(),apReceiptIds:[]};}
    const {unavailable=[],...usableScope}=dataScope;
    return {...baseMainBody(stage,refresh),...usableScope,unavailableQueries:unavailable.map(entry=>entry.query)};
  }

  const CockpitInsight = {
    props: {
      insight: {type: Object, required: true},
      page: {type: String, default: 'overview'},
      slotProps: {type: Object, default: () => ({})},
    },
    setup(props) {
      const stage = computed(() => SLOT_STAGE[props.insight.id] || 'shipment');
      const state = computed(() => stateFor(stage.value));
      const delivered = shallowRef(null);
      const componentError = ref('');
      const insightSlotProps = computed(() => ({
        ...props.slotProps,
        apiBase,
        identityId: Number(identityId),
        page: props.page,
        stage: stage.value,
        uiScope: currentUiScope,
        period: scopePeriod(),
        riskCounts: aiPublicationStore.riskCounts,
        frozenControls: frozenAnnualMode ? {state:frozenAnnual, refresh:refreshFrozenAnnual} : null,
      }));
      const analysisContext = computed(() => ({
        id: Number(identityId),
        stage: stage.value,
        stageName: STAGE_NAMES[stage.value] || stage.value,
        period: analysisEngine === 'main' ? '' : baselineItem?.context.period || scopePeriod(),
        department: analysisEngine === 'main' ? '' : baselineItem?.context.department || DEPARTMENT,
      }));
      const compareLink = computed(()=>{if(!state.value.item)return '';const url=new URL(location.href);url.searchParams.set('engine','standalone');url.searchParams.set('baseline',state.value.item.id);return url.pathname+url.search;});
      // Each slot answers its own question.  Prefer the slot-projected
      // publication over the shared stage card when it is at least as new.
      const slotAnalysis = computed(()=>selectSlotAnalysis({
        slotId:props.insight.id,
        independent:INDEPENDENT_SLOT_KEYS.has(props.insight.id),
        published:slotPublication(props.insight.id),
        current:state.value.item,
        validPayload:validAiCard,
      }));
      const progressClock=ref(Date.now());
      const progressTimer=setInterval(()=>{if(frozenAnnual.running)progressClock.value=Date.now();},1000);
      onBeforeUnmount(()=>clearInterval(progressTimer));
      // Independent cards own their queue entry. Older published payloads may
      // still say publicationKey=opportunity; that must never redirect this
      // card's progress to the shared opportunity stage.
      const publicationKey=computed(()=>INDEPENDENT_SLOT_KEYS.has(props.insight.id)
        ? props.insight.id
        : slotPublication(props.insight.id)?.publicationKey||stage.value);
      const cardUpdating=computed(()=>frozenAnnual.running && frozenAnnual.activeStage===publicationKey.value);
      const cardRefreshStatus=computed(()=>taskProgressText(frozenAnnual,publicationKey.value,progressClock.value));
      const cardMetadata = computed(()=>{
        const item=slotAnalysis.value, name=STAGE_NAMES[stage.value]||stage.value;
        if(!item?.result)return `${frozenAnnual.period} 年度分析 · ${name}`;
        const count=slotPublication(props.insight.id)?.evidenceCount||0;
        const stamp=Number(item.updatedAt||0);
        const stampText=stamp?` · ${new Date(stamp*1000).toLocaleString('zh-CN',{hour12:false})}`:'';
        const durationText=formatAnalysisDuration(item.execution?.durationSeconds);
        return `上次分析 · ${name} · 当前筛选范围 · ${count} 条证据${stampText}${durationText}`;
      });
      const refreshCard=()=>refreshFrozenAnnual(props.insight.id);
      const clarification = ref('');
      const confirmScope = () => {if(!clarification.value.trim())return;clarificationAnswers.set(stage.value, {answer:clarification.value.trim()});ensureSlotAnalysis(props.insight.id,stage.value,true,true).catch(()=>{});};
      const stop = async () => {if(state.value.item?.id)await fetch(`${apiBase}/analyses/${state.value.item.id}/cancel`,{method:'POST'});};
      const reload = () => ensureSlotAnalysis(props.insight.id, stage.value, true, true).catch(() => {});
      let alive=true;
      const registeredStage=stage.value;
      const instance=getCurrentInstance();
      let seenVisible=false, observer=null;
      const slotTop=()=>{
        const el=instance?.proxy?.$el;
        if(el&&el.nodeType===1&&typeof el.getBoundingClientRect==='function')return el.getBoundingClientRect().top+window.scrollY;
        return Number.MAX_SAFE_INTEGER;
      };
      const markVisible=(next,order)=>{
        if(next===seenVisible){
          if(next){const view=stageViewport.get(registeredStage);if(view&&order<view.order)view.order=order;}
          return;
        }
        seenVisible=next;
        noteStageVisibility(registeredStage,next,order);
        if(next)visibleAiSlots.set(props.insight.id,order);else visibleAiSlots.delete(props.insight.id);
        queueFrozenPriority();
        if(next)ensureSlotAnalysis(props.insight.id,registeredStage).catch(()=>{});
      };
      const registerSlot=()=>{
        const top=slotTop();
        const view=stageViewport.get(registeredStage)||{visibleCount:0,order:top};
        view.order=Math.min(view.order,top);
        stageViewport.set(registeredStage,view);
        const el=instance?.proxy?.$el;
        if(typeof IntersectionObserver!=='function'||!el||el.nodeType!==1){markVisible(true,top);return;}
        observer=new IntersectionObserver(entries=>{
          for(const entry of entries)markVisible(entry.isIntersecting,entry.boundingClientRect.top+window.scrollY);
        },{rootMargin:'240px 0px'});
        observer.observe(el);
      };
      visibleStages.set(registeredStage,(visibleStages.get(registeredStage)||0)+1);
      onErrorCaptured((cause, _instance, info) => {
        // A broken delivered component must terminate its own loading state.
        // Leaving the shallow child mounted made the slot look like a model
        // job that never finished.
        componentError.value = `AI 卡片渲染失败：${cause?.message || cause || info || '未知异常'}`;
        delivered.value = null;
        return false;
      });
      onBeforeUnmount(()=>{
        alive=false;
        visibleAiSlots.delete(props.insight.id);
        if(observer)observer.disconnect();
        if(seenVisible)noteStageVisibility(registeredStage,false,0);
        const count=(visibleStages.get(registeredStage)||1)-1;if(count)visibleStages.set(registeredStage,count);else visibleStages.delete(registeredStage);
      });
      onMounted(async()=>{
        try {
          const bundle=await (insightBundleReady ||= import(insightBundleUrl));
          const component=await bundle.loadInsight(props.insight.id);
          if(!alive)return;
          delivered.value=markRaw(component);
          await nextTick();registerSlot();
          // Give the observer one frame to report the real viewport before the
          // queue commits to an order; off-screen cards stay at low priority.
          await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
          await ensureSlotAnalysis(props.insight.id,stage.value);onPageActivity();
        } catch(cause) {if(alive)insightLoadError.value=`插槽加载失败：${cause.message||cause}`;}
      });
      return {frozenAnnualMode,frozenAnnual,stage,cardMetadata,refreshCard,cardRefreshStatus,cardUpdating,dashboardDataMode, delivered, state, slotAnalysis, analysisContext, insightSlotProps, reload, insightLoadError, componentError, analysisEngine, clarification, confirmScope, stop, compareLink, baselineId};
    },
    template: `
      <div v-if="delivered" class="cockpit-insight-slot" :class="{'cockpit-insight-slot--fixed':frozenAnnualMode}">
        <div v-if="frozenAnnualMode" class="cockpit-card-metadata" role="status">
          <span>{{cardMetadata}}</span>
          <button class="cockpit-frozen-release__action" type="button" :disabled="cardUpdating" @click="refreshCard">{{slotAnalysis?.result ? '重新分析' : '分析'}}</button>
          <span v-if="cardRefreshStatus" class="cockpit-card-metadata__status">{{cardRefreshStatus}}</span>
        </div>
        <div v-if="state.scopeNotice" class="insight-scope-notice" role="status">{{ state.scopeNotice }}</div>
        <component :is="delivered"
                   :analysis="slotAnalysis" :status="state.status" :progress="state.progress"
                   :cached="state.cached" :refreshing="state.refreshing"
                   :stale="Boolean(state.stale)" :scope-notice="state.scopeNotice || ''"
                   :error="state.error" :context="analysisContext" :slot-props="insightSlotProps"
                   v-if="!frozenAnnualMode || Boolean(slotAnalysis?.result)" @retry="reload"></component>
      </div>
      <div v-else-if="insightLoadError || componentError" class="insight-runtime-empty" role="status">{{ insightLoadError || componentError }}</div>
      <div v-else class="insight-runtime-empty" role="status" aria-label="插槽组件加载中"></div>
    `,
  };

  function canonical(value) {
    if (value === undefined) return 'null';
    if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
    if (value && typeof value === 'object') {
      return `{${Object.keys(value).filter(key => value[key] !== undefined).sort().map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`;
    }
    return JSON.stringify(value);
  }

  const displayedQueries = new Set();
  let dashboardQueryError = '';
  function failDashboardQuery(message) {
    dashboardQueryError = message + '；请恢复看板数据后刷新页面';
    if (analysisEngine === 'main') Object.values(insightState).forEach(state => { state.item = null; state.status = 'error'; state.error = dashboardQueryError; });
    throw new Error(message);
  }

  function installSnapshots(snapshots) {
    const analysis = new Map(Object.entries(snapshots.analysis || {}));
    const requests = new Map(Object.entries(snapshots.requests || {}));
    const utils = {
      request: async request => {
        const url = new URL(request.url, location.origin);
        const params = request.params || Object.fromEntries(url.searchParams);
        const key = canonical({
          method: (request.method || 'get').toLowerCase(),
          path: url.pathname,
          params,
        });
        const gatewayKey = canonical({
          method: (request.method || 'get').toLowerCase(),
          path: `/api/gateway2${url.pathname}`,
          params,
        });
        // The sales-caliper capture has both a four-node and a three-node response.
        // Use the delivered three-node version for the analysis flow.
        const hit = params.flowCode === 'SALES_CALIBER'
          ? requests.get(gatewayKey) || requests.get(key)
          : requests.get(key) || requests.get(gatewayKey);
        if (!hit) return [new Error('未找到该接口的发布快照'), null];
        return [null, {data: hit.response.data, success: true}];
      },
    };
    const biAdapters = {
      postAnalysisDataQuery: async payload => {
        const hit = analysis.get(canonical(payload));
        if (hit && hit.success === false) failDashboardQuery(hit.msg || hit.message || 'AP 查询失败');
        if (!hit?.data) failDashboardQuery('未找到该 AP 查询的发布快照');
        displayedQueries.add(canonical(payload));
        return hit.data;
      },
    };
    ProUIBi.configureBi({...biAdapters, utils});
    return {biAdapters, utils};
  }

  function pageFromLocation() {
    const match = location.pathname.match(/\/cockpit\/(home|overview|operations|analysis)\/?$/);
    if (match) {
      const page = PAGE_ALIASES[match[1]] || match[1];
      if (PAGES[page]) return page;
    }
    const declared = document.querySelector('meta[name="cockpit-page"]')?.content;
    const page = PAGE_ALIASES[declared] || declared;
    return PAGES[page] ? page : 'overview';
  }

  function routeFor(page, extra = {}) {
    const search = new URLSearchParams({id: identityId, engine: analysisEngine});
    if(baselineId)search.set('baseline',baselineId);
    for (const [key, value] of Object.entries(extra || {})) {
      if (value !== undefined && value !== null && String(value).trim()) search.set(key, String(value).trim());
    }
    return `${routeRoot}/cockpit/${page}?${search}`;
  }

  const CockpitLoading = {
    props: {label: {type: String, default: '正在加载经营看板'}},
    template: `
      <div class="cockpit-loading" role="status" aria-busy="true" :aria-label="label">
        <span class="visually-hidden">{{ label }}</span>
        <div class="cockpit-loading__head">
          <span class="cockpit-loading__line cockpit-loading__line--title"></span>
          <span class="cockpit-loading__line cockpit-loading__line--subtitle"></span>
        </div>
        <div class="cockpit-loading__kpis">
          <div v-for="n in 4" :key="'kpi-'+n" class="cockpit-loading__card cockpit-loading__card--kpi"><span class="cockpit-loading__line"></span><span class="cockpit-loading__line cockpit-loading__line--value"></span></div>
        </div>
        <div class="cockpit-loading__panels">
          <div v-for="n in 2" :key="'chart-'+n" class="cockpit-loading__card cockpit-loading__card--chart"><span class="cockpit-loading__line cockpit-loading__line--panel"></span><span class="cockpit-loading__chart"></span></div>
        </div>
        <div class="cockpit-loading__card cockpit-loading__card--wide"><span class="cockpit-loading__line cockpit-loading__line--panel"></span><span class="cockpit-loading__chart cockpit-loading__chart--wide"></span></div>
      </div>`,
  };

  const app = createApp({
    setup() {
      const page = ref(currentPage);
      let switchPageImpl = null;
      function stagesForPage(target) {
        const insights = runtime.value?.pages?.[target]?.insights || [];
        return [...new Set(insights.map(item => SLOT_STAGE[item.id]).filter(Boolean))];
      }
      function framePage(target, {push = true} = {}) {
        if (!runtime.value || !PAGES[target] || target === page.value) return false;
        const payload = runtime.value;
        currentPage = target;
        page.value = target;
        document.title = `储能经营风险驾驶舱 · ${PAGES[target].title}`;
        const tabs = payload.dashboard?.components?.find(c => c.type === 'tab-container');
        if (tabs) biRuntime.value?.setActiveTab?.(tabs.id, payload.pages[target].tabId);
        if (push) history.pushState({cockpitPage: target}, '', routeFor(target));
        return true;
      }
      function goPage(target, options = {}) {
        if (!framePage(target, options)) return Promise.resolve(false);
        return switchPageImpl ? switchPageImpl(target) : Promise.resolve(true);
      }
      const runtime = ref(null);
      const loading = ref(true);
      const error = ref('');
      const boardRevision=ref(0);
      let publishTimer=null, refreshTimer=null, pageEpoch=0, publishing=false, statusPoller=null, cardsVersion='';
      let installedSnapshotKey='', lastScopeRequestKey='', lastScopeRequestAt=0;
      const biAdapters = ref(null);
      const biRuntime = ref(null);
      const hostUtils = ref(null);
      const liveError = ref('');
      let liveErrorClear = null;
      let liveErrorSweep = null;
      let liveErrorSince = 0;
      const liveFailures = new Set();
      const pageTitle = computed(() => PAGES[page.value]?.title || PAGES.overview.title);
      const release = computed(() => runtime.value?.dashboard || null);
      // The legacy shipment task card is a hidden 15-slot compatibility entry.
      // Its user-facing action now lives in shipment-risk-summary, so rendering
      // the compatibility slot would create a second, empty insight card.
      const pageInsights = computed(() => (runtime.value?.pages?.[page.value]?.insights || [])
        .filter(item => item.id !== 'shipment-task-order'));

      let pendingActivationPage = '';
      let pendingActivationNode = '';
      let activationTimer = null;
      function pageForTab(tabId) {
        return Object.entries(runtime.value?.pages || {}).find(([, spec]) => spec.tabId === tabId)?.[0] || '';
      }
      function activationRuleForNode(node) {
        for (const rule of runtime.value?.activateRules || []) {
          const action = (rule.actions || []).find(item => item.type === 'selectHelmet' && String(item.nodeId) === String(node));
          if (action) return {componentId: action.componentId, selection: {nodeId: action.nodeId}, path: action.embedPath || []};
        }
        return null;
      }
      function helmetPathArg(path) {
        if (Array.isArray(path)) return {segments: path};
        return path && typeof path === 'object' ? path : {segments: []};
      }
      function queueActivationNavigation(containerId, tabId) {
        const target = pageForTab(tabId);
        if (!target || target === page.value) return;
        pendingActivationPage = target;
        pendingActivationNode = '';
        clearTimeout(activationTimer);
        // A delivered activate rule fires switchTab and selectHelmet in the same
        // turn. Wait briefly so the target URL carries the node that was chosen.
        activationTimer = setTimeout(() => {
          if (pendingActivationPage !== target) return;
          const node = pendingActivationNode;
          pendingActivationPage = '';
          pendingActivationNode = '';
          // Switching tabs is a component-internal move: the board instance,
          // its loaded data and every saved AI card stay in memory.
          goPage(target, {push: false}).then(() => {
            if (!node) return;
            history.replaceState(null, '', routeFor(page.value, {node}));
            applyPendingHelmet();
          }).catch(() => {});
        }, 120);
      }
      let pendingHelmet = null;
      function applyPendingHelmet() {
        const pending = pendingHelmet;
        if (!pending) return;
        const apply = attempt => {
          if (!biRuntime.value || !document.querySelector('.mini-cp-helmet__graph canvas')) {
            if (attempt < 50) setTimeout(() => apply(attempt + 1), 100);
            return;
          }
          requestAnimationFrame(() => requestAnimationFrame(() => {
            biRuntime.value?.setHelmetGraphSelection?.(
              pending.componentId, pending.selection, helmetPathArg(pending.path));
          }));
        };
        apply(0);
      }
      function rememberActivationHelmet(componentId, selection, path) {
        const node = String(selection?.nodeId || selection?.id || '').trim();
        pendingHelmet = {componentId, selection, path};
        if (node) pendingActivationNode = node;
        if (!pendingActivationPage) return;
        try {
          sessionStorage.setItem('cockpit.pendingActivation', JSON.stringify({
            id: identityId, page: pendingActivationPage, node, componentId, selection, path,
            expiresAt: Date.now() + 30000,
          }));
        } catch (_) { /* storage can be disabled by the embedding host */ }
      }
      function applyPendingActivation() {
        let pending = null;
        try { pending = JSON.parse(sessionStorage.getItem('cockpit.pendingActivation') || 'null'); } catch (_) {}
        try { sessionStorage.removeItem('cockpit.pendingActivation'); } catch (_) {}
        if (pending && (pending.id !== identityId || pending.page !== page.value || pending.expiresAt < Date.now())) pending = null;
        const routeNode = params.get('node') || '';
        if (!pending && routeNode) pending = activationRuleForNode(routeNode);
        if (!pending) return;
        const node = String(pending.node || pending.selection?.nodeId || routeNode || '');
        if (node) history.replaceState(null, '', routeFor(page.value, {node}));
        // Selecting the helmet before ProUI has mounted its Graph leaves the SDK
        // fitView callback attached to a destroyed instance on the first remount.
        const apply = attempt => {
          if (!biRuntime.value || !document.querySelector('.mini-cp-helmet__graph canvas')) {
            if (attempt < 50) setTimeout(() => apply(attempt + 1), 100);
            return;
          }
          requestAnimationFrame(() => requestAnimationFrame(() => {
            biRuntime.value?.setHelmetGraphSelection?.(
              pending.componentId, pending.selection, helmetPathArg(pending.path));
          }));
        };
        apply(0);
      }

      function findTab(label) {
        return [...document.querySelectorAll('.pro-bi-tab-container__tab')]
          .find(element => element.textContent.trim() === label);
      }

      function onTabClick(event) {
        const button=event.target.closest?.('.pro-bi-tab-container__tab');
        if(!button)return;
        const entry=Object.entries(PAGES).find(([,value])=>value.tab===button.textContent.trim());
        if(!entry||entry[0]===page.value)return;
        event.preventDefault();event.stopPropagation();
        goPage(entry[0]).catch(()=>{});
      }

      function onPopState() {
        const target = pageFromLocation();
        if (target !== page.value) goPage(target, {push: false}).catch(() => {});
      }

      function onVisibilityChange() {
        // Resume immediately when the tab becomes visible again instead of
        // waiting out the hidden-tab interval.
        if (!document.hidden) {statusPoller?.poke(0);aiPublicationClient?.poke(0,currentUiScope);}
      }

      function clearHelmetAnnotations() {
        document.querySelectorAll('.cockpit-helmet-error').forEach(node => node.remove());
      }
      function annotateFailedHelmet(message) {
        const roots = [...document.querySelectorAll('.mini-cp-helmet')];
        if (!roots.length) return;
        for (const root of roots) {
          if (!root.querySelector('.cockpit-helmet-error')) {
            const banner = document.createElement('div');
            banner.className = 'cockpit-helmet-error';
            banner.role = 'alert';
            banner.textContent = '指标加载失败，节点数值不可用' + (message ? '：' + message : '');
            root.prepend(banner);
          }
          // A failed node must never look like a real 0.00 total.
          root.querySelectorAll('*').forEach(element => {
            if (element.children.length) return;
            const text = element.textContent || '';
            if (/0\.00/.test(text) && /金额|天|率|电量|总/.test(text)) {
              element.textContent = text.replace(/0\.00/g, '—');
            }
          });
        }
      }
      function failedMetricLabels() {
        const match = liveError.value.match(/^部分指标加载失败：(?:指标 ([^：]+)：)?/);
        return match && match[1] ? match[1].split('、').filter(Boolean) : [];
      }
      function scrubFailedMetrics() {
        const labels = failedMetricLabels();
        if (!labels.length) return;
        document.querySelectorAll('.cockpit-board *').forEach(element => {
          if (element.children.length) return;
          let text = element.textContent || '';
          let changed = false;
          for (const label of labels) {
            const index = text.indexOf(label);
            if (index < 0) continue;
            const after = text.slice(index + label.length);
            const value = after.match(/^(\s*)(-?[\d,]+(?:\.\d+)?\s*(?:%|GWh|亿元|天|单)?)/);
            if (value) {
              text = text.slice(0, index + label.length) + value[1] + '—' + after.slice(value[0].length);
              changed = true;
            }
          }
          if (changed) {
            element.textContent = text;
            element.title = liveError.value;
          }
        });
      }
      function scrubUnavailableComponent(loader) {
        const owner = loader.closest('.pro-bi-comp-wrap');
        if (!owner) return;
        const loaderText = loader.querySelector('.pro-bi-chart-loading__text');
        if (loaderText && /^(loading|加载中)$/i.test((loaderText.textContent || '').trim())) {
          loaderText.textContent = '加载失败';
          loaderText.title = liveError.value;
        }
        const value = owner.querySelector('.pro-bi-kpi-card__value-row');
        if (value) value.textContent = '—';
        const current = owner.querySelector('.pro-bi-progress-card__current');
        if (current) current.textContent = '—';
        const rate = owner.querySelector('.pro-bi-progress-card__rate');
        if (rate) rate.textContent = '—';
        const target = owner.querySelector('.pro-bi-progress-card__target');
        if (target) target.textContent = '目标 —';
        const gap = owner.querySelector('.pro-bi-progress-card__gap');
        if (gap) gap.textContent = '—';
      }
      function scrubZeroPlaceholders() {
        const failure = /AP未返回成功|AP请求超时|看板AP查询失败|SQL 超时/;
        document.querySelectorAll('.pro-bi-comp-wrap').forEach(owner => {
          if (!failure.test(owner.textContent || '')) return;
          owner.querySelectorAll('*').forEach(element => {
            if (element.children.length) return;
            const text = element.textContent || '';
            if (!/(^|[^\d.])0\.00\s*(?:亿元|GWh|天|%|单)/.test(text)) return;
            element.textContent = text.replace(/(^|[^\d.])0\.00(\s*(?:亿元|GWh|天|%|单))/g, '$1—$2');
            element.title = liveError.value;
          });
        });
      }
      function sweepStuckLoading() {
        if (!liveError.value) return;
        scrubFailedMetrics();
        scrubZeroPlaceholders();
        // Give still-running queries a grace window; only then treat a
        // remaining "loading" card as failed instead of overwriting its value.
        if (Date.now() - liveErrorSince < 6000) return;
        document.querySelectorAll('.cockpit-board *').forEach(element => {
          if (element.children.length) return;
          if (/^(loading|加载中)$/i.test((element.textContent || '').trim())) {
            element.textContent = '加载失败';
            element.title = liveError.value;
          }
        });
        document.querySelectorAll('.pro-bi-chart-loading').forEach(scrubUnavailableComponent);
      }
      function showLiveError(message, detail = {}) {
        if (!liveFailures.size) liveErrorSince = Date.now();
        if (message) liveFailures.add(message);
        liveError.value = liveFailures.size ? '部分指标加载失败：' + [...liveFailures].join('；') : '';
        if (detail.kind === 'helmet') annotateFailedHelmet(liveError.value);
        clearTimeout(liveErrorClear);
        // The vendor cards keep an internal "loading" label when a promise
        // rejects; replace only that placeholder, never a real value.
        clearInterval(liveErrorSweep);
        liveErrorSweep = setInterval(sweepStuckLoading, 4000);
        liveErrorClear = setTimeout(sweepStuckLoading, 6000);
        setTimeout(() => { if (liveError.value) sweepStuckLoading(); }, 15000);
      }
      function clearLiveError() {
        liveFailures.clear();
        liveErrorSince = 0;
        liveError.value = '';
        clearTimeout(liveErrorClear);
        clearInterval(liveErrorSweep);
        clearHelmetAnnotations();
      }

      async function loadJson(url) {
        const response = await fetch(url, {headers: {Accept: 'application/json'}});
        if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
        return response.json();
      }

      function createRuntime(payload) {
        const instance=ProUIBi.createBiRuntime({runtimeKey:'iba-demo'});
        if(payload?.templates)instance.setTemplateRegistry?.(payload.templates);
        const selectGrain=instance.setButtonGrainSelection;
        if(typeof selectGrain==='function'){
          instance.setButtonGrainSelection=function(...args){
            const result=selectGrain.apply(this,args);
            applyPeriodFilterOptions(runtime.value||payload,periodGrain(args[1]));
            return result;
          };
        }
        return instance;
      }

      async function loadRuntime() {
        // Only the delivered layout and the two small capability endpoints are
        // needed before the board can render.  Saved cards, page snapshots and
        // update status are loaded afterwards and never hold the shell.
        const [payload,capabilities,dataConfig,bootstrap] = await Promise.all([
          loadJson(runtimeUrl),
          loadJson(`${apiBase}/engines`),
          loadJson(`${apiBase}/data/config`),
          loadJson(`${apiBase}/bootstrap`),
        ]);
        const periodConfig = bootstrap?.periodConfig || {};
        defaultPeriod = periodText(periodConfig.defaultPeriod) || defaultPeriod;
        activePeriod = periodText(periodConfig.activePeriod) || activePeriod;
        preheatPeriods = Array.isArray(periodConfig.preheatPeriods)
          ? periodConfig.preheatPeriods.map(periodText).filter(Boolean)
          : [activePeriod, defaultPeriod].filter(Boolean);
        if (!preheatPeriods.includes(defaultPeriod)) preheatPeriods.unshift(defaultPeriod);
        if(!capabilities.comparisonOnly || !params.has('engine'))analysisEngine=capabilities.default;
        if(baselineId){
          if(!capabilities.comparisonOnly || analysisEngine!=='standalone')throw new Error('当前不允许独立证据对照');
          baselineItem=await loadJson(`${apiBase}/analyses/${encodeURIComponent(baselineId)}`);
          if(baselineItem.context.engine!=='main')throw new Error('基线必须来自主服务');
        }
        dashboardDataMode.value = dataConfig.mode;
        if (dataConfig.mode === 'ap' && !dataConfig.available) throw new Error('实时AP代理需要连接主服务，当前独立服务不提供此能力');
        if(baselineItem){
          const nodes={opportunity:['2109848488855519233','2109840325158682625'],guidance:['2109848488910045186'],quotation:['2112022555167604737'],technical:['2109848488914239490'],bid:['2109848488918433794'],order:['2109848488926822401','2109840573998350338'],shipment:['2109848488926822402','2109840696539136002']};
          const selected=nodes[baselineItem.context.stage]||[];
          for(const spec of [...Object.values(payload.pages),...Object.values(payload.templates)]){
            for(const c of spec.components||[]){if(c.type==='mini-cpgraph'){
              const rule=c.graphConfig?.graphTemplateSwitchRules?.find(r=>selected.includes(r.nodeId));
              if(rule)c.graphConfig.defaultActiveKey=rule.nodeId;
            }}
          }
        }
        if(analysisEngine==='main') {
          const [{createPublicationClient}]=await Promise.all([
            import(`${assetBase}/publication-client.js?v=${encodeURIComponent(assetVersion)}`),
            startAiPublications(),
          ]);
          publications=createPublicationClient({apiBase,stateFor,bodyFor:mainBody,queue:withAnalysisSlot});
        }
        let installed;
        if (dataConfig.mode === 'ap') {
          const [{createAPDataClient,observeRuntimeFilters,observeActivationActions,tableFilterIds},{createPageCache},{createPublicationPoller}] = await Promise.all([
            import(`${assetBase}/data-client.js?v=${encodeURIComponent(assetVersion)}`),
            import(`${assetBase}/page-client.js?v=${encodeURIComponent(assetVersion)}`),
            import(`${assetBase}/publication-poll.js?v=${encodeURIComponent(assetVersion)}`),
          ]);
          let rawRuntime=createRuntime(payload);
          const tabs=payload.dashboard.components.find(c=>c.type==='tab-container');
          if(tabs)rawRuntime.setActiveTab(tabs.id,payload.pages[page.value].tabId);
          // Charts read live AP data by default.  The page snapshot still
          // supplies AI cards and display metadata, but it is not replayed as
          // chart data unless ?cache=1 is requested explicitly.
          const allowSnapshotReplay=/[?&]cache=1(?:&|$)/.test(location.search);
          const makeClient=(snapshot=null)=>createAPDataClient({apiBase,id:identityId,snapshot:allowSnapshotReplay?snapshot:null,
            stageFor:(kind,payload)=>queryStage(payload),priorityFor:queryPriority,
            // The data client falls back to a live read for a query omitted by
            // the page snapshot.  Do not rebuild the dashboard or inject a
            // host-specific cache message into the delivered component.
            onSnapshotMiss:()=>{fullSnapshot=null;pageState.cached=false;pageState.displayStale=true;},
            onError:(message,detail)=>showLiveError(message,detail),
            onRecover:()=>clearLiveError(),
            // Query mutations (paging, sorting, table-local filters) are display
            // changes.  A committed page-level filter calls changeScope and is
            // handled after the replacement client has loaded its receipts.
            onInvalidate:()=>{}});
          function install(snapshot,remount=false,metadata=[]) {
            if(snapshot&&(Number(snapshot.id)!==Number(identityId)||snapshot.page!==page.value||snapshot.uiScope!==currentUiScope))return;
            const incomingKey=snapshot?.version?`${page.value}:${currentUiScope}:${snapshot.version}`:'';
            if(remount&&incomingKey&&incomingKey===installedSnapshotKey&&liveDataClient){
              fullSnapshot=snapshot;
              if(snapshot.items)publications?.preload(snapshot.items);
              Object.assign(pageState,{cached:true,dataAsOf:snapshot.dataAsOf,
                analyzedAt:Math.max(0,...Object.values(snapshot.items||{}).map(item=>Number(item?.context?.updatedAt||item?.updatedAt||0))),error:''});
              return;
            }
            if(remount){
              filtersReady=false;
              const nextRuntime=createRuntime(payload);
              const restored=biRuntime.value?.replayView?.(nextRuntime);
              rawRuntime=nextRuntime;
              if(tabs)rawRuntime.setActiveTab(tabs.id,payload.pages[page.value].tabId);
              biRuntime.value=observeActivationActions(
                observeRuntimeFilters(rawRuntime,(uiScope,detail)=>changeScope(uiScope,false,detail),()=>filtersReady,restored,
                  {isUserAction:isScopeUserAction,localFilterIds:tableFilterIds(payload)}),
                {onTabChange:queueActivationNavigation,onHelmetSelection:rememberActivationHelmet});
              bindRiskCountRuntime(biRuntime.value);
              const path={segments:[{kind:'tab',containerId:tabs.id,tabId:payload.pages[page.value].tabId,templateId:payload.pages[page.value].templateId}]};
              for(const component of payload.templates[payload.pages[page.value].templateId]?.components||[]){
                if(component.type!=='button-group')continue;
                const grain=rawRuntime.getButtonGrainSelection(component.id,path);
                if(grain){
                  for(const item of component.buttonGroupConfig?.items||[])item.default=String(item.grain||'').toUpperCase()===grain;
                  applyPeriodFilterOptions(runtime.value||payload,grain);
                }
              }
            }
            fullSnapshot=snapshot;
            installedSnapshotKey=incomingKey;
            liveDataClient=makeClient(snapshot);
            const installedClient=liveDataClient;
            for(const entry of metadata)installedClient.read('helmet',entry.payload).then(data=>{
              if(canonical(data)!==canonical(entry.data)){
                const message='流程配置已变化，请刷新页面加载新版本';installedClient.block(message);
                if(installedClient===liveDataClient)pageState.error=message;
              }
            }).catch(()=>{});
            biAdapters.value=liveDataClient.biAdapters;hostUtils.value=liveDataClient.utils;
            ProUIBi.configureBi({...liveDataClient.biAdapters,utils:liveDataClient.utils});
            if(snapshot){publications?.preload(snapshot.items);Object.assign(pageState,{cached:true,dataAsOf:snapshot.dataAsOf,analyzedAt:Math.max(0,...Object.values(snapshot.items||{}).map(item=>Number(item?.context?.updatedAt||item?.updatedAt||0))),error:''});}
            if(remount){
              filtersReady=false;const top=window.scrollY;boardRevision.value++;
              nextTick(()=>requestAnimationFrame(()=>window.scrollTo({top,behavior:'instant'})));
            }
            const client=liveDataClient;
            const scopeReady=()=>{
              if(client!==liveDataClient)return;
              filtersReady=true;biRuntime.value?.flushPendingScope?.();
              if(scopeNeedsAnalysis){
                scopeNeedsAnalysis=false;
                for(const stage of visibleStages.keys())ensureAnalysis(stage,true,true).catch(()=>{});
              }
              onPageActivity();
            };
            const scopeFailed=cause=>{
              if(client!==liveDataClient)return;
              scopeReady();
              // A component can keep its own loading state forever when the
              // shared client settles without a complete result. Surface a
              // terminal, retryable message instead of an endless skeleton.
              if(cause)showLiveError('看板指标加载未完成：'+(cause.message||cause));
            };
            client.ready({allowExpired:Boolean(snapshot),partial:true}).then(scopeReady,scopeFailed);
            setTimeout(()=>{if(client===liveDataClient&&liveError.value)sweepStuckLoading();},6500);
          }
          function updateSnapshotInPlace(snapshot) {
            if(!snapshot||!liveDataClient||snapshot.uiScope!==currentUiScope)return;
            liveDataClient.applySnapshot?.(snapshot.entries||[]);
            if(!rawRuntime?.setComponentData)return;
            const templateId=payload.pages[page.value]?.templateId;
            const tab=payload.pages[page.value]?.tabId||'';
            // The runtime stores tab-contained components under the same path
            // shape as install(); omitting containerId silently updates only
            // the host context and leaves the visible charts on the old data.
            const path={segments:tab?[{kind:'tab',containerId:tabs.id,tabId:tab,templateId}]:[]};
            const components=payload.templates?.[templateId]?.components||[];
            const codesOf=value=>{
              const found=new Set(),stack=[value];
              while(stack.length){const node=stack.pop();
                if(Array.isArray(node)){stack.push(...node);continue;}
                if(!node||typeof node!=='object')continue;
                if(typeof node.identifierCode==='string')found.add(node.identifierCode);
                for(const child of Object.values(node))if(child&&typeof child==='object')stack.push(child);
              }
              return found;
            };
            const componentCodes=components.map(component=>({component,codes:codesOf(component.dataConfig||{})}));
            for(const entry of snapshot.entries||[]){
              if(!entry||entry.kind!=='analysis'||!entry.payload?.analysisConfig)continue;
              const queryCodes=codesOf({dimensions:entry.payload.analysisConfig.dimensions||[],
                indicators:entry.payload.analysisConfig.indicators||[]});
              if(!queryCodes.size)continue;
              for(const {component,codes} of componentCodes){
                if(codes.size!==queryCodes.size||![...queryCodes].every(code=>codes.has(code)))continue;
                const value={data:entry.data,error:null,loading:false,lastUpdated:Date.now()};
                rawRuntime.setComponentData(component.id,value,path);
                rawRuntime.setComponentData(component.id,value,{segments:[]});
              }
            }
          }
          const scheduleStatusPoll=(delay=1000)=>statusPoller?.poke(delay);
          async function changeScope(uiScope,miss=false,detail='') {
            const scopeKey=`${page.value}:${uiScope}`;
            const now=Date.now();
            const repeated=scopeKey===lastScopeRequestKey&&now-lastScopeRequestAt<(miss?30000:1200);
            if(repeated)return;
            lastScopeRequestKey=scopeKey;lastScopeRequestAt=now;
            // The gesture has been consumed by this scope change. SDK defaults
            // emitted while the replacement runtime mounts are not new actions.
            scopeActionUntil=0;
            let metadata=fullSnapshot?.entries?.filter(e=>e.kind==='helmet')||[];
            if(!metadata.length)try{metadata=liveDataClient.entries().filter(e=>e.kind==='helmet');}catch{}
            const token=++pageEpoch;pageCache?.invalidate();clearLiveError();
            currentUiScope=uiScope;defaultView=uiScope==='default';fullSnapshot=null;cardsVersion='';
            scopeNeedsAnalysis=!frozenAnnualMode;
            // Keep the last complete cards on screen; the notice says the scope
            // changed and that the visible analysis still belongs to the old one.
            const notice='筛选口径已切换'+(detail?'（'+detail+'）':'')+'，正在加载新数据；以下仍为上次分析';
            clearTimeout(refreshTimer);if(!frozenAnnualMode){publications?.invalidate(notice);markAiPublicationsStale(notice);}liveDataClient?.clearScope();
            // The slot store is independent from the board.  Ask for the new
            // scope, but keep every old payload on screen until a replacement
            // has been validated and returned.
            if(analysisEngine==='main')aiPublicationClient?.poke(0,uiScope);
            statusPoller?.poke(0);
            Object.assign(pageState,{cached:false,dataAsOf:0,error:'',refreshing:false,displayStale:true,updateStatus:'waiting'});
            filtersReady=false;await Promise.resolve();if(token!==pageEpoch)return;
            install(null,true,metadata);
            if(analysisEngine==='main')scheduleStatusPoll(800);
            if(!miss&&analysisEngine==='main') {
              try {const snapshot=await pageCache.load(uiScope);if(snapshot&&token===pageEpoch){install(snapshot,true);scheduleStatusPoll(800);}}catch{}
            }
          }
          biRuntime.value=observeActivationActions(
            observeRuntimeFilters(rawRuntime,(uiScope,detail)=>changeScope(uiScope,false,detail),()=>filtersReady,null,
              {isUserAction:isScopeUserAction,localFilterIds:tableFilterIds(payload)}),
            {onTabChange:queueActivationNavigation,onHelmetSelection:rememberActivationHelmet});
          bindRiskCountRuntime(biRuntime.value);
          // Historical cards are an independent, best-effort request.  The
          // board already exists; a slow cards response leaves only the AI
          // slot skeletons visible and never delays charts or the shell.
          async function loadCurrentHistoryCards(){
            if(frozenAnnualMode)return;
            const token=pageEpoch,target=page.value;
            try{
              const cards=await pageCache.cards();
              if(token!==pageEpoch||target!==page.value)return;
              publications?.preload(cards.items||{});
              cardsVersion=cards.cardsVersion||'';
              const analyzed=Math.max(0,...Object.values(cards.items||{}).map(item=>Number(item?.updatedAt||0)));
              if(analyzed)Object.assign(pageState,{analyzedAt:analyzed});
            }catch(_){/* the status poll retries the same read */}
          }
          if(analysisEngine==='main') {
            pageCache=createPageCache({independentCards:frozenAnnualMode,apiBase,id:identityId,page:page.value,makeClient,bodyFor:baseMainBody,
              onState:value=>Object.assign(pageState,value),
              onSnapshot:snapshot=>{
                // Background publications refresh metadata and AI cards in
                // place. Remounting the delivered board here would clear all
                // chart state and replay every query for a silent update.
                fullSnapshot=snapshot;
                if(snapshot.items)publications?.preload(snapshot.items);
                Object.assign(pageState,{cached:true,dataAsOf:snapshot.dataAsOf,analyzedAt:Math.max(0,...Object.values(snapshot.items||{}).map(item=>Number(item?.updatedAt||0))),error:'',refreshing:false,updateStatus:'published',displayStale:false});
              }});
            // Tab switches stay inside the mounted board.  Keep the SDK
            // instance and its data client intact: replacing either one makes
            // already rendered tabs query again.  The host only re-points the
            // route, page-specific cards, publication metadata and poller.
            switchPageImpl=async target=>{
              if(analysisEngine!=='main')return true;
              if(frozenAnnualMode){aiPublicationClient?.poke(0,currentUiScope);queueFrozenPriority();return true;}
              const token=++pageEpoch,scope=currentUiScope;
              clearTimeout(publishTimer);clearTimeout(refreshTimer);
              pageCache?.invalidate();
              pageCache=createPageCache({independentCards:frozenAnnualMode,apiBase,id:identityId,page:target,makeClient,bodyFor:baseMainBody,
                onState:value=>Object.assign(pageState,value),
                onSnapshot:snapshot=>{
                  fullSnapshot=snapshot;
                  if(snapshot.items)publications?.preload(snapshot.items);
                  Object.assign(pageState,{cached:true,dataAsOf:snapshot.dataAsOf,analyzedAt:Math.max(0,...Object.values(snapshot.items||{}).map(item=>Number(item?.updatedAt||0))),error:'',refreshing:false,updateStatus:'published',displayStale:false});
                }});
              let analysisReady=Promise.resolve(),cardsReady=Promise.resolve();
              if(scope==='default'){
                // Saved cards are one independent read.  The publication poll
                // handles the page snapshot/status in parallel and can never
                // hold the newly mounted tab.
                fullSnapshot=null;
                Object.assign(pageState,{cached:false,dataAsOf:0,displayStale:false,refreshing:false,error:''});
                cardsReady=pageCache.cards().then(cards=>{
                  if(token!==pageEpoch)return;
                  publications?.preload(cards.items||{});
                  cardsVersion=cards.cardsVersion||'';
                  const analyzed=Math.max(0,...Object.values(cards.items||{}).map(item=>Number(item?.updatedAt||0)));
                  if(analyzed)Object.assign(pageState,{analyzedAt:analyzed});
                }).catch(()=>{});
                statusPoller?.poke(0);
                // Prefer waiting for cards so opening a tab reuses saved
                // analysis, but never strand the tab behind a slow card read.
                analysisReady=Promise.race([cardsReady,new Promise(resolve=>setTimeout(resolve,800))]);
              }else{
                // Custom filters are not represented by the default-scope
                // default history payload.  Keep the cards already on screen; the
                // publication client marks them stale until this scope lands.
                fullSnapshot=null;cardsVersion='';
                Object.assign(pageState,{cached:false,displayStale:true,refreshing:false,error:''});
                statusPoller?.poke(0);
              }
              analysisReady.catch(()=>{}).finally(()=>{
                if(token!==pageEpoch)return;
                for(const stage of stagesForPage(target))ensureAnalysis(stage).catch(()=>{});
              });
              return true;
            };
            statusPoller=createPublicationPoller({
              probe:async()=>{if(frozenAnnualMode)return null;const scope=currentUiScope;return {scope,status:await pageCache.status(scope)};},
              apply:async value=>{
                if(!pageCache||analysisEngine!=='main')return {active:false};
                const {scope,status}=value||{};
                // A late probe for the previous filter scope must not repaint
                // the current page or schedule work for it.
                if(!status||scope!==currentUiScope)return {active:false};
                const update=status.update||{};
                const active=['waiting','checking','running','queued','retry_wait'].includes(update.status);
                Object.assign(pageState,{
                  updateStatus:update.status||'idle',refreshing:active,
                  analyzedAt:status.analyzedAt||pageState.analyzedAt,
                  dataAsOf:status.dataAsOf||pageState.dataAsOf,
                  displayStale:Boolean(status.displayStale||update.status==='stale-display'),
                });
                if(status.publicationVersion&&(!fullSnapshot||status.publicationVersion!==fullSnapshot.version)){
                  const snapshot=await pageCache.load(scope);
                  if(snapshot&&scope===currentUiScope){
                    // Keep the mounted charts and data client intact. Publish
                    // new metadata/cards into the existing page version.
                    fullSnapshot=snapshot;
                    updateSnapshotInPlace(snapshot);
                    if(snapshot.items)publications?.preload(snapshot.items);
                    Object.assign(pageState,{cached:true,dataAsOf:snapshot.dataAsOf,displayStale:false,refreshing:false,error:'',updateStatus:'published'});
                  }
                }
                // Pages without a whole-page snapshot publish AI cards on their
                // own; a changed card version is replaced in place.
                if(currentUiScope==='default'&&status.cardsVersion&&status.cardsVersion!==cardsVersion&&publications){
                  try{
                    const value=await pageCache.cards();
                    if(scope===currentUiScope){publications.preload(value.items||{});cardsVersion=status.cardsVersion;}
                  }catch(_){/* the next poll retries the card fetch */}
                }
                return {active};
              },
              isHidden:()=>document.hidden,
            });
          }
          install(null);
          if(analysisEngine==='main'){
            loadCurrentHistoryCards();
            if(!frozenAnnualMode)statusPoller?.start(50);
          }
          onPageActivity=()=>{
            clearTimeout(publishTimer);
            if(frozenAnnualMode||analysisEngine!=='main'||fullSnapshot||publishing)return;
            publishTimer=setTimeout(async()=>{
              const token=pageEpoch,client=liveDataClient,uiScope=currentUiScope;
              // Stale cards belong to the previous filter scope: never publish
              // them as the version for the new one.
              const stages=[...visibleStages.keys()];
              if(stages.some(stage=>stateFor(stage).stale))return;
              const items=Object.fromEntries(stages.map(stage=>[stage,stateFor(stage).item]));
              if(Object.values(items).some(item=>item?.result?.cardContract!=='cockpit-cards-v1'))return;
              if(page.value!=='overview'&&!Object.keys(items).length)return;
              publishing=true;
              try {
                await client.ready();await new Promise(r=>setTimeout(r,500));
                if(token!==pageEpoch||client!==liveDataClient)return;
                const snapshot=await pageCache.publish(client,items,uiScope,undefined,true);
                if(snapshot&&token===pageEpoch){fullSnapshot=snapshot;Object.assign(pageState,{cached:true,dataAsOf:snapshot.dataAsOf,error:''});scheduleStatusPoll();}
              }catch(cause){
                if(token!==pageEpoch)return;
                // Automatic page merging is optional. A rejected or incomplete
                // merge keeps the live charts and published cards unchanged;
                // explicit user refreshes still surface their own errors.
                console.debug('[cockpit-page-publish]',cause?.message||cause);
                Object.assign(pageState,{error:'',refreshing:false,updateStatus:'waiting'});
              }
              finally{publishing=false;}
            },600);
          };
          installed=liveDataClient;
        } else if (dataConfig.mode === 'snapshot') {
          installed = installSnapshots(await loadJson(snapshotsUrl));
          biRuntime.value=createRuntime(payload);
          const tabs=payload.dashboard.components.find(c=>c.type==='tab-container');
          if(tabs)biRuntime.value.setActiveTab(tabs.id,payload.pages[page.value].tabId);
          const {observeActivationActions}=await import(`${assetBase}/data-client.js?v=${encodeURIComponent(assetVersion)}`);
          biRuntime.value=observeActivationActions(biRuntime.value,
            {onTabChange:queueActivationNavigation,onHelmetSelection:rememberActivationHelmet});
          bindRiskCountRuntime(biRuntime.value);
          biAdapters.value=installed.biAdapters;hostUtils.value=installed.utils;
        } else { throw new Error('未识别的看板取数模式'); }
        runtime.value = payload;
        if (!runtime.value?.dashboard) throw new Error('交付看板配置为空');
      }

      const retryRuntime = () => location.reload();
      async function bootRuntime() {
        error.value='';loading.value=true;
        try {
          await loadRuntime();
          await nextTick();
          applyPendingActivation();
          onPageActivity();
          schedulePrefetch();
        } catch (cause) {
          error.value = `看板配置加载失败：${cause.message || cause}`;
        } finally {
          loading.value = false;
        }
      }

      onMounted(() => {
        // Persisted AI cards are independent of layout, metrics and AP
        // readiness.  Start their read before runtime/config can delay the
        // board, and keep the store alive across every board remount.
        startAiPublications();
        document.title = `储能经营风险驾驶舱 · ${pageTitle.value}`;
        document.addEventListener('click', onTabClick, true);
        document.addEventListener('click', noteScopeAction, true);
        document.addEventListener('pointerdown', noteScopeAction, true);
        document.addEventListener('keydown', noteScopeAction, true);
        document.addEventListener('visibilitychange', onVisibilityChange);
        window.addEventListener('popstate', onPopState);
        if (location.pathname.endsWith('/cockpit/home')) {
          history.replaceState(null, '', routeFor('overview'));
        }
        // Vue owns the first paint from this point on.  Keeping the static
        // shell for the whole startup caused the old double loading state.
        document.getElementById('cockpit-boot')?.remove();
        bootRuntime();
      });
      onBeforeUnmount(() => {unbindRiskCountRuntime(biRuntime.value);statusPoller?.stop();aiPublicationClient?.stop();document.removeEventListener('click', onTabClick, true);document.removeEventListener('click', noteScopeAction, true);document.removeEventListener('pointerdown', noteScopeAction, true);document.removeEventListener('keydown', noteScopeAction, true);document.removeEventListener('visibilitychange', onVisibilityChange);window.removeEventListener('popstate', onPopState);switchPageImpl=null;clearTimeout(publishTimer);clearTimeout(refreshTimer);clearTimeout(activationTimer);clearTimeout(priorityTimer);clearTimeout(liveErrorClear);clearInterval(liveErrorSweep);pageCache?.invalidate();onPageActivity=()=>{};});

      return {
        frozenAnnualMode, frozenAnnual, refreshFrozenAnnual, failureDialog, closeFailureDialog, page, runtime, loading, error, retryRuntime, pageTitle, pageState, dashboardDescription, liveError, boardRevision, dashboard: release, release,
        pageInsights, dashboardComponent: dashboard, biAdapters, biRuntime, hostUtils,
        slot_name: insight => `insight-${insight.id}`,
      };
    },
  });
  app.component('cockpit-insight', CockpitInsight);
  app.component('cockpit-loading', CockpitLoading);
  app.config.errorHandler = cause => console.error('cockpit component error', cause);
  app.mount('#app');
})();
