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
  const params = new URLSearchParams(location.search);
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

  const {createApp, ref, computed, onMounted, onBeforeUnmount, nextTick} = window.Vue;

  let insightLoadError = '';
  const insightBundleReady = import(insightBundleUrl).catch(cause => {
    insightLoadError = `交付插槽组件加载失败：${cause.message || cause}`;
    console.error('cockpit insight bundle error', cause);
  });

  const DeliveredInsight = {
    props: {
      insight: {type: Object, required: true},
      slotProps: {type: Object, default: () => ({})},
    },
    setup(props) {
      const delivered = computed(() => window.InsightComponents?.[props.insight.id] || null);
      return {delivered};
    },
    template: `
      <component v-if="delivered" :is="delivered"></component>
      <div v-else class="cockpit-insight-missing" role="status">
        插槽组件缺失：{{ insight.id }}
      </div>
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
    const search = new URLSearchParams({id: identityId});
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
      const gaps = computed(() => {
        const values = [...(runtime.value?.gaps || [])];
        if (insightLoadError) {
          values.push({code: 'INSIGHT_BUNDLE_LOAD_FAILED', description: insightLoadError});
        }
        return values;
      });
      const pageInsights = computed(() => runtime.value?.pages?.[page.value]?.insights || []);
      const metadataSummary = computed(() => {
        const source = runtime.value?.source;
        if (!source) return '';
        const snapshot = source.snapshot || {};
        return `交付看板 ${source.branch}@${source.commit?.slice(0, 7)} · ${source.templateCount} 个模板 · ${source.totalComponents} 个组件 · ${source.insightComponents} 个插槽组件 · 快照 ${snapshot.analysisRequests} 个 AP 查询`;
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
  app.component('cockpit-insight', DeliveredInsight);
  app.config.errorHandler = cause => console.error('cockpit component error', cause);
  app.mount('#app');
})();
