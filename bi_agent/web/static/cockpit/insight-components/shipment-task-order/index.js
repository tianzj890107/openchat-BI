/**
 * 发货风险解决任务令。插在发货节点「客户与超期订单」卡片下方。
 * 任务令由真实分析返回的建议、责任角色和验收标准生成。
 */
const { loadInsightStyle, registerInsightComponent, insightProps, useInsight } = window.InsightRuntime

loadInsightStyle(import.meta.url)

registerInsightComponent(
  'shipment-task-order',
  Vue.defineComponent({
    name: 'ShipmentTaskOrder',
    props: insightProps,
    components: {InsightLoading: window.InsightRuntime.InsightLoading},
    emits: ['retry'],
    setup(props, { emit }) {
      const insight = useInsight(props, emit)
      const linkedCauseTitles = action => {
        const ids = new Set(action.causeIds || [])
        return insight.causes.value.filter(cause => ids.has(cause.id)).map(cause => cause.title).join('；')
      }
      return { ...insight, linkedCauseTitles }
    },
    template: `
      <section class="shipment-task-order" aria-live="polite">
        <insight-loading v-if="!hasResult && status !== 'error'" kind="task" :progress="progress" />
        <div v-if="hasResult || status === 'error'" class="insight-runtime-state">
          <div class="insight-runtime-state__row">
            <span>{{ stateText }}</span>
            <button v-if="status === 'error'" type="button" class="insight-runtime-retry" @click="retry">重试</button>
          </div>
        </div>
        <template v-if="hasResult">
          <div class="shipment-task-order__head">
            <span class="shipment-task-order__step">3</span>
            <strong class="shipment-task-order__title">出货风险解决任务令</strong>
            <span class="shipment-task-order__sub">责任角色、目标和验收来自当前分析</span>
          </div>
          <div class="shipment-task-order__summary" :title="summary">{{ summary }}</div>
          <div v-if="!openRecommendations.length" class="insight-runtime-empty">尚无经过证据校验的措施，需先核实原因与责任口径。</div>
          <article v-for="(item, index) in openRecommendations" :key="item.id" class="shipment-task-order__task">
            <div class="shipment-task-order__task-head">
              <span class="shipment-task-order__no">{{ index + 1 }}</span>
              <strong class="shipment-task-order__task-title">{{ item.action }}</strong>
              <span class="shipment-task-order__deadline">{{ deadlineText(item) }}</span>
            </div>
            <div class="shipment-task-order__meta">
              <span class="shipment-task-order__owner">{{ item.ownerRole || '责任角色未提供' }}</span>
              <span class="shipment-task-order__acceptance">验收：{{ item.acceptance }}</span>
              <button v-if="hasRecommendationDetail(item)" type="button" class="shipment-task-order__detail-toggle"
                      :aria-expanded="String(isRecommendationExpanded(item.id))"
                      @click="toggleRecommendationDetail(item.id)">
                {{ isRecommendationExpanded(item.id) ? '收起' : '查看详情' }}
              </button>
            </div>
            <div v-if="isRecommendationExpanded(item.id)" class="shipment-task-order__detail">
              <div v-if="linkedCauseTitles(item)"><span class="shipment-task-order__label">关联原因：</span>{{ linkedCauseTitles(item) }}</div>
              <div>{{ recommendationDetail(item) }}</div>
            </div>
          </article>
          <div class="shipment-task-order__foot">
            <span class="shipment-task-order__hint">依据 {{ evidenceCount }} 条证据生成，限制：{{ limitations[0] || '未提供' }}</span>
          </div>
        </template>
      </section>
    `,
  })
)
