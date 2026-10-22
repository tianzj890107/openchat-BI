/**
 * 发货风险概况。插在发货节点联动展示模版顶部。
 */
import { loadInsightStyle, registerInsightComponent } from '../registry.js'

loadInsightStyle(import.meta.url)

registerInsightComponent(
  'shipment-risk-summary',
  Vue.defineComponent({
    name: 'ShipmentRiskSummary',
    template: `
      <section class="shipment-risk-summary">
        <article class="shipment-risk-summary__card">
          <div class="shipment-risk-summary__head">
            <strong class="shipment-risk-summary__title">发货风险概况</strong>
            <span class="shipment-risk-summary__aside">
              合计 39.6 亿元 / 约 11.3 GWh ·
              <span class="shipment-risk-summary__green">正常订未发 15.3 亿元 / 约 4.4 GWh</span>
              ·
              <span class="shipment-risk-summary__red">超期订未发 24.3 亿元 / 约 6.9 GWh</span>
            </span>
          </div>
          <div>订未发拆分：正常订未发 15.3 亿元 / 约 4.4 GWh；超期订未发 24.3 亿元 / 约 6.9 GWh</div>
          <div>
            <span class="shipment-risk-summary__green">正常订未发 15.3 亿元 / 约 4.4 GWh</span>：
            <span class="shipment-risk-summary__green">正常订未发 4.4 GWh</span>
          </div>
          <div>
            <span class="shipment-risk-summary__red">超期订未发 24.3 亿元 / 约 6.9 GWh</span>：
            <span class="shipment-risk-summary__red">超期订未发 6.9 GWh</span>
          </div>
          <div class="shipment-risk-summary__note">
            订未发 39.6 亿元 = 正常订未发 15.3 亿元 + 超期订未发 24.3 亿元。按 319 亿元对应 91 GWh 的模拟比例，约为 4.4 + 6.9 = 11.3 GWh；详细原因与客户处置见下方发货风险内容。
          </div>
        </article>

        <article class="shipment-risk-summary__panel shipment-risk-summary__panel--risk">
          <div class="shipment-risk-summary__title">
            <span class="shipment-risk-summary__mark--risk">【风险】</span>
            已超期未发 24.3 亿，战略与重点客户需优先处理
          </div>
          <div>
            全年销售目标 <span class="shipment-risk-summary__num--risk">319 亿元</span>，已发货
            <span class="shipment-risk-summary__num--risk">191.4 亿元</span>；订未发
            <span class="shipment-risk-summary__num--risk">39.6 亿元 / 11.3 GWh</span>，其中超期未发
            <span class="shipment-risk-summary__num--risk">24.3 亿元 / 约 6.9 GWh</span>，正常订未发
            <span class="shipment-risk-summary__num--risk">15.3 亿元 / 4.4 GWh</span>。
          </div>
          <div>
            超期订单涉及 S1、S2、S3、S6、S7 战略客户合计
            <span class="shipment-risk-summary__num--risk">15.6 亿元</span>，以及 K1、K2、K3 重点客户合计
            <span class="shipment-risk-summary__num--risk">8.7 亿元</span>。其中 S1 战略客户（客户 A）因设备质量异常与质检未放行，
            <span class="shipment-risk-summary__num--risk">4.8 亿元</span>未如期发货。
          </div>
        </article>

        <article class="shipment-risk-summary__panel shipment-risk-summary__panel--cause">
          <div class="shipment-risk-summary__title">
            <span class="shipment-risk-summary__mark--cause">【原因】</span>
            四类主因共影响约 6.9 GWh 超期出货
          </div>
          <div>
            已超期出货电量约 <span class="shipment-risk-summary__num--cause">6.9 GWh（金额 24.3 亿元）</span>，按单一主因互斥归属：排产问题
            <span class="shipment-risk-summary__num--cause">2.2 GWh / 7.9 亿元</span>、厂线产能和生产问题
            <span class="shipment-risk-summary__num--cause">2.1 GWh / 7.5 亿元</span>、物流及单证问题
            <span class="shipment-risk-summary__num--cause">1.3 GWh / 4.5 亿元</span>、客户侧提货
            <span class="shipment-risk-summary__num--cause">1.3 GWh / 4.4 亿元</span>。
          </div>
          <div class="shipment-risk-summary__note">
            每笔超期订单只归入一类主因；细分根因用于安排处理动作，避免跨类重复计数。
          </div>
        </article>

        <article class="shipment-risk-summary__panel shipment-risk-summary__panel--suggest">
          <div class="shipment-risk-summary__head">
            <div class="shipment-risk-summary__title">
              <span class="shipment-risk-summary__mark--suggest">【建议】</span>
              按客户优先级逐单排障并下达任务
            </div>
            <button type="button" class="shipment-risk-summary__draft">查看任务令</button>
          </div>
          <div>
            优先处理战略与重点客户的已超期订单：排产锁产能、厂线补料与质量放行、物流补舱补单证、客户重签提货计划。60 天内化解
            <span class="shipment-risk-summary__num--suggest">16.0 亿元</span>，其余
            <span class="shipment-risk-summary__num--suggest">8.3 亿元</span>逐单跟踪。
          </div>
          <div>先对 S1 战略客户确认返工及质检放行日期，再给出可承诺发货日。</div>
        </article>
      </section>
    `,
  })
)
