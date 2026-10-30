/**
 * 报价概况。插在报价节点联动展示模版顶部。
 * 阶段数值来自服务端证据事实，分析结论来自当前报价环节的模型结果。
 */
const { loadInsightStyle, registerInsightComponent, insightProps, useInsight } = window.InsightRuntime

const { quotationStatus } = await import(new URL('./status.js' + new URL(import.meta.url).search, import.meta.url))

loadInsightStyle(import.meta.url)

registerInsightComponent(
  'quote-summary',
  Vue.defineComponent({
    name: 'QuoteSummary',
    props: insightProps,
    components: {InsightLoading: window.InsightRuntime.InsightLoading},
    emits: ['retry'],
    setup(props, { emit }) {
      const insight = useInsight(props, emit)
      const statusData = Vue.computed(() => quotationStatus(insight.records.value))
      const volume = value => value === null || value === undefined ? '未返回' : `${value} GWh`
      return {...insight, statusData, volume}
    },
    template: `
      <section class="quote-summary" aria-live="polite">
        <insight-loading v-if="!hasResult && status !== 'error'" kind="summary" :progress="progress" />
        <div v-if="hasResult || status === 'error'" class="insight-runtime-state">
          <div class="insight-runtime-state__row">
            <span>{{ stateText }}</span>
            <button v-if="status === 'error'" type="button" class="insight-runtime-retry" @click="retry">重试</button>
          </div>
        </div>
        <template v-if="hasResult">
          <div class="quote-summary__head">
            <strong class="quote-summary__title">报价概况</strong>
            <span class="quote-summary__aside">{{ contextLine }}</span>
          </div>
          <div>
            已返回状态合计 {{ volume(statusData.total) }} ·
            <span class="quote-summary__green">已完成 {{ volume(statusData.completed) }}</span>
            · 未完成 {{ volume(statusData.pending) }}
          </div>
          <div>
            正常完成 {{ volume(statusData.values.normal_completed) }} ·
            逾期完成 {{ volume(statusData.values.overdue_completed) }}
          </div>
          <div>
            <span class="quote-summary__red">逾期未完成 {{ volume(statusData.values.overdue_uncompleted) }}</span> ·
            临期未完成 {{ volume(statusData.values.imminent_uncompleted) }} ·
            正常未完成 {{ volume(statusData.values.normal_uncompleted) }}
          </div>
          <div class="quote-summary__note" :title="summary">真实分析摘要：{{ summary }}</div>
        </template>
      </section>
    `,
  })
)
