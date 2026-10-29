/* The cockpit renders one delivered ProBiDashboard from iba-demo demo_1021.
 * Three tabs, their templates, component positions and insight placements are
 * used verbatim. The host only supplies the Fuxi identity (id=1|2), rewrites
 * the selected tab into the route path and consumes main-service AP results.
 */
(() => {
  'use strict';

  const root = document.querySelector('meta[name="app-root"]').content.replace(/\/$/, '');
  const routeRoot = location.pathname.replace(/\/cockpit(?:\/(?:home|overview|operations|analysis))?\/?$/, '');
  const assetVersion = document.querySelector('meta[name="cockpit-version"]')?.content || '1';
  const assetBase = document.querySelector('meta[name="cockpit-assets"]')?.content || `${root}/static/cockpit`;
  const runtimeUrl = `${assetBase}/metadata/runtime.json?v=${encodeURIComponent(assetVersion)}`;
  const snapshotsUrl = `${assetBase}/metadata/pdt-release-2109836674373566465/data-snapshots.json?v=${encodeURIComponent(assetVersion)}`;
  const insightBundleUrl = `${assetBase}/insight-components/index.js?v=${encodeURIComponent(assetVersion)}`;
  const apiBase = (document.querySelector('meta[name="cockpit-api-base"]')?.content || `${root}/api/cockpit`).replace(/\/$/, '');
  const PERIOD = '2025-10';
  const DEPARTMENT = '全部产品部';
  const params = new URLSearchParams(location.search);
  let analysisEngine = params.get('engine') === 'standalone' ? 'standalone' : 'main';
  const baselineId = params.get('baseline') || '';
  let baselineItem = null;
  const identityId = ['1', '2'].includes(params.get('id')) ? params.get('id') : '1';
  const PAGES = {
    overview: {title: '经营看板', tab: '经营看板'},
    operations: {title: '运营360整体分析', tab: '运营360整体分析'},
    analysis: {title: '穿透式问题分析', tab: '穿透式问题分析'},
  };
  const PAGE_ALIASES = {home: 'overview'};

  if (!window.Vue) {
    document.getElementById('app').textContent = 'Vue 资源加载失败，请刷新页面。';
    return;
  }
  const ProUIBi = window.ProUIBi;
  const dashboard = ProUIBi?.ProBiDashboard;
  if (!dashboard || !ProUIBi.configureBi) {
    document.getElementById('app').textContent = 'ProUI 组件资源加载失败，请刷新页面或检查静态资源。';
    document.getElementById('app').removeAttribute('v-cloak');
    return;
  }

  const {createApp, ref, computed, reactive, onMounted, onBeforeUnmount, nextTick, shallowRef, markRaw, getCurrentInstance} = window.Vue;

  const dashboardDataMode = ref('ap');
  let liveDataClient = null;
  let publications = null;
  let defaultView = true;
  let refreshDebounce = null;
  let filtersReady = false;
  const insightLoadError = ref('');
  let insightBundleReady;
  let fullSnapshot = null, pageCache = null, currentUiScope = 'default';
  const pageState = reactive({cached:false,dataAsOf:0,refreshing:false,error:''});
  const dashboardDescription = computed(() => {
    const parts = [];
    if (pageState.cached) parts.push('完整看板 · 数据时间 ' + new Date(pageState.dataAsOf * 1000).toLocaleString('zh-CN', {hour12:false}));
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
    'sales-shipment-issues': 'shipment',
    'opportunity-risk': 'opportunity',
    'opportunity-coverage-note': 'opportunity',
    'order-risk-summary': 'order',
    'shipment-risk-summary': 'shipment',
    'shipment-overdue-note': 'shipment',
    'shipment-cause-breakdown': 'shipment',
    'shipment-task-order': 'shipment',
  };
  const STAGE_NAMES = {
    opportunity: '商机获取',
    guidance: '方案引导',
    quotation: '报价',
    technical: '技术方案',
    bid: '投标',
    order: '订单接收',
    shipment: '发货',
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
    if (!insightState[stage]) insightState[stage] = {status: 'idle', progress: '', item: null, error: ''};
    return insightState[stage];
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
      const current = liveDataClient ? liveDataClient.scope({partial:true}) : {chartQueries: [...displayedQueries].sort(), apReceiptIds: []};
      if (dashboardQueryError || canonical(context.chartQueries||[])!==canonical(current.chartQueries) || canonical(context.apReceiptIds||[])!==canonical(current.apReceiptIds)) throw new Error(dashboardQueryError || '看板查询范围已变化，请重新分析');
    }
    if(context.engine!==analysisEngine || context.id!==Number(identityId) || context.stage!==stage ||
       context.period!==(baselineItem?.context.period||PERIOD) || context.department!==(baselineItem?.context.department||DEPARTMENT) ||
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
      dataScope = await liveDataClient.ready({partial:true});
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
    state.progress = 'AI 正在分析';
    state.error = '';
    const body = JSON.stringify({
      id: Number(identityId),
      engine: analysisEngine,
      clarifications: clarificationAnswers.get(stage) || {},
      chartSnapshotId: 'pdt-release-2109836674373566465',
      chartQueries: dataScope.chartQueries,
      apReceiptIds: dataScope.apReceiptIds,
      unavailableQueries: (dataScope.unavailable || []).map(entry => entry.query),
      period: baselineItem?.context.period || PERIOD,
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
    state.progress = item.progress || '读取当前快照';
    const deadline = Date.now() + 240000;
    while (item.status === 'queued' || item.status === 'running') {
      if (Date.now() > deadline) throw new Error('模型分析超时，请重试');
      await new Promise(resolve => setTimeout(resolve, 1500));
      const poll = await fetch(`${apiBase}/analyses/${encodeURIComponent(item.id)}`, {headers: {'Accept': 'application/json'}});
      if (!poll.ok) throw new Error(await responseError(poll));
      item = checkedAnalysis(await poll.json(), stage);
      state.item = item;
      state.progress = item.progress || '模型分析中';
    }
    if (!['completed', 'limited', 'needs_input'].includes(item.status)) throw new Error(item.progress || '分析未完成');
    state.status = 'done';
    state.item = item;
    state.progress = '';
    return item;
  }

  function ensureAnalysis(stage, refresh = false, urgent = false) {
    if (analysisEngine === 'main' && fullSnapshot) {
      if (refresh) return pageCache.refresh(fullSnapshot,true);
      return Promise.resolve(stateFor(stage).item);
    }
    if (analysisEngine === 'main' && publications) return publications.refresh(stage, refresh, urgent).finally(onPageActivity);
    const state = stateFor(stage);
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
    return {id:Number(identityId),engine:'main',source:'service',page:pageFromLocation(),defaultView:currentUiScope==='default' && !clarificationAnswers.has(stage),
      stage,period:PERIOD,department:DEPARTMENT,filters:{},repositoryId:'',chartSnapshotId:'pdt-release-2109836674373566465',
      clarifications:clarificationAnswers.get(stage)||{},refresh:Boolean(refresh)};
  }
  async function mainBody(stage,refresh) {
    let dataScope;
    if(liveDataClient) dataScope=await liveDataClient.ready({partial:true});
    else {for(let n=0;n<20 && !displayedQueries.size;n++) await new Promise(r=>setTimeout(r,100));if(dashboardQueryError)throw new Error(dashboardQueryError);dataScope={chartQueries:[...displayedQueries].sort(),apReceiptIds:[]};}
    const {unavailable=[],...usableScope}=dataScope;
    return {...baseMainBody(stage,refresh),...usableScope,unavailableQueries:unavailable.map(entry=>entry.query)};
  }

  const CockpitInsight = {
    props: {insight: {type: Object, required: true}, slotProps: {type: Object, default: () => ({})}},
    setup(props) {
      const stage = computed(() => SLOT_STAGE[props.insight.id] || 'shipment');
      const state = computed(() => stateFor(stage.value));
      const delivered = shallowRef(null);
      const analysisContext = computed(() => ({
        id: Number(identityId),
        stage: stage.value,
        stageName: STAGE_NAMES[stage.value] || stage.value,
        period: analysisEngine === 'main' ? '' : baselineItem?.context.period || PERIOD,
        department: analysisEngine === 'main' ? '' : baselineItem?.context.department || DEPARTMENT,
      }));
      const compareLink = computed(()=>{if(!state.value.item)return '';const url=new URL(location.href);url.searchParams.set('engine','standalone');url.searchParams.set('baseline',state.value.item.id);return url.pathname+url.search;});
      const clarification = ref('');
      const confirmScope = () => {if(!clarification.value.trim())return;clarificationAnswers.set(stage.value, {answer:clarification.value.trim()});ensureAnalysis(stage.value,true,true).catch(()=>{});};
      const stop = async () => {if(state.value.item?.id)await fetch(`${apiBase}/analyses/${state.value.item.id}/cancel`,{method:'POST'});};
      const reload = () => ensureAnalysis(stage.value, true, true).catch(() => {});
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
        if(next)ensureAnalysis(registeredStage).catch(()=>{});
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
      onBeforeUnmount(()=>{
        alive=false;
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
          await ensureAnalysis(stage.value);onPageActivity();
        } catch(cause) {if(alive)insightLoadError.value=`插槽加载失败：${cause.message||cause}`;}
      });
      return {dashboardDataMode, delivered, state, analysisContext, reload, insightLoadError, analysisEngine, clarification, confirmScope, stop, compareLink, baselineId};
    },
    template: `
      <component v-if="delivered" :is="delivered"
                 :analysis="state.item" :status="state.status" :progress="state.progress"
                 :cached="state.cached" :refreshing="state.refreshing"
                 :error="state.error" :context="analysisContext" :slot-props="slotProps"
                 @retry="reload"></component>
      <div v-else-if="insightLoadError" class="insight-runtime-empty" role="status">{{ insightLoadError }}</div>
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

  const app = createApp({
    setup() {
      const page = ref(pageFromLocation());
      const runtime = ref(null);
      const loading = ref(true);
      const error = ref('');
      const boardRevision=ref(0);
      let publishTimer=null, refreshTimer=null, pageEpoch=0, publishing=false;
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
      const gaps = computed(() => runtime.value?.gaps || []);
      const pageInsights = computed(() => runtime.value?.pages?.[page.value]?.insights || []);
      const metadataSummary = computed(() => {
        const source = runtime.value?.source;
        if (!source) return '';
        const snapshot = source.snapshot || {};
        const mode = source.dataMode === 'ap-single-query' ? 'AP 单查' : `快照 ${snapshot.analysisRequests} 个 AP 查询`;
        return `交付看板 ${source.branch}@${source.commit?.slice(0, 7)} · ${source.templateCount} 个模板 · ${source.totalComponents} 个组件 · ${source.insightComponents} 个插槽声明 · ${mode}`;
      });

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
          location.assign(routeFor(target, node ? {node} : {}));
        }, 120);
      }
      function rememberActivationHelmet(componentId, selection, path) {
        const node = String(selection?.nodeId || selection?.id || '').trim();
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
            biRuntime.value?.setHelmetGraphSelection?.(pending.componentId, pending.selection, pending.path);
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
        location.assign(routeFor(entry[0]));
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

      async function loadRuntime() {
        const [payload,startup] = await Promise.all([loadJson(runtimeUrl),loadJson(`${apiBase}/startup?id=${identityId}&page=${page.value}`)]);
        const capabilities=startup.engines,dataConfig=startup.dataConfig;
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
          const {createPublicationClient}=await import(`${assetBase}/publication-client.js?v=${encodeURIComponent(assetVersion)}`);
          publications=createPublicationClient({apiBase,stateFor,bodyFor:mainBody,queue:withAnalysisSlot});
          publications.preload(startup.cards||{});
        }
        let installed;
        if (dataConfig.mode === 'ap') {
          const [{createAPDataClient,observeRuntimeFilters,observeActivationActions},{createPageCache}] = await Promise.all([
            import(`${assetBase}/data-client.js?v=${encodeURIComponent(assetVersion)}`),
            import(`${assetBase}/page-client.js?v=${encodeURIComponent(assetVersion)}`),
          ]);
          let rawRuntime=ProUIBi.createBiRuntime();
          const tabs=payload.dashboard.components.find(c=>c.type==='tab-container');
          if(tabs)rawRuntime.setActiveTab(tabs.id,payload.pages[page.value].tabId);
          const makeClient=(snapshot=null)=>createAPDataClient({apiBase,id:identityId,snapshot,
            onSnapshotMiss:()=>changeScope(currentUiScope,true),
            onError:(message,detail)=>showLiveError(message,detail),
            onRecover:()=>clearLiveError(),
            onInvalidate:()=>{
              if(analysisEngine!=='main'||fullSnapshot)return;
              clearTimeout(refreshDebounce);
              refreshDebounce=setTimeout(()=>{for(const stage of visibleStages.keys())ensureAnalysis(stage).catch(()=>{});onPageActivity();},400);
            }});
          function install(snapshot,remount=false,metadata=[]) {
            if(remount){
              filtersReady=false;
              const nextRuntime=ProUIBi.createBiRuntime();
              const restored=biRuntime.value?.replayView?.(nextRuntime);
              rawRuntime=nextRuntime;
              if(tabs)rawRuntime.setActiveTab(tabs.id,payload.pages[page.value].tabId);
              biRuntime.value=observeActivationActions(
                observeRuntimeFilters(rawRuntime,uiScope=>changeScope(uiScope),()=>filtersReady,restored),
                {onTabChange:queueActivationNavigation,onHelmetSelection:rememberActivationHelmet});
              const path={segments:[{kind:'tab',containerId:tabs.id,tabId:payload.pages[page.value].tabId,templateId:payload.pages[page.value].templateId}]};
              for(const component of payload.templates[payload.pages[page.value].templateId]?.components||[]){
                if(component.type!=='button-group')continue;
                const grain=rawRuntime.getButtonGrainSelection(component.id,path);
                if(grain)for(const item of component.buttonGroupConfig?.items||[])item.default=String(item.grain||'').toUpperCase()===grain;
              }
            }
            fullSnapshot=snapshot;
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
            if(snapshot){publications?.preload(snapshot.items);Object.assign(pageState,{cached:true,dataAsOf:snapshot.dataAsOf,error:''});}
            if(remount){
              filtersReady=false;const top=window.scrollY;boardRevision.value++;
              nextTick(()=>requestAnimationFrame(()=>window.scrollTo({top,behavior:'instant'})));
            }
            const client=liveDataClient;
            client.ready({allowExpired:Boolean(snapshot),partial:true}).then(()=>{if(client===liveDataClient){filtersReady=true;onPageActivity();}}).catch(()=>{if(client===liveDataClient){filtersReady=true;onPageActivity();}});
            setTimeout(()=>{if(client===liveDataClient&&liveError.value)sweepStuckLoading();},6500);
          }
          function schedulePageRefresh(delay=120000) {
            clearTimeout(refreshTimer);
            refreshTimer=setTimeout(async()=>{
              if(!fullSnapshot||!pageCache)return;
              if(document.hidden){schedulePageRefresh(30000);return;}
              const token=pageEpoch;
              await pageCache.refresh(fullSnapshot);
              if(token===pageEpoch&&fullSnapshot)schedulePageRefresh(pageState.error?60000:120000);
            },delay);
          }
          async function changeScope(uiScope,miss=false) {
            let metadata=fullSnapshot?.entries?.filter(e=>e.kind==='helmet')||[];
            if(!metadata.length)try{metadata=liveDataClient.entries().filter(e=>e.kind==='helmet');}catch{}
            const token=++pageEpoch;pageCache?.invalidate();clearLiveError();
            currentUiScope=uiScope;defaultView=uiScope==='default';fullSnapshot=null;
            clearTimeout(refreshTimer);publications?.invalidate();liveDataClient?.clearScope();
            Object.assign(pageState,{cached:false,dataAsOf:0,error:'',refreshing:false});
            filtersReady=false;await Promise.resolve();if(token!==pageEpoch)return;
            install(null,true,metadata);
            if(!miss&&analysisEngine==='main') {
              try {const snapshot=await pageCache.load(uiScope);if(snapshot&&token===pageEpoch){install(snapshot,true);schedulePageRefresh(800);}}catch{}
            }
          }
          biRuntime.value=observeActivationActions(
            observeRuntimeFilters(rawRuntime,uiScope=>changeScope(uiScope),()=>filtersReady),
            {onTabChange:queueActivationNavigation,onHelmetSelection:rememberActivationHelmet});
          if(analysisEngine==='main') {
            pageCache=createPageCache({apiBase,id:identityId,page:page.value,makeClient,bodyFor:baseMainBody,
              onState:value=>Object.assign(pageState,value),
              onSnapshot:snapshot=>{
                const changed=fullSnapshot?.version!==snapshot.version;
                if(changed)install(snapshot,true);
                else{fullSnapshot=snapshot;pageState.dataAsOf=snapshot.dataAsOf;pageState.error='';}
              }});
          }
          install(analysisEngine==='main'?startup.snapshot:null);
          if(fullSnapshot)schedulePageRefresh(1000);
          onPageActivity=()=>{
            clearTimeout(publishTimer);
            if(analysisEngine!=='main'||fullSnapshot||publishing)return;
            publishTimer=setTimeout(async()=>{
              const token=pageEpoch,client=liveDataClient,uiScope=currentUiScope;
              const items=Object.fromEntries([...visibleStages.keys()].map(stage=>[stage,stateFor(stage).item]));
              if(Object.values(items).some(item=>item?.result?.cardContract!=='cockpit-cards-v1'))return;
              if(page.value!=='overview'&&!Object.keys(items).length)return;
              publishing=true;
              try {
                await client.ready();await new Promise(r=>setTimeout(r,500));
                if(token!==pageEpoch||client!==liveDataClient)return;
                const snapshot=await pageCache.publish(client,items,uiScope);
                if(snapshot&&token===pageEpoch){fullSnapshot=snapshot;Object.assign(pageState,{cached:true,dataAsOf:snapshot.dataAsOf,error:''});schedulePageRefresh();}
              }catch(cause){if(token===pageEpoch)pageState.error=cause.message||'未形成完整看板';}
              finally{publishing=false;}
            },600);
          };
          installed=liveDataClient;
        } else if (dataConfig.mode === 'snapshot') {
          installed = installSnapshots(await loadJson(snapshotsUrl));
          biRuntime.value=ProUIBi.createBiRuntime();
          const tabs=payload.dashboard.components.find(c=>c.type==='tab-container');
          if(tabs)biRuntime.value.setActiveTab(tabs.id,payload.pages[page.value].tabId);
          const {observeActivationActions}=await import(`${assetBase}/data-client.js?v=${encodeURIComponent(assetVersion)}`);
          biRuntime.value=observeActivationActions(biRuntime.value,
            {onTabChange:queueActivationNavigation,onHelmetSelection:rememberActivationHelmet});
          biAdapters.value=installed.biAdapters;hostUtils.value=installed.utils;
        } else { throw new Error('未识别的看板取数模式'); }
        runtime.value = payload;
        if (!runtime.value?.dashboard) throw new Error('交付看板配置为空');
      }

      onMounted(async () => {
        document.title = `储能经营风险驾驶舱 · ${pageTitle.value}`;
        document.addEventListener('click', onTabClick, true);
        if (location.pathname.endsWith('/cockpit/home')) {
          history.replaceState(null, '', routeFor('overview'));
        }
        try {
          await loadRuntime();
          await nextTick();
          applyPendingActivation();
          onPageActivity();
          schedulePrefetch();
        } catch (cause) {
          error.value = `正式看板配置加载失败：${cause.message}`;
        } finally {
          loading.value = false;
          document.getElementById('cockpit-boot')?.remove();
        }
      });
      onBeforeUnmount(() => {document.removeEventListener('click', onTabClick, true);clearTimeout(refreshDebounce);clearTimeout(publishTimer);clearTimeout(refreshTimer);clearTimeout(activationTimer);clearTimeout(liveErrorClear);clearInterval(liveErrorSweep);pageCache?.invalidate();onPageActivity=()=>{};});

      return {
        page, runtime, loading, error, pageTitle, pageState, dashboardDescription, liveError, boardRevision, dashboard: release, release, gaps, metadataSummary,
        pageInsights, dashboardComponent: dashboard, biAdapters, biRuntime, hostUtils,
        slot_name: insight => `insight-${insight.id}`,
      };
    },
  });
  app.component('cockpit-insight', CockpitInsight);
  app.config.errorHandler = cause => console.error('cockpit component error', cause);
  app.mount('#app');
})();
