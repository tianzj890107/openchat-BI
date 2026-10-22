/* V3 cockpit: metadata-driven ProUI dashboard with frozen demo data. */
(() => {
  'use strict';

  const root = document.querySelector('meta[name="app-root"]').content.replace(/\/$/, '');
  const routeRoot = location.pathname.replace(/\/cockpit(?:\/(?:home|overview|operations|analysis))?\/?$/, '');
  const runtimeUrl = `${root}/static/cockpit/metadata/runtime.json?v=proui-dashboard-v2`;
  const params = new URLSearchParams(location.search);
  const identityId = ['1', '2'].includes(params.get('id')) ? params.get('id') : '1';
  const PAGES = [
    {id: 'home', title: '首页'},
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

  const {createApp, ref, computed, onMounted, onBeforeUnmount, nextTick} = window.Vue;

  function homePageSpec(runtime) {
    const overview = runtime?.pages?.overview;
    const operations = runtime?.pages?.operations;
    if (!overview || !operations) return null;
    const kpiGroup = overview.components.find(component => (
      component.type === 'group' && Array.isArray(component.children)
    ));
    const kpiIds = new Set(kpiGroup?.children || []);
    const components = JSON.parse(JSON.stringify(
      overview.components.filter(component => component.id === kpiGroup?.id || kpiIds.has(component.id)),
    ));
    const processSource = operations.components.find(component => component.type === 'mini-cpgraph');
    if (processSource) {
      const process = JSON.parse(JSON.stringify(processSource));
      process.id = 'home-process';
      process.title = '运营全流程';
      process.position = {
        x: 0,
        y: (kpiGroup?.position?.y || 0) + (kpiGroup?.position?.h || 11) + 2,
        w: 120,
        h: 19,
      };
      process.graphConfig = {...process.graphConfig, graphTemplateSwitchRules: []};
      components.push(process);
    }
    for (const component of components) {
      delete component.templateSwitchTargets;
      delete component.selectionGroupDefault;
    }
    return {id: 'home', title: '首页', components};
  }

  function pageFromLocation() {
    const match = location.pathname.match(/\/cockpit\/(home|overview|operations|analysis)\/?$/);
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
      const nav = ref(null);
      const activeBarStyle = ref({width: '0px', transform: 'translateX(0px)'});

      const pageTitle = computed(() => PAGE_BY_ID[page.value]?.title || PAGES[0].title);
      const boardPage = computed(() => (
        page.value === 'home' ? homePageSpec(runtime.value) : runtime.value?.pages?.[page.value]
      ));
      const tabs = computed(() => PAGES.map(item => ({
        ...item,
        label: item.title,
        href: hrefFor(item.id),
        active: item.id === page.value,
      })));
      const gaps = computed(() => runtime.value?.gaps || []);
      const metadataSummary = computed(() => {
        if (page.value === 'home') {
          return `首页：${boardPage.value?.components?.length || 0} 个 ProUI 组件，复用全局经营指标与运营全流程元数据。`;
        }
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

      function updateActiveBar() {
        const navElement = nav.value;
        const active = navElement?.querySelector('.pro-tabs__item.is-active');
        if (!navElement || !active) {
          activeBarStyle.value = {width: '0px', transform: 'translateX(0px)'};
          return;
        }
        const scroll = navElement.closest('.pro-tabs__nav-scroll');
        if (scroll) {
          const left = active.offsetLeft;
          const right = left + active.offsetWidth;
          if (left < scroll.scrollLeft) scroll.scrollLeft = left;
          else if (right > scroll.scrollLeft + scroll.clientWidth) {
            scroll.scrollLeft = right - scroll.clientWidth;
          }
        }
        const navRect = navElement.getBoundingClientRect();
        const activeRect = active.getBoundingClientRect();
        activeBarStyle.value = {
          width: `${activeRect.width}px`,
          transform: `translateX(${activeRect.left - navRect.left}px)`,
        };
      }

      async function fetchJson(url) {
        const response = await fetch(url, {headers: {'Accept': 'application/json'}});
        if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
        return response.json();
      }

      onMounted(async () => {
        document.title = `${pageTitle.value} · 储小策`;
        window.addEventListener('resize', updateActiveBar);
        try {
          runtime.value = await fetchJson(runtimeUrl);
          document.title = `${pageTitle.value} · 储小策`;
          await nextTick();
          updateActiveBar();
        } catch (cause) {
          error.value = `看板元数据加载失败：${cause.message}`;
        } finally {
          loading.value = false;
        }
      });
      onBeforeUnmount(() => window.removeEventListener('resize', updateActiveBar));

      return {
        page, runtime, loading, error, pageTitle, boardPage, tabs, gaps, metadataSummary,
        nav, activeBarStyle,
        dashboardComponent: dashboard,
      };
    },
  });
  app.config.errorHandler = cause => console.error('cockpit component error', cause);
  app.mount('#app');
})();
