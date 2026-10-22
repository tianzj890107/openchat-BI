/**
 * 商机获取的风险、原因、建议。插在商机获取节点联动展示模版顶部。
 * 三块内容分别消费真实分析的摘要、原因和建议，不再保留原型静态数字。
 */
import { loadInsightStyle, registerInsightComponent } from '../registry.js'
import { insightProps, useInsight } from '../shared.js'

loadInsightStyle(import.meta.url)

registerInsightComponent(
  'opportunity-risk',
  Vue.defineComponent({
    name: 'OpportunityRisk',
    props: insightProps,
    emits: ['retry'],
    setup(props, { emit }) {
      return useInsight(props, emit)
    },
    template: `
      <section class="opportunity-risk" aria-live="polite">
        <div class="insight-runtime-state">
          <div class="insight-runtime-state__row">
            <span>{{ stateText }}</span>
            <button v-if="status === 'error'" type="button" class="insight-runtime-retry" @click="retry">重试</button>
          </div>
        </div>
        <template v-if="hasResult">
          <article class="opportunity-risk__card">
            <div class="opportunity-risk__title">
              <span class="opportunity-risk__mark opportunity-risk__mark--risk">【风险】</span>
              当前商机环节的真实分析摘要
            </div>
            <div>{{ summary }}</div>
            <div v-for="(item, index) in facts" :key="item.id" class="opportunity-risk__row">
              <span class="opportunity-risk__tag opportunity-risk__tag--risk">风险{{ index + 1 }}</span>
              <span>
                {{ item.label }}：
                <span class="opportunity-risk__num opportunity-risk__num--risk">{{ metricValue(item) }}</span>。
                {{ item.definition }}
              </span>
            </div>
          </article>

          <article class="opportunity-risk__card">
            <div class="opportunity-risk__title">
              <span class="opportunity-risk__mark opportunity-risk__mark--cause">【原因】</span>
              模型基于当前证据识别 {{ causes.length }} 项原因
            </div>
            <div v-for="(cause, index) in causes" :key="cause.id" class="opportunity-risk__row">
              <span class="opportunity-risk__tag opportunity-risk__tag--cause">原因{{ index + 1 }}</span>
              <span>
                <span class="opportunity-risk__num opportunity-risk__num--cause">{{ cause.title }}（{{ causeMeta(cause) }}）</span>：
                {{ cause.description }}
              </span>
            </div>
          </article>

          <article class="opportunity-risk__card">
            <div class="opportunity-risk__head">
              <div class="opportunity-risk__title">
                <span class="opportunity-risk__mark opportunity-risk__mark--suggest">【建议】</span>
                按证据链关闭商机缺口
              </div>
              <button type="button" class="opportunity-risk__draft">生成任务令草稿</button>
            </div>
            <div v-for="(item, index) in openRecommendations" :key="item.id" class="opportunity-risk__item">
              <span class="opportunity-risk__index">{{ index + 1 }}</span>
              <span class="opportunity-risk__item-text">{{ item.action }}</span>
              <span class="opportunity-risk__owner">{{ item.ownerRole }}</span>
              <span class="opportunity-risk__time">验收：{{ item.acceptance }}</span>
              <button type="button" class="opportunity-risk__close" aria-label="关闭这条建议" @click="dismissRecommendation(item.id)">×</button>
            </div>
            <div class="opportunity-risk__foot">
              <div>证据范围：{{ contextLine }}；{{ records.length }} 条记录、{{ evidenceCount }} 条证据。</div>
              <div v-for="(limitation, index) in limitations" :key="'limit-' + index">限制 {{ index + 1 }}：{{ limitation }}</div>
            </div>
          </article>

          <article class="opportunity-risk__card opportunity-risk__brief">
            <div>
              当前只展示服务端证据包与模型结果：{{ summary }}
            </div>
          </article>
        </template>
      </section>
    `,
  })
)
