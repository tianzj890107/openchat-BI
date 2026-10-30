/** 客户与超期订单：AP 事实 + 已校验卡片的主因和具体根因。 */
import {createTableInsight} from '../table-runtime.js'

const {loadInsightStyle} = window.InsightRuntime

loadInsightStyle(import.meta.url)

const fields = [
  {fieldType: 'Dimension', identifierCode: 'YWLN_D049', isTree: false, label: '销售订单编号', valueType: 'STRING'},
  {fieldType: 'Dimension', identifierCode: 'YWLN_D006', isTree: false, label: '具体客户', valueType: 'STRING'},
  {fieldType: 'Dimension', identifierCode: 'YWLN_D005', isTree: false, label: '客户等级', valueType: 'STRING'},
  {fieldType: 'Dimension', identifierCode: 'YWLN_D004', isTree: false, label: '产品团队', valueType: 'STRING'},
  {fieldType: 'Dimension', identifierCode: 'YWLN_D050', isTree: false, label: '承诺发货日', valueType: 'DATE'},
  {fieldType: 'Indicator', identifierCode: 'M0143', isTree: false, label: '超期订未发金额', name: 'Overdue_Unshipped_Amount', valueType: 'NUMBER'},
  {fieldType: 'Indicator', identifierCode: 'YWLN_M_ORDER_OVERDUE_DAYS', isTree: false, label: '超期天数', name: 'Order_Overdue_Days', valueType: 'NUMBER'},
]

const columns = [
  {code: 'YWLN_D049', fieldType: 'Dimension', id: 'YWLN_D049', isTree: false, label: '销售订单编号', showSearch: false, showSource: true, valueType: 'STRING'},
  {code: 'YWLN_D006', fieldType: 'Dimension', id: 'YWLN_D006', isTree: false, label: '具体客户', showSearch: false, showSource: true, valueType: 'STRING'},
  {code: 'YWLN_D005', fieldType: 'Dimension', id: 'YWLN_D005', isTree: false, label: '客户等级', showSearch: false, showSource: true, valueType: 'STRING'},
  {code: 'YWLN_D004', fieldType: 'Dimension', id: 'YWLN_D004', isTree: false, label: '产品团队', showSearch: false, showSource: true, valueType: 'STRING'},
  {code: 'YWLN_D050', fieldType: 'Dimension', id: 'YWLN_D050', isTree: false, label: '承诺发货日', showSearch: false, showSource: true, valueType: 'DATE'},
  {code: 'M0143', fieldType: 'Indicator', id: 'M0143', isTree: false, label: '超期订未发金额', showSearch: false, showSource: true, valueType: 'NUMBER'},
  {code: 'YWLN_M_ORDER_OVERDUE_DAYS', fieldType: 'Indicator', id: 'YWLN_M_ORDER_OVERDUE_DAYS', isTree: false, label: '超期天数', showSearch: false, showSource: true, valueType: 'NUMBER'},
  {code: '主因和根因分析', fieldType: 'Dimension', id: '主因和根因分析', isTree: false, label: '主因和根因分析', showSearch: false, showSource: true, valueType: 'STRING'},
]

createTableInsight({
  id: 'overdue-order-list',
  name: 'OverdueOrderList',
  title: '客户与超期订单',
  tableKey: 'overdue-order-list',
  fields,
  columns,
  showTitle: true,
})
