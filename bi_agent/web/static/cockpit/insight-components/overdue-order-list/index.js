/** 客户与超期订单：AP 事实 + 已校验卡片的主因和具体根因。 */
import {createTableInsight} from '../table-runtime.js'
// Upstream 5bbfcf7: default sort icon, click override and explicit clear are
// preserved by the shared adapter; business/AI reads stay on Cockpit APIs.

const {loadInsightStyle} = window.InsightRuntime

loadInsightStyle(import.meta.url)

const OVERDUE_DAYS_FIELD = 'YWLN_M_ORDER_OVERDUE_DAYS'
/** 与看板 table-s41y03ym dataConfig.sort 对齐：按超期订未发金额降序 */
const SORT_FIELDS = [
  {fieldType: 'Indicator', identifierCode: 'M0143', isTree: false, label: '超期订未发金额', name: 'Overdue_Unshipped_Amount', valueType: 'NUMBER', order: 'DESC'},
]

const filterFields = [
  {
    fieldType: 'Indicator',
    identifierCode: OVERDUE_DAYS_FIELD,
    isTree: false,
    label: '超期天数',
    name: 'Order_Overdue_Days',
    valueType: 'NUMBER',
    conditions: {
      alias: '超期天数',
      identifierCode: OVERDUE_DAYS_FIELD,
      operator: {code: 'GT', type: 'NUMBER'},
      type: 'Indicator',
      value: 0,
      valueType: 'ABSOLUTE',
    },
  },
]

const fields = [
  {fieldType: 'Dimension', identifierCode: 'YWLN_D049', isTree: false, label: '销售订单编号', valueType: 'STRING'},
  {fieldType: 'Dimension', identifierCode: 'YWLN_D006', isTree: false, label: '具体客户', valueType: 'STRING'},
  {fieldType: 'Dimension', identifierCode: 'YWLN_D005', isTree: false, label: '客户等级', valueType: 'STRING'},
  {fieldType: 'Dimension', identifierCode: 'YWLN_D004', isTree: false, label: '产品团队', valueType: 'STRING'},
  {fieldType: 'Indicator', identifierCode: 'M0143', isTree: false, label: '超期订未发金额', name: 'Overdue_Unshipped_Amount', valueType: 'NUMBER'},
  {fieldType: 'Indicator', identifierCode: OVERDUE_DAYS_FIELD, isTree: false, label: '超期天数', name: 'Order_Overdue_Days', valueType: 'NUMBER'},
  {fieldType: 'Dimension', identifierCode: 'YWLN_D050', isTree: true, label: '承诺发货日', valueType: 'DATE'},
]

const columns = [
  {code: 'YWLN_D049', fieldType: 'Dimension', id: 'YWLN_D049', isTree: false, label: '销售订单编号', showSearch: false, showSource: true, valueType: 'STRING'},
  {code: 'YWLN_D006', fieldType: 'Dimension', id: 'YWLN_D006', isTree: false, label: '具体客户', showSearch: false, showSource: true, valueType: 'STRING'},
  {code: 'YWLN_D005', fieldType: 'Dimension', id: 'YWLN_D005', isTree: false, label: '客户等级', showSearch: false, showSource: true, valueType: 'STRING'},
  {code: 'YWLN_D004', fieldType: 'Dimension', id: 'YWLN_D004', isTree: false, label: '产品团队', showSearch: false, showSource: true, valueType: 'STRING'},
  {code: 'M0143', fieldType: 'Indicator', id: 'M0143', isTree: false, label: '超期订未发金额', showSearch: false, showSource: true, valueType: 'NUMBER'},
  {code: OVERDUE_DAYS_FIELD, fieldType: 'Indicator', id: OVERDUE_DAYS_FIELD, isTree: false, label: '超期天数', showSearch: false, showSource: true, valueType: 'NUMBER'},
  {code: 'YWLN_D050', fieldType: 'Dimension', id: 'YWLN_D050', isTree: true, label: '承诺发货日', showSearch: false, showSource: true, valueType: 'DATE'},
  {code: '主因和根因分析', fieldType: 'Dimension', id: '主因和根因分析', isTree: false, label: '主因和根因分析', showSearch: false, showSource: true, valueType: 'STRING'},
]

createTableInsight({
  id: 'overdue-order-list',
  name: 'OverdueOrderList',
  title: '客户与超期订单',
  tableKey: 'overdue-order-list',
  fields,
  columns,
  filterFields,
  sort: SORT_FIELDS,
  showTitle: true,
})
