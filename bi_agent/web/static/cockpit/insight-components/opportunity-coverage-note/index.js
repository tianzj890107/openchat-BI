/**
 * 商机推进与覆盖缺口说明。插在商机获取节点联动展示模版该卡片底部。
 */
import { loadInsightStyle, registerInsightComponent } from '../registry.js'

loadInsightStyle(import.meta.url)

registerInsightComponent(
  'opportunity-coverage-note',
  Vue.defineComponent({
    name: 'OpportunityCoverageNote',
    template: `
      <section class="opportunity-coverage-note">
        <div>
          PACK 商机 46 条中，
          <span class="opportunity-coverage-note__em">28 条已进入投标（60.9%，28/46）</span>
          ——其中已签单 6 条、投标中 22 条；
          <span class="opportunity-coverage-note__em">18 条未进入投标（39.1%，18/46）</span>
          ——其中方案引导 11 条、商机获取 7 条，且这 18 条全部属于战略客户；另有 7 家战略客户尚无商机。
        </div>
        <div>
          未投标的 18 条预计金额 39.6 亿元，占 PACK 商机预测口径 44%。其中 11 条卡在方案引导超过 14 天，7 条仍停在商机获取；若本周不能推进到投标，季度覆盖缺口还会再扩大约 12.4 亿元。建议优先跟进金额前五的战略客户，并补齐尚无商机的 7 家客户覆盖。
        </div>
        <div class="opportunity-coverage-note__tags">
          <span class="opportunity-coverage-note__tag">13 家有商机未投标</span>
          <span class="opportunity-coverage-note__tag">7 家无商机</span>
          <span class="opportunity-coverage-note__tag">11 条超 14 天</span>
          <span class="opportunity-coverage-note__tag">缺口约 12.4 亿元</span>
        </div>
      </section>
    `,
  })
)
