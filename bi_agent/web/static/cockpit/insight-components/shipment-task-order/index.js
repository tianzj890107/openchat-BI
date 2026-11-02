/**
 * Compatibility shim for the delivered 15-slot metadata.
 *
 * Task generation now lives in the recommendation card shared by the
 * opportunity, order and shipment risk slots. Keeping this registration
 * avoids changing the delivered slot count while ensuring there is only one
 * visible entry point and one draft contract.
 */
const {insightProps, registerInsightComponent} = window.InsightRuntime

registerInsightComponent('shipment-task-order', Vue.defineComponent({
  name: 'ShipmentTaskOrderCompatibility',
  props: insightProps,
  template: '<section class="shipment-task-order-compat" style="display:none" aria-hidden="true"></section>',
}))
