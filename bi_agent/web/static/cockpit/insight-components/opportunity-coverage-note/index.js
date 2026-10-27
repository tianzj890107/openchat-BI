/**
 * 商机推进与覆盖缺口说明。插在商机获取节点联动展示模版该卡片底部。
 * 状态分布由记录聚合，结论与标签由真实分析结果驱动。
 */
const { loadInsightStyle, registerInsightComponent, insightProps, useInsight } = window.InsightRuntime

const { computed } = window.Vue

loadInsightStyle(import.meta.url)

registerInsightComponent(
  'opportunity-coverage-note',
  Vue.defineComponent({
    name: 'OpportunityCoverageNote',
    props: insightProps,
    components: {InsightLoading: window.InsightRuntime.InsightLoading},
    emits: ['retry'],
    setup(props, { emit }) {
      const insight = useInsight(props, emit)
      const statusCounts = computed(() => insight.records.value.reduce((counts, record) => {
        const status = record.status || '未分类'
        counts[status] = (counts[status] || 0) + 1
        return counts
      }, {}))
      return { ...insight, statusCounts }
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
          <div class="opportunity-coverage-note__status">
            当前商机快照共 {{ records.length }} 条记录：
            <span class="opportunity-coverage-note__em">
              {{ Object.entries(statusCounts).map(([key, value]) => key + ' ' + value + ' 条').join('，') || '状态未提供' }}
            </span>。
          </div>
          <details v-if="causes.length" class="opportunity-coverage-note__causes">
            <summary>查看 {{ causes.length }} 项原因与证据</summary>
            <div v-for="cause in causes" :key="cause.id" class="opportunity-coverage-note__cause">
              <span class="opportunity-coverage-note__em">{{ causeStatus(cause) }}</span>：
              <b>{{ cause.title }}</b>。{{ cause.description }}
            </div>
          </details>
          <div class="opportunity-coverage-note__tags">
            <span v-for="item in facts" :key="item.id" class="opportunity-coverage-note__tag">
              {{ item.label }} {{ metricValue(item) }}
            </span>
          </div>
        </template>
      </section>
    `,
  })
)
