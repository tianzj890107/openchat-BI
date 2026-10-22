/**
 * 销售额 / 出货量共同问题分析。插在穿透式问题分析的经营指标分组下方。
 * 内容由当前发货环节的真实分析结果、证据事实和记录驱动。
 */
import { loadInsightStyle, registerInsightComponent } from '../registry.js'
import { insightProps, useInsight } from '../shared.js'

loadInsightStyle(import.meta.url)

registerInsightComponent(
  'sales-shipment-issues',
  Vue.defineComponent({
    name: 'SalesShipmentIssues',
    props: insightProps,
    emits: ['retry'],
    setup(props, { emit }) {
      return useInsight(props, emit)
    },
    template: `
      <section class="sales-shipment-issues" aria-live="polite">
        <div class="insight-runtime-state">
          <div class="insight-runtime-state__row">
            <span>{{ stateText }}</span>
            <button v-if="status === 'error'" type="button" class="insight-runtime-retry" @click="retry">重试</button>
          </div>
        </div>
        <template v-if="hasResult">
          <div class="sales-shipment-issues__title">销售额 / 出货量共同问题分析：</div>
          <div>
            当前证据范围：{{ contextLine }}；共 {{ facts.length }} 项阶段事实、{{ records.length }} 条记录、
            {{ evidenceCount }} 条证据。
          </div>
          <div class="sales-shipment-issues__line">真实分析摘要：{{ summary }}</div>
          <div v-for="(item, index) in facts" :key="item.id" class="sales-shipment-issues__line">
            {{ index + 1 }}）【{{ item.label }}】
            <span class="sales-shipment-issues__num">{{ metricValue(item) }}</span>
            ——{{ item.definition }}
          </div>
          <div v-for="(cause, index) in causes" :key="cause.id" class="sales-shipment-issues__line">
            {{ facts.length + index + 1 }}）【{{ causeStatus(cause) }}】
            <span class="sales-shipment-issues__num">{{ cause.title }}</span>——{{ cause.description }}
          </div>
        </template>
      </section>
    `,
  })
)
