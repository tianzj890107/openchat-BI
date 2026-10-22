/* The published cockpit is one ProBiDashboard, matching the pdt release page.
 * The four tabs, header filter, card positions and templates all come from the
 * frozen release configuration. The host only keeps the Fuxi identity (id=1|2)
 * and mirrors the selected tab into the existing route paths.
 */
(() => {
  'use strict';

  const root = document.querySelector('meta[name="app-root"]').content.replace(/\/$/, '');
  const routeRoot = location.pathname.replace(/\/cockpit(?:\/(?:home|overview|operations|analysis))?\/?$/, '');
  const assetVersion = document.querySelector('meta[name="cockpit-version"]')?.content || '1';
  const runtimeUrl = `${root}/static/cockpit/metadata/runtime.json?v=${encodeURIComponent(assetVersion)}`;
  const snapshotsUrl = `${root}/static/cockpit/metadata/pdt-release-2109836674373566465/data-snapshots.json?v=${encodeURIComponent(assetVersion)}`;
  const apiBase = (document.querySelector('meta[name="cockpit-api-base"]')?.content || `${root}/api/cockpit`).replace(/\/+$/, '');
  const params = new URLSearchParams(location.search);
  const identityId = ['1', '2'].includes(params.get('id')) ? params.get('id') : '1';
  const PAGES = {
    home: {title: '首页', tab: '储能产品线整体经营分析'},
    overview: {title: '全局经营看板', tab: '全局经营看板'},
    operations: {title: '运营 360 整体分析', tab: '运营360整体分析'},
    analysis: {title: '穿透式问题分析', tab: '穿透式问题分析'},
  };

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

  /* Slot id -> analysis stage and the result section shown in that card. */
  const SLOT_STAGE = {
    'focus-risks': 'shipment',
    'bid-status-note': 'bid',
    'scheme-guide-summary': 'guidance',
    'quote-summary': 'quotation',
    'tech-plan-summary': 'technical',
    'bid-summary': 'bid',
    'order-sign-summary': 'order',
    'shipment-summary': 'shipment',
    'sales-shipment-issues': 'shipment',
    'opportunity-risk': 'opportunity',
    'opportunity-coverage-note': 'opportunity',
    'sales-bid-summary': 'bid',
    'order-risk-summary': 'order',
    'shipment-risk-summary': 'shipment',
    'shipment-overdue-note': 'shipment',
    'shipment-cause-breakdown': 'shipment',
    'shipment-task-order': 'shipment',
  };
  const SLOT_SECTION = {
    'focus-risks': 'causes3',
    'shipment-task-order': 'recommendations',
    'shipment-cause-breakdown': 'causes',
    'opportunity-risk': 'causes',
    'order-risk-summary': 'causes',
    'shipment-risk-summary': 'causes',
    'sales-shipment-issues': 'causes',
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
  const SLOT_TITLES = {
    'focus-risks': '今天重点关注的风险',
    'bid-status-note': '投标状态分析',
    'scheme-guide-summary': '方案引导分析',
    'quote-summary': '报价分析',
    'tech-plan-summary': '技术方案分析',
    'bid-summary': '投标分析',
    'order-sign-summary': '订单签订分析',
    'shipment-summary': '发货分析',
    'sales-shipment-issues': '发货问题与原因',
    'opportunity-risk': '商机风险分析',
    'opportunity-coverage-note': '商机覆盖分析',
    'sales-bid-summary': '投标结果分析',
    'order-risk-summary': '订单风险分析',
    'shipment-risk-summary': '发货风险分析',
    'shipment-overdue-note': '超期未发分析',
    'shipment-cause-breakdown': '发货原因拆解',
    'shipment-task-order': '改善建议',
  };

  const insightState = reactive({});
  const analysisPromises = new Map();
  const MAX_CONCURRENT = 3;
  const analysisQueue = [];
  let runningAnalyses = 0;

  function pumpAnalysisQueue() {
    while (runningAnalyses < MAX_CONCURRENT && analysisQueue.length) {
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

  async function startAnalysis(stage, refresh) {
    const state = stateFor(stage);
    state.status = 'running';
    state.progress = '提交模型分析';
    state.error = '';
    const body = JSON.stringify({
      id: Number(identityId),
      period: '2025-10',
      department: '全部产品部',
      stage,
      source: 'prototype',
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
    let item = await response.json();
    state.progress = item.progress || '读取当前快照';
    const deadline = Date.now() + 240000;
    while (item.status === 'queued' || item.status === 'running') {
      if (Date.now() > deadline) throw new Error('模型分析超时，请重试');
      await new Promise(resolve => setTimeout(resolve, 1500));
      const poll = await fetch(`${apiBase}/analyses/${encodeURIComponent(item.id)}`, {headers: {'Accept': 'application/json'}});
      if (!poll.ok) throw new Error(await responseError(poll));
      item = await poll.json();
      state.progress = item.progress || '模型分析中';
    }
    if (item.status !== 'completed') throw new Error(item.progress || '分析未完成');
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

  const CockpitInsight = {
    props: {insight: {type: Object, required: true}, slotProps: {type: Object, default: () => ({})}},
    setup(props) {
      const stage = computed(() => SLOT_STAGE[props.insight.id] || 'shipment');
      const section = computed(() => SLOT_SECTION[props.insight.id] || 'summary');
      const title = computed(() => SLOT_TITLES[props.insight.id] || props.insight.id);
      const state = computed(() => stateFor(stage.value));
      const conditions = computed(() => {
        const value = props.slotProps?.linkageConditions;
        if (!value) return '';
        if (Array.isArray(value) && !value.length) return '';
        if (typeof value === 'object' && !Array.isArray(value) && !Object.keys(value).length) return '';
        return typeof value === 'string' ? value : JSON.stringify(value);
      });
      const item = computed(() => state.value.item);
      const causes = computed(() => {
        const all = item.value?.result?.causes || [];
        return section.value === 'causes3' ? all.slice(0, 3) : all;
      });
      const evidenceCount = computed(() => item.value?.evidence?.evidence?.length || item.value?.result?.causes?.reduce((total, cause) => total + (cause.evidenceIds?.length || 0), 0) || 0);
      const duration = computed(() => {
        const created = Number(item.value?.createdAt);
        const updated = Number(item.value?.updatedAt);
        return Number.isFinite(created) && Number.isFinite(updated) && updated >= created ? updated - created : null;
      });
      const reload = () => ensureAnalysis(stage.value, true).catch(() => {});
      onMounted(() => ensureAnalysis(stage.value).catch(() => {}));
      return {
        stage, section, title, state, conditions, item, causes, evidenceCount, duration, reload,
        stageName: computed(() => STAGE_NAMES[stage.value] || stage.value),
      };
    },
    template: `
      <section class="cockpit-insight" :class="'is-' + state.status" :data-insight="insight.id" aria-live="polite">
        <header class="cockpit-insight__hd">
          <div class="cockpit-insight__title">
            <b>{{ title }}</b>
            <small>{{ stageName }} · 模型实时分析</small>
          </div>
          <button type="button" class="cockpit-insight__refresh"
                  :disabled="state.status === 'running'" @click="reload">
            {{ state.status === 'running' ? '分析中' : '重新分析' }}
          </button>
        </header>
        <div v-if="state.status === 'running'" class="cockpit-insight__loading">
          <i></i><span>{{ state.progress || '正在调用模型…' }} · 首次通常约 10–20 秒</span>
        </div>
        <div v-else-if="state.status === 'error'" class="cockpit-insight__error">
          <span>{{ state.error }}</span>
          <button type="button" @click="reload">重试</button>
        </div>
        <div v-else-if="item" class="cockpit-insight__body">
          <p v-if="section === 'summary'" class="cockpit-insight__summary">{{ item.result.summary }}</p>
          <ul v-else-if="section === 'recommendations'" class="cockpit-insight__list">
            <li v-for="action in item.result.recommendations" :key="action.id">
              <b>{{ action.action }}</b>
              <small>{{ action.ownerRole }} · 验收：{{ action.acceptance }}</small>
            </li>
          </ul>
          <ul v-else class="cockpit-insight__list">
            <li v-for="cause in causes" :key="cause.id">
              <b>{{ cause.title }}<em :class="'is-' + cause.status">{{ cause.status === 'supported' ? '有证据' : '待验证' }}</em></b>
              <small>{{ cause.description }}</small>
            </li>
          </ul>
          <p class="cockpit-insight__meta">演示数据 · 依据 {{ evidenceCount }} 条证据<span v-if="conditions"> · 联动 {{ conditions }}</span><span v-if="duration !== null"> · 首次分析 {{ duration.toFixed(1) }} 秒</span></p>
        </div>
        <div v-else class="cockpit-insight__idle">等待分析结果。</div>
      </section>
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

    ProUIBi.configureBi({
      postAnalysisDataQuery: async payload => {
        const key = canonical(payload);
        const hit = analysis.get(key);
        if (hit && hit.success === false) throw new Error(hit.msg || hit.message || 'AP 查询失败');
        if (!hit?.data) throw new Error('未找到该 AP 查询的发布快照');
        return hit.data;
      },
      postAnalysisDataQueryBatch: async payload => {
        const key = canonical(payload);
        const hit = batch.get(key);
        if (hit && hit.success === false) throw new Error(hit.msg || hit.message || 'AP 查询失败');
        if (!hit?.data) throw new Error('未找到该批量查询的发布快照');
        return hit.data;
      },
      utils: {
        request: async request => {
          const url = new URL(request.url, location.origin);
          const key = canonical({
            method: (request.method || 'get').toLowerCase(),
            path: url.pathname,
            params: request.params || Object.fromEntries(url.searchParams),
          });
          const hit = requests.get(key) || requests.get(canonical({
            method: (request.method || 'get').toLowerCase(),
            path: `/api/gateway2${url.pathname}`,
            params: request.params || Object.fromEntries(url.searchParams),
          }));
          if (!hit) return [new Error('未找到该接口的发布快照'), null];
          return [null, {data: hit.response.data, success: true}];
        },
      },
    });
  }

  function pageFromLocation() {
    const match = location.pathname.match(/\/cockpit\/(home|overview|operations|analysis)\/?$/);
    if (match && PAGES[match[1]]) return match[1];
    const declared = document.querySelector('meta[name="cockpit-page"]')?.content;
    return PAGES[declared] ? declared : 'overview';
  }

  function routeFor(page) {
    const search = new URLSearchParams({id: identityId});
    return `${routeRoot}/cockpit/${page}?${search}`;
  }

  const app = createApp({
    setup() {
      const page = ref(pageFromLocation());
      const runtime = ref(null);
      const loading = ref(true);
      const error = ref('');
      const pageTitle = computed(() => PAGES[page.value]?.title || PAGES.overview.title);
      const release = computed(() => runtime.value?.dashboard || null);
      const gaps = computed(() => runtime.value?.gaps || []);
      const pageInsights = computed(() => runtime.value?.pages?.[page.value]?.insights || []);
      const metadataSummary = computed(() => {
        const source = runtime.value?.source;
        if (!source) return '';
        return `正式发布看板 ${source.dashboardId} · v${source.version} · ${source.templateCount} 个模板 · ${source.totalComponents} 个组件 · 抓取 ${source.fetchedAt}`;
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
        const [payload, snapshots] = await Promise.all([loadJson(runtimeUrl), loadJson(snapshotsUrl)]);
        installSnapshots(snapshots);
        runtime.value = payload;
        if (!runtime.value?.dashboard) throw new Error('发布看板配置为空');
      }

      onMounted(async () => {
        document.title = `${pageTitle.value} · 储小策`;
        document.addEventListener('click', onTabClick, true);
        try {
          await loadRuntime();
          await nextTick();
          setTimeout(applyRouteTab, 0);
        } catch (cause) {
          error.value = `正式看板配置加载失败：${cause.message}`;
        } finally {
          loading.value = false;
        }
      });
      onBeforeUnmount(() => document.removeEventListener('click', onTabClick, true));

      return {
        page, runtime, loading, error, pageTitle, dashboard: release, release, gaps, metadataSummary,
        pageInsights, dashboardComponent: dashboard,
        slot_name: insight => `insight-${insight.id}`,
      };
    },
  });
  app.component('cockpit-insight', CockpitInsight);
  app.config.errorHandler = cause => console.error('cockpit component error', cause);
  app.mount('#app');
})();
