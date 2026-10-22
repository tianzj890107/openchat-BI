/**
 * 插入组件入口。新增组件时在这里加一行。
 * 所有内部模块沿用入口 URL 的版本串，避免部署后命中旧子组件缓存。
 */
const version = new URL(import.meta.url).search
const load = path => import(new URL(`${path}${version}`, import.meta.url).href)

const [registry, shared] = await Promise.all([
  load('./registry.js'),
  load('./shared.js'),
])

window.InsightRuntime = { ...registry, ...shared }

await Promise.all([
  load('./bid-status-note/index.js'),
  load('./quote-summary/index.js'),
  load('./bid-summary/index.js'),
  load('./order-sign-summary/index.js'),
  load('./sales-shipment-issues/index.js'),
  load('./opportunity-risk/index.js'),
  load('./opportunity-coverage-note/index.js'),
  load('./order-risk-summary/index.js'),
  load('./shipment-risk-summary/index.js'),
  load('./shipment-overdue-note/index.js'),
  load('./shipment-cause-breakdown/index.js'),
  load('./shipment-task-order/index.js'),
])
