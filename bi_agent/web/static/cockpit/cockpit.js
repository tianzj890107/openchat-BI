/* V3 cockpit: metadata-driven ProUI dashboard with frozen demo data. */
(() => {
  'use strict';

  const root = document.querySelector('meta[name="app-root"]').content.replace(/\/$/, '');
  const routeRoot = location.pathname.replace(/\/cockpit(?:\/(?:overview|operations|analysis))?\/?$/, '');
  const runtimeUrl = `${root}/static/cockpit/metadata/runtime.json?v=proui-dashboard-v1`;
  const params = new URLSearchParams(location.search);
  const identityId = ['1', '2'].includes(params.get('id')) ? params.get('id') : '1';
  const PAGES = [
    {id: 'overview', title: '全局经营看板'},
    {id: 'operations', title: '运营 360 整体分析'},
    {id: 'analysis', title: '穿透式问题分析'},
  ];
  const PAGE_BY_ID = Object.fromEntries(PAGES.map(page => [page.id, page]));

  if (!window.Vue) {
    document.getElementById('app').textContent = 'Vue 资源加载失败，请刷新页面。';
    return;
  }
  const dashboard = window.ProUIBi?.ProBiDashboard;
  if (!dashboard) {
    document.getElementById('app').textContent = 'ProUI 组件资源加载失败，请刷新页面或检查静态资源。';
    document.getElementById('app').removeAttribute('v-cloak');
    return;
  }

  const {createApp, ref, computed, onMounted} = window.Vue;

  function pageFromLocation() {
    const match = location.pathname.match(/\/cockpit\/(overview|operations|analysis)\/?$/);
    if (match && PAGE_BY_ID[match[1]]) return match[1];
    const declared = document.querySelector('meta[name="cockpit-page"]')?.content;
    return PAGE_BY_ID[declared] ? declared : 'overview';
  }

  const app = createApp({
    setup() {
      const page = ref(pageFromLocation());
      const runtime = ref(null);
      const loading = ref(true);
      const error = ref('');

      const pageTitle = computed(() => PAGE_BY_ID[page.value]?.title || PAGES[0].title);
      const tabs = computed(() => PAGES.map(item => ({
        ...item,
        label: item.title,
        href: hrefFor(item.id),
        active: item.id === page.value,
      })));
      const gaps = computed(() => runtime.value?.gaps || []);
      const metadataSummary = computed(() => {
        const count = runtime.value?.counts?.[page.value];
        const source = runtime.value?.source;
        if (!count) return '';
        return `${pageTitle.value}：${count.total} 个元数据组件，${count.withData} 个已绑定演示数据；ProUI 原生组件渲染。数据包 ${source?.branch || 'iba-demo'}@${(source?.commit || '').slice(0, 8) || 'unknown'}。`;
      });

      function hrefFor(targetPage, extra = {}) {
        const search = new URLSearchParams({id: identityId, ...extra});
        const query = search.toString();
        return `${routeRoot}/cockpit/${targetPage}${query ? `?${query}` : ''}`;
      }

      async function fetchJson(url) {
        const response = await fetch(url, {headers: {'Accept': 'application/json'}});
        if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
        return response.json();
      }

      onMounted(async () => {
        document.title = `${pageTitle.value} · 储小策`;
        try {
          runtime.value = await fetchJson(runtimeUrl);
          document.title = `${pageTitle.value} · 储小策`;
        } catch (cause) {
          error.value = `看板元数据加载失败：${cause.message}`;
        } finally {
          loading.value = false;
        }
      });

      return {
        page, runtime, loading, error, pageTitle, tabs, gaps, metadataSummary,
        dashboardComponent: dashboard,
      };
    },
  });
  app.config.errorHandler = cause => console.error('cockpit component error', cause);
  app.mount('#app');
})();
