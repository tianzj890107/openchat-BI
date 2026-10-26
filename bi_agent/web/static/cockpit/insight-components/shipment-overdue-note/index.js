/**
 * 超期未发口径说明。插在发货节点「风险结构」卡片底部。
 * 数量与金额来自发货环节真实证据事实，判断来自同一份真实分析结果。
 */
const { loadInsightStyle, registerInsightComponent, insightProps, useInsight } = window.InsightRuntime

loadInsightStyle(import.meta.url)

registerInsightComponent(
  'shipment-overdue-note',
  Vue.defineComponent({
    name: 'ShipmentOverdueNote',
    props: insightProps,
    components: {InsightLoading: window.InsightRuntime.InsightLoading},
    emits: ['retry'],
    setup(props, { emit }) {
      return useInsight(props, emit)
    },
    template: `
      <section class="shipment-overdue-note" aria-live="polite">
        <insight-loading v-if="!hasResult && status !== 'error'" kind="summary" :progress="progress" />
        <div v-if="hasResult || status === 'error'" class="insight-runtime-state">
          <div class="insight-runtime-state__row">
            <span>{{ stateText }}</span>
            <button v-if="status === 'error'" type="button" class="insight-runtime-retry" @click="retry">重试</button>
          </div>
        </div>
        <template v-if="hasResult">
          正常订未发 {{ factText('正常订未发') }}；超期订未发 {{ factText('超期订未发') }}；
          超期未发金额 {{ factText('超期未发金额') }}。{{ summary }}
        </template>
      </section>
    `,
  })
)
