/**
 * 订单签单概况。插在订单接收节点联动展示模版顶部。
 * 电量取自订单环节证据事实，摘要取自当前订单环节的真实分析结果。
 */
const { loadInsightStyle, registerInsightComponent, insightProps, useInsight } = window.InsightRuntime

loadInsightStyle(import.meta.url)

registerInsightComponent(
  'order-sign-summary',
  Vue.defineComponent({
    name: 'OrderSignSummary',
    props: insightProps,
    components: {InsightLoading: window.InsightRuntime.InsightLoading},
    emits: ['retry'],
    setup(props, { emit }) {
      return useInsight(props, emit)
    },
    template: `
      <section class="order-sign-summary" aria-live="polite">
        <insight-loading v-if="!hasResult && status !== 'error'" kind="summary" :progress="progress" />
        <div v-if="hasResult || status === 'error'" class="insight-runtime-state">
          <div class="insight-runtime-state__row">
            <span>{{ stateText }}</span>
            <button v-if="status === 'error'" type="button" class="insight-runtime-retry" @click="retry">重试</button>
          </div>
        </div>
        <template v-if="hasResult">
          <div class="order-sign-summary__head">
            <strong class="order-sign-summary__title">订单签单概况</strong>
            <span class="order-sign-summary__aside">{{ contextLine }} · 事实合计 {{ sumFacts(null, 'GWh') }} GWh</span>
          </div>
          <div>
            <span class="order-sign-summary__green">有效订单 {{ factText('有效订单') }}</span>；
            <span class="order-sign-summary__orange">已中标未签单 {{ factText('已中标未签单') }}</span>。
          </div>
          <div v-for="item in facts" :key="item.id">
            {{ item.label }}：{{ metricValue(item) }}。
          </div>
          <div class="order-sign-summary__aside order-sign-summary__summary" :title="summary">真实分析摘要：{{ summary }}</div>
        </template>
      </section>
    `,
  })
)
