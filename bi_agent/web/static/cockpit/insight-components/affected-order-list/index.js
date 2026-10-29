/** 受影响订单清单：AP 事实 + 已校验卡片的原因与责任动作。 */
import {createTableInsight} from '../table-runtime.js'

const {loadInsightStyle} = window.InsightRuntime

loadInsightStyle(import.meta.url)

const fields = [
  {fieldType: 'Dimension', identifierCode: 'YWLN_D049', isTree: false, label: '销售订单编号', valueType: 'STRING'},
  {fieldType: 'Dimension', identifierCode: 'YWLN_D006', isTree: false, label: '具体客户', valueType: 'STRING'},
  {fieldType: 'Dimension', identifierCode: 'YWLN_D005', isTree: false, label: '客户等级', valueType: 'STRING'},
  {fieldType: 'Dimension', identifierCode: 'YWLN_D003', isTree: false, label: '产品类型', valueType: 'STRING'},
  {fieldType: 'Dimension', identifierCode: 'YWLN_D004', isTree: false, label: '产品团队', valueType: 'STRING'},
  {fieldType: 'Indicator', identifierCode: 'YWLN_M_ORDER_CANCEL_CHANGE', isTree: false, label: '取消/变更订单电量', name: '取消/变更订单电量', valueType: 'NUMBER'},
]

const columns = [
  {code: 'YWLN_D049', fieldType: 'Dimension', id: 'YWLN_D049', isTree: false, label: '销售订单编号', showSearch: false, showSource: true, valueType: 'STRING'},
  {code: 'YWLN_D006', fieldType: 'Dimension', id: 'YWLN_D006', isTree: false, label: '具体客户', showSearch: false, showSource: true, valueType: 'STRING'},
  {code: 'YWLN_D005', fieldType: 'Dimension', id: 'YWLN_D005', isTree: false, label: '客户等级', showSearch: false, showSource: true, valueType: 'STRING'},
  {code: 'YWLN_D003', fieldType: 'Dimension', id: 'YWLN_D003', isTree: false, label: '产品类型', showSearch: false, showSource: true, valueType: 'STRING'},
  {code: 'YWLN_D004', fieldType: 'Dimension', id: 'YWLN_D004', isTree: false, label: '产品团队', showSearch: false, showSource: true, valueType: 'STRING'},
  {code: 'YWLN_M_ORDER_CANCEL_CHANGE', fieldType: 'Indicator', id: 'YWLN_M_ORDER_CANCEL_CHANGE', isTree: false, label: '取消/变更订单电量', showSearch: false, showSource: true, valueType: 'NUMBER'},
  {code: '原因', fieldType: 'Dimension', id: '原因', isTree: false, label: '原因', showSearch: false, showSource: true, valueType: 'STRING'},
  {code: '责任动作', fieldType: 'Dimension', id: '责任动作', isTree: false, label: '责任动作', showSearch: false, showSource: true, valueType: 'STRING'},
]

createTableInsight({
  id: 'affected-order-list',
  name: 'AffectedOrderList',
  title: '受影响订单清单',
  tableKey: 'affected-order-list',
  fields,
  columns,
})
