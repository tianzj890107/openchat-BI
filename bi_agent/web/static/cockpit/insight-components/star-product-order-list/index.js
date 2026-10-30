/** 明星产品订单电量、占比与口径。布局由 ProDataTable 提供。 */
import {createTableInsight} from '../table-runtime.js'

const {loadInsightStyle} = window.InsightRuntime

loadInsightStyle(import.meta.url)

const SHARE_FIELD = 'YWLN_M_ORDER_RECEIPT_ENERGY_PCT'

const fields = [
  {fieldType: 'Dimension', identifierCode: 'YWLN_D046', isTree: false, label: '明星产品系列', valueType: 'STRING'},
  {fieldType: 'Indicator', identifierCode: 'YWLN_M_STAR_PRODUCT_SHIPMENT_2025', isTree: false, label: '去年参考电量', name: '去年参考电量', valueType: 'NUMBER'},
  {fieldType: 'Indicator', identifierCode: 'YWLN_M0032', isTree: false, label: '订单接收电量', name: 'Signed_Opportunity_Forecast_Energy', valueType: 'NUMBER'},
  {fieldType: 'Indicator', identifierCode: SHARE_FIELD, isTree: false, label: '占全部订单电量', name: 'Order_Receipt_Energy_Percentage', valueType: 'NUMBER'},
]

const columns = [
  {code: 'YWLN_D046', fieldType: 'Dimension', id: 'YWLN_D046', isTree: false, label: '明星产品系列', showSearch: false, showSource: true, valueType: 'STRING'},
  {code: 'YWLN_M_STAR_PRODUCT_SHIPMENT_2025', fieldType: 'Indicator', id: 'YWLN_M_STAR_PRODUCT_SHIPMENT_2025', isTree: false, label: '去年参考电量', showSearch: false, showSource: true, valueType: 'NUMBER'},
  {code: 'YWLN_M0032', fieldType: 'Indicator', id: 'YWLN_M0032', isTree: false, label: '订单接收电量', showSearch: false, showSource: true, valueType: 'NUMBER'},
  {code: SHARE_FIELD, fieldType: 'Indicator', id: SHARE_FIELD, isTree: false, label: '占全部订单电量', showSearch: false, showSource: true, valueType: 'NUMBER'},
  {code: '口径', fieldType: 'Dimension', id: '口径', isTree: false, label: '口径', showSearch: false, showSource: true, valueType: 'STRING'},
]

createTableInsight({
  id: 'star-product-order-list',
  name: 'StarProductOrderList',
  title: '明星产品订单电量及占比',
  tableKey: 'star-product-order-list',
  fields,
  columns,
})
