/**
 * 销售额 / 出货量共同问题分析。插在穿透式问题分析的经营指标分组下方。
 */
import { loadInsightStyle, registerInsightComponent } from '../registry.js'

loadInsightStyle(import.meta.url)

registerInsightComponent(
  'sales-shipment-issues',
  Vue.defineComponent({
    name: 'SalesShipmentIssues',
    template: `
      <section class="sales-shipment-issues">
        <div class="sales-shipment-issues__title">销售额 / 出货量共同问题分析：</div>
        <div>
          销售额 <span class="sales-shipment-issues__num">191.4 亿元</span>，达成率
          <span class="sales-shipment-issues__num">60.0%</span>，缺口
          <span class="sales-shipment-issues__num">127.6 亿元</span>（目标
          <span class="sales-shipment-issues__num">319 亿元</span>）；出货量
          <span class="sales-shipment-issues__num">54.6 GWh</span>，达成率
          <span class="sales-shipment-issues__num">60.0%</span>，缺口
          <span class="sales-shipment-issues__num">36.4 GWh</span>（目标
          <span class="sales-shipment-issues__num">91.0 GWh</span>）。共同问题分析：
        </div>
        <div class="sales-shipment-issues__line">
          1）【发货】订未发约 <span class="sales-shipment-issues__num">11.3 GWh</span>（<span class="sales-shipment-issues__num">39.6 亿元</span>）——超期订未发约
          <span class="sales-shipment-issues__num">6.9 GWh</span>（<span class="sales-shipment-issues__num">24.3 亿元</span>，最长超期
          <span class="sales-shipment-issues__num">78 天</span>）、正常订未发约
          <span class="sales-shipment-issues__num">4.4 GWh</span>（<span class="sales-shipment-issues__num">15.3 亿元</span>）。S1 战略客户因设备质量问题未能如期发货，影响交付侧即期确认。
        </div>
        <div class="sales-shipment-issues__line">
          2）【订单接收】订单变更减少 <span class="sales-shipment-issues__num">0.8 GWh</span>（约
          <span class="sales-shipment-issues__num">2.8 亿元</span>）、订单取消涉及
          <span class="sales-shipment-issues__num">1.2 GWh</span>（约 <span class="sales-shipment-issues__num">4.2 亿元</span>），合计影响
          <span class="sales-shipment-issues__num">2.0 GWh</span>（约 <span class="sales-shipment-issues__num">7.0 亿元</span>）的出货。
        </div>
        <div class="sales-shipment-issues__line">
          3）【投标】投标总电量约 <span class="sales-shipment-issues__num">7.8 GWh</span>（<span class="sales-shipment-issues__num">27.4 亿元</span>），中标电量约
          <span class="sales-shipment-issues__num">3.7 GWh</span>（<span class="sales-shipment-issues__num">13.0 亿元</span>）；其中已签单
          <span class="sales-shipment-issues__num">1.4 GWh</span>（<span class="sales-shipment-issues__num">5.0 亿元</span>）、已中标未签单
          <span class="sales-shipment-issues__num">2.3 GWh</span>（<span class="sales-shipment-issues__num">8.0 亿元</span>）；中标率
          <span class="sales-shipment-issues__num">49.0%</span>（<span class="sales-shipment-issues__num">24/49</span> 项，按项目数统计）；
        </div>
        <div class="sales-shipment-issues__line">
          4）【商机获取】商机预测总电量约 <span class="sales-shipment-issues__num">79.9 GWh</span>（<span class="sales-shipment-issues__num">280 亿元</span>），低于全年目标
          <span class="sales-shipment-issues__num">91.0 GWh</span>（<span class="sales-shipment-issues__num">319 亿元</span>），缺口约
          <span class="sales-shipment-issues__num">11.1 GWh</span>（<span class="sales-shipment-issues__num">39 亿元</span>）。
        </div>
      </section>
    `,
  })
)
