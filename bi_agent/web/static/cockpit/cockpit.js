/* V3 cockpit: shell-free prototype layout with explicit metadata gaps. */
(() => {
  'use strict';

  const root = document.querySelector('meta[name="app-root"]').content.replace(/\/$/, '');
  const routeRoot = location.pathname.replace(/\/cockpit(?:\/(?:overview|operations|analysis))?\/?$/, '');
  const base = `${root}/api/cockpit`;
  const layoutUrl = `${root}/static/cockpit/layout/views.json?v=prototype-layout-v2`;
  const runtimeUrl = `${root}/static/cockpit/metadata/runtime.json?v=prototype-runtime-v1`;
  const params = new URLSearchParams(location.search);
  const identityId = ['1', '2'].includes(params.get('id')) ? params.get('id') : '1';
  const PAGES = {
    overview: {title: '全局经营看板'},
    operations: {title: '运营 360 整体分析'},
    analysis: {title: '穿透式问题分析'},
  };
  const OPERATIONS_STAGES = ['opportunity', 'guidance', 'quotation', 'technical', 'bid', 'order', 'shipment'];
  const ANALYSIS_STAGES = ['opportunity', 'bid', 'order', 'shipment'];
  const GAP_LABELS = {
    'landing-risk-card': '首页三项重点风险卡片',
    'process-node': '首页八节点风险链按钮',
    'annual-chart': '年度销售／出货图表',
    'helmet': '双环头盔图',
    'stage-tile': '运营节点入口卡',
    'cycle-benchmark': '平均周期与标杆对照区',
    'shipment-fulfillment': '发货订单履约率卡片',
    'ai-card': '风险／原因／建议卡片',
    'common-analysis': '共同问题分析说明',
    'special-analysis': '专项分析与改善卡片',
    'detail-chart': '细分图形',
  };

  if (!window.Vue) {
    document.getElementById('app').textContent = 'Vue 资源加载失败，请刷新页面。';
    return;
  }
  const {createApp, ref, computed, onMounted, onBeforeUnmount, nextTick, h} = window.Vue;

  function pageFromLocation() {
    const match = location.pathname.match(/\/cockpit\/(overview|operations|analysis)\/?$/);
    const declared = document.querySelector('meta[name="cockpit-page"]')?.content;
    return match?.[1] || (PAGES[declared] ? declared : 'overview');
  }

  const app = createApp({
    setup() {
      const page = ref(pageFromLocation());
      const metricParam = params.get('metric');
      const metric = ref(['sales', 'volume'].includes(metricParam) ? metricParam : '');
      const stageParam = params.get('stage');
      const stage = ref(page.value === 'analysis'
        ? (ANALYSIS_STAGES.includes(stageParam) ? stageParam : 'shipment')
        : (OPERATIONS_STAGES.includes(stageParam) ? stageParam : ''));
      const loading = ref(true);
      const error = ref('');
      const toast = ref('');
      const layout = ref(null);
      const runtime = ref(null);
      const mountedGapIds = ref(new Set());
      const metadataSummary = ref('');
      let toastTimer = null;
      let boardApps = [];

      const viewKey = computed(() => {
        if (page.value === 'overview') return metric.value ? `overview-${metric.value}` : 'overview';
        if (page.value === 'operations') return stage.value ? `operations-${stage.value}` : 'operations';
        return `analysis-${stage.value || 'shipment'}`;
      });
      const activeTab = computed(() => page.value === 'overview' ? (metric.value ? 'board' : 'home') : page.value);
      const pageTitle = computed(() => activeTab.value === 'home' ? '首页' : PAGES[page.value].title);
      const viewHtml = computed(() => layout.value?.views?.[viewKey.value] || layout.value?.views?.[page.value] || '');
      const gaps = computed(() => (layout.value?.gaps || []).filter(gap => gap.view === viewKey.value && !mountedGapIds.value.has(gap.id)));
      const tabs = computed(() => {
        const items = [
          {key: 'home', label: '首页', href: hrefFor('overview')},
          {key: 'board', label: '全局经营看板', href: hrefFor('overview', {metric: 'sales'})},
          {key: 'operations', label: '运营 360 整体分析', href: hrefFor('operations')},
          {key: 'analysis', label: '穿透式问题分析', href: hrefFor('analysis', {stage: 'shipment'})},
        ];
        return items.map(item => ({...item, active: item.key === activeTab.value}));
      });
      const groupedGaps = computed(() => {
        const groups = new Map();
        for (const gap of gaps.value) {
          const key = `${gap.key}\u0000${gap.reason}`;
          const current = groups.get(key);
          if (current) current.count += 1;
          else groups.set(key, {
            key, count: 1, reason: gap.reason,
            label: GAP_LABELS[gap.key] || gap.key,
          });
        }
        return [...groups.values()];
      });

      function notify(message, timeout = 3600) {
        toast.value = message;
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => { toast.value = ''; }, timeout);
      }

      async function fetchJson(url) {
        const response = await fetch(url, {headers: {'Accept': 'application/json'}});
        if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
        return response.json();
      }

      function hrefFor(targetPage, extra = {}) {
        const search = new URLSearchParams({id: identityId, ...extra});
        const query = search.toString();
        const suffix = query ? `?${query}` : '';
        return `${routeRoot}/cockpit/${targetPage}${suffix}`;
      }

      function go(targetPage, extra = {}) {
        location.assign(hrefFor(targetPage, extra));
      }

      function graphNodeId(payload) {
        const value = payload?.id || payload?.nodeId || payload?.node?.id || payload?.data?.id;
        return typeof value === 'string' ? value : '';
      }

      function openGraphNode(payload) {
        const stage = runtime.value?.nodeStages?.[graphNodeId(payload)];
        if (!stage) return;
        if (page.value === 'analysis') return go('analysis', {stage});
        return go('operations', {stage});
      }

      function handleAction(action) {
        if (!action) return;
        if (action === 'route:operations') return go('operations');
        if (action === 'route:overview') return go('overview');
        if (action.startsWith('route:analysis:')) {
          const target = action.slice('route:analysis:'.length);
          return go('analysis', {stage: ANALYSIS_STAGES.includes(target) ? target : 'shipment'});
        }
        if (action.startsWith('advice:')) {
          const target = action.slice('advice:'.length);
          return go('analysis', {stage: ANALYSIS_STAGES.includes(target) ? target : 'shipment', focus: 'advice'});
        }
        if (action.startsWith('metric:')) {
          const target = action.slice('metric:'.length);
          return go('overview', {metric: ['sales', 'volume'].includes(target) ? target : 'sales'});
        }
        if (action.startsWith('stage:')) {
          const target = action.slice('stage:'.length);
          if (!OPERATIONS_STAGES.includes(target)) return;
          if (page.value === 'operations') return go('operations', {stage: target});
          if (page.value === 'analysis' && ANALYSIS_STAGES.includes(target)) return go('analysis', {stage: target});
          return go('operations', {stage: target});
        }
        if (action === 'unavailable:monthly') return notify('交付元数据没有月度口径配置，当前只保留原型年度累计数据。');
        if (action === 'unavailable:payment') return notify('原型回款环节未交付对应的组件与数据配置。');
        notify('该操作没有交付对应的元数据或动作契约。');
      }

      function boardClick(event) {
        const target = event.target.closest('[data-action]');
        if (!target) return;
        event.preventDefault();
        handleAction(target.dataset.action);
      }

      function boardKeydown(event) {
        if (!['Enter', ' '].includes(event.key)) return;
        const target = event.target.closest('[data-action]');
        if (!target) return;
        event.preventDefault();
        handleAction(target.dataset.action);
      }

      function decorateBoard() {
        const board = document.querySelector('.cockpit-board');
        if (!board) return;
        const primaryRisk = board.querySelector('[data-gap="overview:landing-risk-card:0"]');
        if (primaryRisk && !primaryRisk.querySelector('.cockpit-gap-actions')) {
          const actions = document.createElement('div');
          actions.className = 'cockpit-risk-actions cockpit-gap-actions';
          actions.innerHTML = '<button type="button" class="cockpit-risk-primary" data-action="route:analysis:shipment">查看三级穿透</button><button type="button" class="cockpit-risk-secondary" data-action="advice:shipment">AI 改善建议</button>';
          primaryRisk.append(actions);
        }
        board.querySelectorAll('[data-gap]').forEach(element => {
          element.title = element.getAttribute('aria-label') || '交付元数据缺少该位置，按原型尺寸留空';
          if (element.dataset.action) {
            element.setAttribute('role', 'button');
            element.tabIndex = 0;
          }
        });
        board.querySelectorAll('[data-action]').forEach(element => {
          if (!element.getAttribute('role')) element.setAttribute('role', 'button');
          if (!element.hasAttribute('tabindex')) element.tabIndex = 0;
        });
        if (params.get('focus') === 'advice') {
          const advice = board.querySelector('[data-gap^="analysis-shipment:ai-card"]');
          if (advice) {
            advice.classList.add('cockpit-gap-focused');
            advice.setAttribute('aria-label', 'AI 改善建议：等待对应分析卡片组件和模型结果回填');
            requestAnimationFrame(() => advice.scrollIntoView({block: 'center', behavior: 'smooth'}));
          }
        }
      }

      function destroyBoardComponents() {
        for (const item of boardApps) {
          try { item.app.unmount(); } catch (cause) { console.warn('cockpit component unmount failed', cause); }
          item.element.replaceChildren();
        }
        boardApps = [];
        mountedGapIds.value = new Set();
      }

      function mountBoardComponents() {
        const board = document.querySelector('.cockpit-board');
        const configured = runtime.value?.mounts?.[viewKey.value] || {};
        const mounted = new Set();
        if (!board || !window.ProUIBi) return;
        for (const [gapId, spec] of Object.entries(configured)) {
          const entry = runtime.value.components?.[spec.bindingKey];
          const element = [...board.querySelectorAll('[data-gap]')].find(node => node.dataset.gap === gapId);
          if (!entry || !element) continue;
          const component = window.ProUIBi[entry.proComponent];
          if (!component) continue;
          const rect = element.getBoundingClientRect();
          const height = Math.max(180, Math.round(rect.height || 280));
          const metadata = JSON.parse(JSON.stringify(entry.component));
          metadata.showHeader = false;
          if (spec.graphActiveKey && metadata.graphConfig) {
            metadata.graphConfig.defaultActiveKey = spec.graphActiveKey;
          }
          element.classList.remove('prototype-gap');
          element.classList.add('cockpit-pro-mount');
          element.removeAttribute('data-gap');
          element.removeAttribute('role');
          element.setAttribute('data-pro-component', entry.proComponent);
          element.setAttribute('aria-label', entry.title || entry.proComponent);
          element.style.height = `${height}px`;
          element.style.minHeight = `${height}px`;
          element.replaceChildren();
          const componentApp = createApp({
            render: () => h(component, {
              component: metadata,
              data: entry.data,
              height: '100%',
              minHeight: height,
              onNodeClick: openGraphNode,
              onSectorClick: openGraphNode,
            }),
          });
          componentApp.config.errorHandler = cause => console.error(`cockpit ProUI error: ${entry.proComponent}`, cause);
          componentApp.mount(element);
          boardApps.push({app: componentApp, element});
          mounted.add(gapId);
        }
        mountedGapIds.value = mounted;
      }

      onMounted(async () => {
        document.title = `${pageTitle.value} · 储小策`;
        try {
          const [layoutData, runtimeData, metadata] = await Promise.all([
            fetchJson(layoutUrl),
            fetchJson(runtimeUrl),
            fetchJson(`${base}/metadata`).catch(() => null),
          ]);
          layout.value = layoutData;
          runtime.value = runtimeData;
          if (metadata) {
            const templateId = metadata.pages?.[page.value];
            const count = metadata.templates?.[templateId]?.components?.length || 0;
            metadataSummary.value = `交付页面根模板 ${templateId || '未映射'}，${count} 个根组件；源配置差异 ${metadata.gaps?.length || 0} 项。`;
          }
        } catch (cause) {
          error.value = `原型布局加载失败：${cause.message}`;
        } finally {
          loading.value = false;
        }
        await nextTick();
        decorateBoard();
        mountBoardComponents();
        const staticCount = Object.keys(runtime.value?.components || {}).length;
        const viewCount = mountedGapIds.value.size;
        const source = runtime.value?.source;
        metadataSummary.value = `${metadataSummary.value}${metadataSummary.value ? ' ' : ''}静态 ProUI 运行包 ${source?.branch || 'iba-demo'}@${(source?.commit || '').slice(0, 8) || 'unknown'}：${staticCount} 个组件，本页挂载 ${viewCount} 个。`;
      });

      onBeforeUnmount(() => {
        clearTimeout(toastTimer);
        destroyBoardComponents();
      });

      return {
        page, stage, metric, loading, error, toast, pageTitle, viewHtml,
        gaps, groupedGaps, metadataSummary, tabs, boardClick, boardKeydown,
      };
    },
  });
  app.config.errorHandler = cause => console.error('cockpit component error', cause);
  app.mount('#app');
})();
