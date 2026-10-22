/**
 * 商机推进与覆盖缺口说明。插在商机获取节点联动展示模版该卡片底部。
 * 状态分布由记录聚合，结论与标签由真实分析结果驱动。
 */
import { loadInsightStyle, registerInsightComponent } from '../registry.js'
import { insightProps, useInsight } from '../shared.js'

const { computed } = window.Vue

loadInsightStyle(import.meta.url)

registerInsightComponent(
  'opportunity-coverage-note',
  Vue.defineComponent({
    name: 'OpportunityCoverageNote',
    props: insightProps,
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
        <div class="insight-runtime-state">
          <div class="insight-runtime-state__row">
            <span>{{ stateText }}</span>
            <button v-if="status === 'error'" type="button" class="insight-runtime-retry" @click="retry">重试</button>
          </div>
        </div>
        <template v-if="hasResult">
          <div>
            当前商机快照共 {{ records.length }} 条记录：
            <span class="opportunity-coverage-note__em">
              {{ Object.entries(statusCounts).map(([key, value]) => key + ' ' + value + ' 条').join('，') || '状态未提供' }}
            </span>。
            下列缺口与推进结论均来自 {{ contextLine }} 的真实分析。
          </div>
          <div>真实分析摘要：{{ summary }}</div>
          <div v-for="cause in causes" :key="cause.id">
            <span class="opportunity-coverage-note__em">{{ causeStatus(cause) }}</span>：
            {{ cause.title }}。{{ cause.description }}
          </div>
          <div class="opportunity-coverage-note__tags">
            <span v-for="item in facts" :key="item.id" class="opportunity-coverage-note__tag">
              {{ item.label }} {{ metricValue(item) }}
            </span>
            <span v-for="cause in causes" :key="'tag-' + cause.id" class="opportunity-coverage-note__tag">
              {{ cause.title }}
            </span>
          </div>
        </template>
      </section>
    `,
  })
)
