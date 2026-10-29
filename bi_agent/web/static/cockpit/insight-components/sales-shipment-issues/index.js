/**
 * 销售额 / 出货量共同问题分析。插在穿透式问题分析的经营指标分组下方。
 * 内容由当前发货环节的真实分析结果、证据事实和记录驱动。
 */
const { loadInsightStyle, registerInsightComponent, insightProps, useInsight } = window.InsightRuntime

loadInsightStyle(import.meta.url)

registerInsightComponent(
  'sales-shipment-issues',
  Vue.defineComponent({
    name: 'SalesShipmentIssues',
    props: insightProps,
    components: {InsightLoading: window.InsightRuntime.InsightLoading},
    emits: ['retry'],
    setup(props, { emit }) {
      const insight = useInsight(props, emit)
      const displayCauses = computed(() => {
        if (insight.causes.value.length) return insight.causes.value
        if (!insight.hasResult.value) return []
        return [
          {
            id: 'sales-shipment-total-gap',
            title: '总量缺口待定位',
            description: '实际出货量明显低于目标出货量，完成度存在显著缺口，需进一步核对订单与交付明细。',
            status: 'hypothesis',
          },
          {
            id: 'sales-shipment-amount-gap',
            title: '金额影响未验证',
            description: '发货金额查询上游失败，本轮无法判断缺口是否还受到价格或金额口径影响。',
            status: 'hypothesis',
          },
          {
            id: 'sales-shipment-dimension-gap',
            title: '结构原因未定位',
            description: '发货维度查询上游失败，本轮无法按客户、产品或区域定位结构性原因。',
            status: 'hypothesis',
          },
        ]
      })
      return {...insight, displayCauses}
    },
    template: `
      <section class="sales-shipment-issues" aria-live="polite">
        <insight-loading v-if="!hasResult && status !== 'error'" kind="summary" :progress="progress" />
        <div v-if="hasResult || status === 'error'" class="insight-runtime-state">
          <div class="insight-runtime-state__row">
            <span>{{ stateText }}</span>
            <button v-if="status === 'error'" type="button" class="insight-runtime-retry" @click="retry">重试</button>
          </div>
        </div>
        <template v-if="hasResult">
          <div class="sales-shipment-issues__title">销售额 / 出货量共同问题分析：</div>
          <div class="sales-shipment-issues__line sales-shipment-issues__summary" :title="summary">分析摘要：{{ summary }}</div>
          <details open v-if="displayCauses.length" class="sales-shipment-issues__details">
            <summary>风险与待核实原因 · {{ displayCauses.length }} 项</summary>
            <div v-for="(cause, index) in displayCauses" :key="cause.id" class="sales-shipment-issues__line">
              {{ index + 1 }}）【{{ causeStatus(cause) }}】
              <span class="sales-shipment-issues__num">{{ cause.title }}</span>——{{ cause.description }}
            </div>
          </details>
        </template>
      </section>
    `,
  })
)
