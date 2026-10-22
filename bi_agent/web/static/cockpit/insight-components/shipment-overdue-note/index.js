/**
 * 超期口径说明。插在发货节点「风险结构与原因拆解」卡片内。
 */
import { loadInsightStyle, registerInsightComponent } from '../registry.js'

loadInsightStyle(import.meta.url)

registerInsightComponent(
  'shipment-overdue-note',
  Vue.defineComponent({
    name: 'ShipmentOverdueNote',
    template: `
      <section class="shipment-overdue-note">
        订未发 39.6 亿元 / 11.3 GWh = 正常订未发 15.3 亿元 / 4.4 GWh + 超期订未发 24.3 亿元 / 6.9 GWh。本页只将已超期订单列为发货风险；订单取消和变更影响另见销售额口径的订单环，不重复加进本页超期金额。
      </section>
    `,
  })
)
