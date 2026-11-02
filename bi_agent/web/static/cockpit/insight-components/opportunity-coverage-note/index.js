/**
 * 商机推进与覆盖缺口说明。插在商机获取节点联动展示模版该卡片底部。
 * 只展示分析摘要与可追溯原因，不把查询事实逐项平铺或把样本行数当客户数。
 */
const { loadInsightStyle, registerInsightComponent, insightProps, useInsight } = window.InsightRuntime

loadInsightStyle(import.meta.url)

registerInsightComponent(
  'opportunity-coverage-note',
  Vue.defineComponent({
    name: 'OpportunityCoverageNote',
    props: insightProps,
    components: {InsightLoading: window.InsightRuntime.InsightLoading},
    emits: ['retry'],
    setup(props, { emit }) {
      return useInsight(props, emit)
    },
    template: `
      <section class="opportunity-coverage-note" aria-live="polite">
        <insight-loading v-if="!hasResult && status !== 'error'" kind="summary" :progress="progress" />
        <div v-if="hasResult || status === 'error'" class="insight-runtime-state">
          <div class="insight-runtime-state__row">
            <span>{{ stateText }}</span>
            <button v-if="status === 'error'" type="button" class="insight-runtime-retry" @click="retry">重试</button>
          </div>
        </div>
        <template v-if="hasResult">
          <div class="opportunity-coverage-note__summary" :title="summary">真实分析摘要：{{ summary }}</div>
          <details v-if="causes.length" class="opportunity-coverage-note__causes">
            <summary>查看 {{ causes.length }} 项原因与证据</summary>
            <div v-for="cause in causes" :key="cause.id" class="opportunity-coverage-note__cause">
              <span class="opportunity-coverage-note__em">{{ causeStatus(cause) }}</span>：
              <b>{{ cause.title }}</b>。{{ cause.description }}
            </div>
          </details>

        </template>
      </section>
    `,
  })
)
