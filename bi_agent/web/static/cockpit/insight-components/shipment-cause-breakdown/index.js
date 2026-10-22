/**
 * 主因与细分根因。插在发货节点「风险结构与原因拆解」卡片下方。
 * 主因按证据记录中的 cause 聚合，金额和超期天数来自同一条记录。
 */
import { loadInsightStyle, registerInsightComponent } from '../registry.js'
import { insightProps, sumBy, round, useInsight } from '../shared.js'

const { computed } = window.Vue

loadInsightStyle(import.meta.url)

registerInsightComponent(
  'shipment-cause-breakdown',
  Vue.defineComponent({
    name: 'ShipmentCauseBreakdown',
    props: insightProps,
    emits: ['retry'],
    setup(props, { emit }) {
      const insight = useInsight(props, emit)
      const groups = computed(() => {
        const grouped = new Map()
        insight.records.value.forEach(record => {
          const name = record.cause || '未分类'
          const item = grouped.get(name) || {name, amount: 0, count: 0, maxOverdue: 0, items: []}
          item.amount += Number(record.amount) || 0
          item.count += 1
          item.maxOverdue = Math.max(item.maxOverdue, Number(record.overdueDays) || 0)
          item.items.push(record)
          grouped.set(name, item)
        })
        const values = [...grouped.values()].sort((a, b) => b.amount - a.amount)
        if (values.length) return values
        return insight.causes.value.map(cause => ({name: cause.title, amount: 0, count: 0, maxOverdue: 0, items: [], cause}))
      })
      const totalAmount = computed(() => sumBy(groups.value, item => item.amount))
      const share = value => totalAmount.value ? `${round(value / totalAmount.value * 100, 1)}%` : '—'
      return { ...insight, groups, totalAmount, share, round }
    },
    template: `
      <section class="shipment-cause-breakdown" aria-live="polite">
        <div class="insight-runtime-state">
          <div class="insight-runtime-state__row">
            <span>{{ stateText }}</span>
            <button v-if="status === 'error'" type="button" class="insight-runtime-retry" @click="retry">重试</button>
          </div>
        </div>
        <template v-if="hasResult">
          <div class="shipment-cause-breakdown__title">按证据记录聚合的主因与细分根因</div>
          <div class="shipment-cause-breakdown__grid">
            <article v-for="group in groups" :key="group.name" class="shipment-cause-breakdown__item">
              <div class="shipment-cause-breakdown__item-title">
                {{ group.name }} ·
                <span class="shipment-cause-breakdown__metric">
                  {{ group.count }} 单 / {{ round(group.amount, 1) }} 亿元 / {{ share(group.amount) }}
                </span>
              </div>
              <ul v-if="group.items.length" class="shipment-cause-breakdown__list">
                <li v-for="item in group.items" :key="item.id">
                  {{ item.id }} · {{ item.customer }} · {{ item.evidence }}：
                  <span class="shipment-cause-breakdown__metric">{{ item.amount }} 亿元 / 超期 {{ item.overdueDays }} 天</span>
                </li>
              </ul>
              <div v-else class="insight-runtime-empty">{{ group.cause ? group.cause.description : '记录级主因未提供' }}</div>
            </article>
          </div>
          <div class="shipment-cause-breakdown__foot">
            证据记录金额合计 {{ round(totalAmount, 1) }} 亿元，共 {{ records.length }} 单。
            真实分析摘要：{{ summary }}
          </div>
        </template>
      </section>
    `,
  })
)
