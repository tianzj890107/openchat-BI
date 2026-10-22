/**
 * 看板插入位置。内容在 insight-components/，这里只描述插在哪一层、哪条缝。
 */
window.DashboardInsights = [
  // 运营360整体分析 → 投标卡片底部（投标状态分布下方）
  // 组件 insight-components/bid-status-note
  {
    id: 'bid-status-note',
    embedPath: {
      segments: [
        {
          kind: 'tab',
          containerId: 'tab-container-zm9eyxne',
          tabId: 'tab-211tc4o0',
          templateId: '2112434004503347202',
        },
      ],
    },
    placement: { mode: 'in-card', anchorId: 'group-4croqift', position: 'bottom' },
  },
  // 运营360整体分析 → 报价节点联动展示模版顶部（头盔图下方、报价-异常项目分析上方）
  // 组件 insight-components/quote-summary
  {
    id: 'quote-summary',
    embedPath: {
      segments: [
        {
          kind: 'tab',
          containerId: 'tab-container-zm9eyxne',
          tabId: 'tab-211tc4o0',
          templateId: '2112434004503347202',
        },
        {
          kind: 'template',
          containerId: 'template-rjjcf4v1',
          templateId: '2112059463654490114',
        },
      ],
    },
    placement: { mode: 'insert', afterId: null },
  },
  // 运营360整体分析 → 投标节点联动展示模版顶部（头盔图下方、状态卡片上方）
  // 组件 insight-components/bid-summary
  {
    id: 'bid-summary',
    embedPath: {
      segments: [
        {
          kind: 'tab',
          containerId: 'tab-container-zm9eyxne',
          tabId: 'tab-211tc4o0',
          templateId: '2112434004503347202',
        },
        {
          kind: 'template',
          containerId: 'template-rjjcf4v1',
          templateId: '2112059751740260354',
        },
      ],
    },
    placement: { mode: 'insert', afterId: null },
  },
  // 运营360整体分析 → 订单接收节点联动展示模版顶部（头盔图下方、已签单订单结构上方）
  // 组件 insight-components/order-sign-summary
  {
    id: 'order-sign-summary',
    embedPath: {
      segments: [
        {
          kind: 'tab',
          containerId: 'tab-container-zm9eyxne',
          tabId: 'tab-211tc4o0',
          templateId: '2112434004503347202',
        },
        {
          kind: 'template',
          containerId: 'template-rjjcf4v1',
          templateId: '2112060211964461057',
        },
      ],
    },
    placement: { mode: 'insert', afterId: null },
  },
  // 穿透式问题分析 → 经营指标分组下方、头盔图上方
  // 组件 insight-components/sales-shipment-issues
  {
    id: 'sales-shipment-issues',
    embedPath: {
      segments: [
        {
          kind: 'tab',
          containerId: 'tab-container-zm9eyxne',
          tabId: 'tab-1suxx5hd',
          templateId: '2112061604959928321',
        },
      ],
    },
    placement: { mode: 'insert', afterId: 'group-dhflgwln' },
  },
  // 穿透式问题分析 → 商机获取节点联动展示模版顶部（销售额口径明细上方）
  // 组件 insight-components/opportunity-risk
  {
    id: 'opportunity-risk',
    embedPath: {
      segments: [
        {
          kind: 'tab',
          containerId: 'tab-container-zm9eyxne',
          tabId: 'tab-1suxx5hd',
          templateId: '2112061604959928321',
        },
        {
          kind: 'template',
          containerId: 'template-ryfsat5y',
          templateId: '2112062888320483329',
        },
      ],
    },
    placement: { mode: 'insert', afterId: null },
  },
  // 穿透式问题分析 → 商机获取节点联动展示模版 → 商机推进与覆盖缺口卡片底部
  // 组件 insight-components/opportunity-coverage-note
  {
    id: 'opportunity-coverage-note',
    embedPath: {
      segments: [
        {
          kind: 'tab',
          containerId: 'tab-container-zm9eyxne',
          tabId: 'tab-1suxx5hd',
          templateId: '2112061604959928321',
        },
        {
          kind: 'template',
          containerId: 'template-ryfsat5y',
          templateId: '2112062888320483329',
        },
      ],
    },
    placement: { mode: 'in-card', anchorId: 'group-9ypz7vwt', position: 'bottom' },
  },
  // 穿透式问题分析 → 订单接收节点联动展示模版顶部（受影响订单清单上方）
  // 组件 insight-components/order-risk-summary
  {
    id: 'order-risk-summary',
    embedPath: {
      segments: [
        {
          kind: 'tab',
          containerId: 'tab-container-zm9eyxne',
          tabId: 'tab-1suxx5hd',
          templateId: '2112061604959928321',
        },
        {
          kind: 'template',
          containerId: 'template-ryfsat5y',
          templateId: '2112064105591390209',
        },
      ],
    },
    placement: { mode: 'insert', afterId: null },
  },
  // 穿透式问题分析 → 发货节点联动展示模版顶部（风险结构与原因拆解上方）
  // 组件 insight-components/shipment-risk-summary
  {
    id: 'shipment-risk-summary',
    embedPath: {
      segments: [
        {
          kind: 'tab',
          containerId: 'tab-container-zm9eyxne',
          tabId: 'tab-1suxx5hd',
          templateId: '2112061604959928321',
        },
        {
          kind: 'template',
          containerId: 'template-ryfsat5y',
          templateId: '2112064144187375617',
        },
      ],
    },
    placement: { mode: 'insert', afterId: null },
  },
  // 穿透式问题分析 → 发货节点联动展示模版 → 风险结构与原因拆解卡片内（占比条下方）
  // 组件 insight-components/shipment-overdue-note
  {
    id: 'shipment-overdue-note',
    embedPath: {
      segments: [
        {
          kind: 'tab',
          containerId: 'tab-container-zm9eyxne',
          tabId: 'tab-1suxx5hd',
          templateId: '2112061604959928321',
        },
        {
          kind: 'template',
          containerId: 'template-ryfsat5y',
          templateId: '2112064144187375617',
        },
      ],
    },
    placement: { mode: 'in-card', anchorId: 'share-bar-zob5z1uu', position: 'bottom' },
  },
  // 穿透式问题分析 → 发货节点联动展示模版 → 风险结构与原因拆解卡片下方（客户与超期订单上方）
  // 组件 insight-components/shipment-cause-breakdown
  {
    id: 'shipment-cause-breakdown',
    embedPath: {
      segments: [
        {
          kind: 'tab',
          containerId: 'tab-container-zm9eyxne',
          tabId: 'tab-1suxx5hd',
          templateId: '2112061604959928321',
        },
        {
          kind: 'template',
          containerId: 'template-ryfsat5y',
          templateId: '2112064144187375617',
        },
      ],
    },
    placement: { mode: 'insert', afterId: 'share-bar-zob5z1uu' },
  },
  // 穿透式问题分析 → 发货节点联动展示模版 → 客户与超期订单卡片下方
  // 组件 insight-components/shipment-task-order
  {
    id: 'shipment-task-order',
    embedPath: {
      segments: [
        {
          kind: 'tab',
          containerId: 'tab-container-zm9eyxne',
          tabId: 'tab-1suxx5hd',
          templateId: '2112061604959928321',
        },
        {
          kind: 'template',
          containerId: 'template-ryfsat5y',
          templateId: '2112064144187375617',
        },
      ],
    },
    placement: { mode: 'insert', afterId: 'table-md1iftaj' },
  },
]
