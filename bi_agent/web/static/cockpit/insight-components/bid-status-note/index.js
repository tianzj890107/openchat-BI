/**
 * 投标状态说明。插在运营360整体分析「投标」卡片底部。
 */
import { loadInsightStyle, registerInsightComponent } from '../registry.js'

loadInsightStyle(import.meta.url)

registerInsightComponent(
  'bid-status-note',
  Vue.defineComponent({
    name: 'BidStatusNote',
    template: `
      <section class="bid-status-note">
        中标 3.7 GWh（13.0 亿元）= 已签单 1.4 GWh（5.0 亿元）+ 已中标未签单 2.3 GWh（8.0 亿元）；丢标 4.1 GWh（14.4 亿元）。中标率 49.0%（24/49 项）按项目数计算，弃标单列。
      </section>
    `,
  })
)
