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

  const {createApp, ref, computed, onMounted, onBeforeUnmount, nextTick} = window.Vue;

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
        dashboardComponent: dashboard,
      };
    },
  });
  app.config.errorHandler = cause => console.error('cockpit component error', cause);
  app.mount('#app');
})();
