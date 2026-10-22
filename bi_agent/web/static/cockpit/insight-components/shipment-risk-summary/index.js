/**
 * 发货风险概况。插在发货节点联动展示模版顶部。
 * 发货事实来自证据包，风险、原因和建议来自真实分析结果。
 */
const { loadInsightStyle, registerInsightComponent, insightProps, useInsight } = window.InsightRuntime

loadInsightStyle(import.meta.url)

registerInsightComponent(
  'shipment-risk-summary',
  Vue.defineComponent({
    name: 'ShipmentRiskSummary',
    props: insightProps,
    emits: ['retry'],
    setup(props, { emit }) {
      const insight = useInsight(props, emit)
      const focusTasks = () => document.querySelector('.shipment-task-order')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      return { ...insight, focusTasks }
    },
    template: `
      <section class="shipment-risk-summary" aria-live="polite">
        <div class="insight-runtime-state">
          <div class="insight-runtime-state__row">
            <span>{{ stateText }}</span>
            <button v-if="status === 'error'" type="button" class="insight-runtime-retry" @click="retry">重试</button>
          </div>
        </div>
        <template v-if="hasResult">
          <article class="shipment-risk-summary__card">
            <div class="shipment-risk-summary__head">
              <strong class="shipment-risk-summary__title">发货风险概况</strong>
              <span class="shipment-risk-summary__aside">{{ contextLine }}</span>
            </div>
            <div v-for="item in facts" :key="item.id">
              {{ item.label }}：
              <span :class="item.label.includes('超期') ? 'shipment-risk-summary__red' : 'shipment-risk-summary__green'">
                {{ metricValue(item) }}
              </span>
            </div>
            <div class="shipment-risk-summary__note">真实分析摘要：{{ summary }}</div>
          </article>

          <article class="shipment-risk-summary__panel shipment-risk-summary__panel--risk">
            <div class="shipment-risk-summary__title">
              <span class="shipment-risk-summary__mark--risk">【风险】</span>
              超期订单集中在 {{ records.length }} 条证据记录
            </div>
            <div v-for="record in records.slice(0, 5)" :key="record.id">
              <span class="shipment-risk-summary__num--risk">{{ record.customer }} · {{ record.department }}：</span>
              {{ record.id }}，{{ record.amount }} 亿元，超期 {{ record.overdueDays }} 天。
            </div>
          </article>

          <article class="shipment-risk-summary__panel shipment-risk-summary__panel--cause">
            <div class="shipment-risk-summary__title">
              <span class="shipment-risk-summary__mark--cause">【原因】</span>
              记录支持 {{ causes.filter(item => item.status === 'supported').length }} 项、待核实
              {{ causes.filter(item => item.status !== 'supported').length }} 项
            </div>
            <div v-for="cause in causes" :key="cause.id">
              <span class="shipment-risk-summary__num--cause">{{ causeMeta(cause) }}：</span>{{ cause.title }}。{{ cause.description }}
            </div>
          </article>

          <article class="shipment-risk-summary__panel shipment-risk-summary__panel--suggest">
            <div class="shipment-risk-summary__head">
              <div class="shipment-risk-summary__title">
                <span class="shipment-risk-summary__mark--suggest">【建议】</span>
                按证据链形成可验收动作
              </div>
              <button type="button" class="shipment-risk-summary__draft" @click="focusTasks">查看任务令</button>
            </div>
            <div v-for="action in openRecommendations" :key="action.id">
              <span class="shipment-risk-summary__num--suggest">{{ action.ownerRole }}：</span>
              {{ action.action }}（验收：{{ action.acceptance }}）
            </div>
          </article>
        </template>
      </section>
    `,
  })
)
