/**
 * 出货风险解决任务令。插在发货节点「客户与超期订单」卡片下方。
 */
import { loadInsightStyle, registerInsightComponent } from '../registry.js'

loadInsightStyle(import.meta.url)

registerInsightComponent(
  'shipment-task-order',
  Vue.defineComponent({
    name: 'ShipmentTaskOrder',
    data() {
      return {
        tasks: [
          {
            title: '锁定排产与产能',
            tag: '排产问题 · 2.2 GWh / 7.9 亿元',
            lead: '运营管理部 / PMC',
            coop: '销售运营、各产品部、财经信控',
            action:
              '逐单核对需求预测与集团产能池分配，处理插单、跨厂调配及信用条件限制；先锁定战略与重点客户的可执行排产窗口。',
            deliver: '48 小时内提交锁产能清单和承诺发货日；60 天内化解 5.0 亿元，每周更新。',
          },
          {
            title: '补料、返工与质量放行',
            tag: '厂线产能和生产问题 · 2.1 GWh / 7.5 亿元',
            lead: '制造中心',
            coop: '采购中心、质量管理部、AIDC 产品部',
            action: '逐单确认缺料到料、返工和质检放行日期；优先解决 S1 战略客户 4.8 亿元设备批次质量异常。',
            deliver: '48 小时内提交补料与质量放行计划；60 天内化解 5.0 亿元，每周更新。',
          },
          {
            title: '保障发运与补齐单证',
            tag: '物流及单证问题 · 1.3 GWh / 4.5 亿元',
            lead: '物流中心',
            coop: '国际电力产品部、认证合规团队',
            action: '重新协调发运排期与海外舱位，逐单补齐 UL、CE、并网等认证和提货单证。',
            deliver: '3 个工作日内提交舱位、运力及单证完成日期；60 天内化解 3.0 亿元，每周更新。',
          },
          {
            title: '确认客户提货计划',
            tag: '客户侧提货 · 1.3 GWh / 4.4 亿元',
            lead: '各产品部销售负责人',
            coop: '客户项目团队、售后团队',
            action: '与客户重签提货及分批交付计划，核实现场收货条件，关闭验收争议和售后遗留问题。',
            deliver: '3 个工作日内提交客户确认的提货计划；60 天内化解 3.0 亿元，每周更新。',
          },
        ],
      }
    },
    template: `
      <section class="shipment-task-order">
        <div class="shipment-task-order__head">
          <span class="shipment-task-order__step">3</span>
          <strong class="shipment-task-order__title">出货风险解决任务令</strong>
          <span class="shipment-task-order__sub">明确责任、目标和回报方式</span>
        </div>
        <div class="shipment-task-order__summary">
          按四类主因分派 4 条任务，覆盖超期未发 24.3 亿元 / 约 6.9 GWh；60 天内拟化解 16.0 亿元，其余 8.3 亿元逐单滚动。
        </div>
        <article v-for="(item, index) in tasks" :key="item.title" class="shipment-task-order__task">
          <div class="shipment-task-order__task-head">
            <span class="shipment-task-order__no">{{ index + 1 }}</span>
            <strong class="shipment-task-order__task-title">{{ item.title }}</strong>
            <span class="shipment-task-order__tag">{{ item.tag }}</span>
          </div>
          <div class="shipment-task-order__meta">
            <div><span class="shipment-task-order__label">牵头部门：</span>{{ item.lead }}</div>
            <div><span class="shipment-task-order__label">协同部门：</span>{{ item.coop }}</div>
          </div>
          <div><span class="shipment-task-order__label">处理动作：</span>{{ item.action }}</div>
          <div><span class="shipment-task-order__label">交付与时限：</span>{{ item.deliver }}</div>
        </article>
        <div class="shipment-task-order__foot">
          <span class="shipment-task-order__hint">原型中仅更新任务状态。</span>
          <button type="button" class="shipment-task-order__dispatch">下发 4 条任务令</button>
        </div>
      </section>
    `,
  })
)
