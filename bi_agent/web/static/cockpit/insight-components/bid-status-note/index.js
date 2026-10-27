/**
 * 投标状态说明。插在运营360整体分析「投标」卡片底部。
 * 数值与结论均来自当前环节的真实分析结果和证据包。
 */
const { loadInsightStyle, registerInsightComponent, insightProps, useInsight } = window.InsightRuntime

loadInsightStyle(import.meta.url)

registerInsightComponent(
  'bid-status-note',
  Vue.defineComponent({
    name: 'BidStatusNote',
    props: insightProps,
    components: {InsightLoading: window.InsightRuntime.InsightLoading},
    emits: ['retry'],
    setup(props, { emit }) {
      return useInsight(props, emit)
    },
    template: `
      <section class="bid-status-note" aria-live="polite">
        <insight-loading v-if="!hasResult && status !== 'error'" kind="summary" :progress="progress" />
        <div v-if="hasResult || status === 'error'" class="insight-runtime-state">
          <div class="insight-runtime-state__row">
            <span>{{ stateText }}</span>
            <button v-if="status === 'error'" type="button" class="insight-runtime-retry" @click="retry">重试</button>
          </div>
        </div>
        <template v-if="hasResult">
          <span>中标 {{ factText('中标') }} · 丢标 {{ factText('丢标') }} · </span>
          <span class="bid-status-note__summary" :title="summary">{{ summary }}</span>
        </template>
      </section>
    `,
  })
)
