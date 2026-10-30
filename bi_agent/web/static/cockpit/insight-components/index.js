/**
 * 插入组件入口。新增组件时在这里加一行。
 * 所有内部模块沿用入口 URL 的版本串，避免部署后命中旧子组件缓存。
 */
const version = new URL(import.meta.url).search
const load = path => import(new URL(`${path}${version}`, import.meta.url).href)

const ids = new Set(['bid-status-note','quote-summary','bid-summary','order-sign-summary',
  'star-product-order-list','affected-order-list','overdue-order-list',
  'sales-shipment-issues','opportunity-risk','opportunity-coverage-note','order-risk-summary',
  'shipment-risk-summary','shipment-overdue-note','shipment-cause-breakdown','shipment-task-order'])
let runtime
const pending = new Map()
export function loadInsight(id) {
  if (!ids.has(id)) return Promise.reject(new Error('未知的AI插槽组件'))
  if (!runtime) runtime = Promise.all([load('./registry.js'),load('./shared.js')]).then(([registry,shared])=>{
    window.InsightRuntime = {...registry,...shared}
  })
  if (!pending.has(id)) pending.set(id,runtime.then(()=>load(`./${id}/index.js`)).then(()=>window.InsightComponents[id]))
  return pending.get(id)
}
