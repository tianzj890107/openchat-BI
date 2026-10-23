/* The cockpit renders one delivered ProBiDashboard from iba-demo demo_1021.
 * Three tabs, their templates, component positions and insight placements are
 * used verbatim. The host only supplies the Fuxi identity (id=1|2), rewrites
 * the selected tab into the route path and replays frozen AP responses.
 */
(() => {
  'use strict';

  const root = document.querySelector('meta[name="app-root"]').content.replace(/\/$/, '');
  const routeRoot = location.pathname.replace(/\/cockpit(?:\/(?:home|overview|operations|analysis))?\/?$/, '');
  const assetVersion = document.querySelector('meta[name="cockpit-version"]')?.content || '1';
  const runtimeUrl = `${root}/static/cockpit/metadata/runtime.json?v=${encodeURIComponent(assetVersion)}`;
  const snapshotsUrl = `${root}/static/cockpit/metadata/pdt-release-2109836674373566465/data-snapshots.json?v=${encodeURIComponent(assetVersion)}`;
  const insightBundleUrl = `${root}/static/cockpit/insight-components/index.js?v=${encodeURIComponent(assetVersion)}`;
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

  const {createApp, ref, computed, reactive, onMounted, onBeforeUnmount, nextTick} = window.Vue;

  const insightLoadError = ref('');
  const insightReady = ref(false);
  const insightBundleReady = import(insightBundleUrl).then(() => {
    insightReady.value = true;
  }).catch(cause => {
    insightLoadError.value = `交付插槽组件加载失败：${cause.message || cause}`;
    console.error('cockpit insight bundle error', cause);
  });

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
  let runningAnalyses = 0;

  function pumpAnalysisQueue() {
    while (runningAnalyses < (analysisEngine === 'main' ? 1 : MAX_CONCURRENT) && analysisQueue.length) {
      const job = analysisQueue.shift();
      runningAnalyses += 1;
      job.run().then(job.resolve, job.reject).finally(() => {
        runningAnalyses -= 1;
        pumpAnalysisQueue();
      });
    }
  }

  function withAnalysisSlot(run) {
    return new Promise((resolve, reject) => {
      analysisQueue.push({run, resolve, reject});
      pumpAnalysisQueue();
    });
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
    state.progress = '提交模型分析';
    state.error = '';
    const body = JSON.stringify({
      id: Number(identityId),
      engine: analysisEngine,
      clarifications: clarificationAnswers.get(stage) || {},
      chartSnapshotId: 'pdt-release-2109836674373566465',
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
    for (let attempt = 0; attempt < 4; attempt += 1) {
      response = await fetch(`${apiBase}/analyses`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
        body,
      });
      if (response.status !== 429) break;
      state.progress = '分析并发已满，排队重试';
      await new Promise(resolve => setTimeout(resolve, 3000));
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

  function ensureAnalysis(stage, refresh = false) {
    const state = stateFor(stage);
    if (!refresh && state.status === 'done' && state.item) return Promise.resolve(state.item);
    if (!refresh && analysisPromises.has(stage)) return analysisPromises.get(stage);
    const promise = withAnalysisSlot(() => startAnalysis(stage, refresh)).catch(cause => {
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

  const CockpitInsight = {
    props: {insight: {type: Object, required: true}, slotProps: {type: Object, default: () => ({})}},
    setup(props) {
      const stage = computed(() => SLOT_STAGE[props.insight.id] || 'shipment');
      const state = computed(() => stateFor(stage.value));
      const delivered = computed(() => insightReady.value ? window.InsightComponents?.[props.insight.id] || null : null);
      const analysisContext = computed(() => ({
        id: Number(identityId),
        stage: stage.value,
        stageName: STAGE_NAMES[stage.value] || stage.value,
        period: baselineItem?.context.period || PERIOD,
        department: baselineItem?.context.department || DEPARTMENT,
      }));
      const compareLink = computed(()=>{if(!state.value.item)return '';const url=new URL(location.href);url.searchParams.set('engine','standalone');url.searchParams.set('baseline',state.value.item.id);return url.pathname+url.search;});
      const clarification = ref('');
      const confirmScope = () => {if(!clarification.value.trim())return;clarificationAnswers.set(stage.value, {answer:clarification.value.trim()});ensureAnalysis(stage.value,true).catch(()=>{});};
      const stop = async () => {if(state.value.item?.id)await fetch(`${apiBase}/analyses/${state.value.item.id}/cancel`,{method:'POST'});};
      const reload = () => ensureAnalysis(stage.value, true).catch(() => {});
      onMounted(() => ensureAnalysis(stage.value).catch(() => {}));
      return {delivered, state, analysisContext, reload, insightLoadError, analysisEngine, clarification, confirmScope, stop, compareLink, baselineId};
    },
    template: `
      <section v-if="analysisEngine==='main'" class="main-service-insight" aria-live="polite">
        <div class="main-service-insight__meta">主服务分析 · {{analysisContext.period}} · {{analysisContext.department}} · 图表快照及筛选尚未与分析范围自动对齐</div>
        <div v-if="state.status==='running'">{{state.progress}} <button @click="stop">停止分析</button></div>
        <div v-else-if="state.status==='error'" role="alert">{{state.error}} <button @click="reload">重试</button></div>
        <template v-if="state.item?.result">
          <b>{{state.item.context.stageName}} · {{state.item.status==='needs_input'?'待确认口径':state.item.status==='limited'?'受限交付':'主服务交付'}}</b>
          <div class="main-service-insight__section">{{state.item.result.narrative}}</div>
          <div v-if="state.item.status==='needs_input'">
            <p>{{state.item.result.clarification?.question}}</p>
            <input v-model="clarification" aria-label="补充分析口径" placeholder="补充口径后重新分析"><button @click="confirmScope">确认并重新分析</button>
          </div>
          <a v-if="state.item.evidence?.facts?.length || state.item.evidence?.records?.length" :href="compareLink">用同一冻结证据对照独立路线</a>
          <details><summary>执行来源与证据（{{state.item.evidence?.facts?.length||0}}）</summary>
            <div v-for="fact in state.item.evidence?.facts||[]">{{fact.label}}</div>
            <div>耗时 {{state.item.execution?.durationSeconds}} 秒 · {{state.item.execution?.toolCalls}} 次工具调用</div>
            <div v-for="event in state.item.events||[]">{{event.tool}}</div>
            <div v-for="limit in state.item.result.limitations">{{limit}}</div>
          </details>
        </template>
      </section>
      <div v-if="analysisEngine==='standalone'" class="main-service-insight__meta">独立路线对照 · {{baselineId?'使用主服务冻结证据，只比较材料归纳':'原型演示证据，与交付图表快照尚未对齐'}}</div>
      <component v-if="analysisEngine==='standalone' && delivered" :is="delivered"
                 :analysis="state.item" :status="state.status" :progress="state.progress"
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

  function installSnapshots(snapshots) {
    const analysis = new Map(Object.entries(snapshots.analysis || {}));
    const batch = new Map(Object.entries(snapshots.batch || {}));
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
        if (hit && hit.success === false) throw new Error(hit.msg || hit.message || 'AP 查询失败');
        if (!hit?.data) throw new Error('未找到该 AP 查询的发布快照');
        return hit.data;
      },
      postAnalysisDataQueryBatch: async payload => {
        const hit = batch.get(canonical(payload));
        if (hit && hit.success === false) throw new Error(hit.msg || hit.message || 'AP 查询失败');
        if (!hit?.data) throw new Error('未找到该批量查询的发布快照');
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

  function routeFor(page) {
    const search = new URLSearchParams({id: identityId, engine: analysisEngine});
    if(baselineId)search.set('baseline',baselineId);
    return `${routeRoot}/cockpit/${page}?${search}`;
  }

  const app = createApp({
    setup() {
      const page = ref(pageFromLocation());
      const runtime = ref(null);
      const loading = ref(true);
      const error = ref('');
      const biAdapters = ref(null);
      const hostUtils = ref(null);
      const pageTitle = computed(() => PAGES[page.value]?.title || PAGES.overview.title);
      const release = computed(() => runtime.value?.dashboard || null);
      const gaps = computed(() => runtime.value?.gaps || []);
      const pageInsights = computed(() => runtime.value?.pages?.[page.value]?.insights || []);
      const metadataSummary = computed(() => {
        const source = runtime.value?.source;
        if (!source) return '';
        const snapshot = source.snapshot || {};
        return `交付看板 ${source.branch}@${source.commit?.slice(0, 7)} · ${source.templateCount} 个模板 · ${source.totalComponents} 个组件 · ${source.insightComponents} 个插槽声明 · 快照 ${snapshot.analysisRequests} 个 AP 查询`;
      });

      function findTab(label) {
        return [...document.querySelectorAll('.pro-bi-tab-container__tab')]
          .find(element => element.textContent.trim() === label);
      }

      function applyRouteTab() {
        const button = findTab(PAGES[page.value]?.tab);
        if (button && !button.classList.contains('is-active')) button.click();
      }

      function onTabClick(event) {
        const button = event.target.closest?.('.pro-bi-tab-container__tab');
        if (!button) return;
        const label = button.textContent.trim();
        const entry = Object.entries(PAGES).find(([, value]) => value.tab === label);
        if (!entry) return;
        page.value = entry[0];
        document.title = `${entry[1].title} · 储小策`;
        history.replaceState(null, '', routeFor(entry[0]));
      }

      async function loadJson(url) {
        const response = await fetch(url, {headers: {Accept: 'application/json'}});
        if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
        return response.json();
      }

      async function loadRuntime() {
        const capabilities=await loadJson(`${apiBase}/engines`);
        if(!capabilities.comparisonOnly || !params.has('engine'))analysisEngine=capabilities.default;
        if(baselineId){
          if(!capabilities.comparisonOnly || analysisEngine!=='standalone')throw new Error('当前不允许独立证据对照');
          baselineItem=await loadJson(`${apiBase}/analyses/${encodeURIComponent(baselineId)}`);
          if(baselineItem.context.engine!=='main')throw new Error('基线必须来自主服务');
        }
        const [payload, snapshots] = await Promise.all([loadJson(runtimeUrl), loadJson(snapshotsUrl)]);
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
        const installed = installSnapshots(snapshots);
        biAdapters.value = installed.biAdapters;
        hostUtils.value = installed.utils;
        runtime.value = payload;
        if (!runtime.value?.dashboard) throw new Error('交付看板配置为空');
      }

      onMounted(async () => {
        document.title = `${pageTitle.value} · 储小策`;
        document.addEventListener('click', onTabClick, true);
        if (location.pathname.endsWith('/cockpit/home')) {
          history.replaceState(null, '', routeFor('overview'));
        }
        try {
          await Promise.all([loadRuntime(), insightBundleReady]);
          await nextTick();
          setTimeout(applyRouteTab, 0);
          schedulePrefetch();
        } catch (cause) {
          error.value = `正式看板配置加载失败：${cause.message}`;
        } finally {
          loading.value = false;
        }
      });
      onBeforeUnmount(() => document.removeEventListener('click', onTabClick, true));

      return {
        page, runtime, loading, error, pageTitle, dashboard: release, release, gaps, metadataSummary,
        pageInsights, dashboardComponent: dashboard, biAdapters, hostUtils,
        slot_name: insight => `insight-${insight.id}`,
      };
    },
  });
  app.component('cockpit-insight', CockpitInsight);
  app.config.errorHandler = cause => console.error('cockpit component error', cause);
  app.mount('#app');
})();
