/**
 * 销售额 / 出货量共同问题分析。插在穿透式问题分析的经营指标分组下方。
 * 内容由当前发货环节的真实分析结果、证据事实和记录驱动。
 */
const { loadInsightStyle, registerInsightComponent, insightProps, useInsight } = window.InsightRuntime
const { computed } = window.Vue

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
      // The card may only render causes delivered by the analysis contract.
      // Missing causes stay explicit through the summary/limitations instead of
      // being filled with demo-time placeholder findings.
      const displayCauses = computed(() => insight.causes.value)
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
