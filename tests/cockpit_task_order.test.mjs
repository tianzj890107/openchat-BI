import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const root = new URL('../bi_agent/web/static/cockpit/insight-components/', import.meta.url)
const read = path => readFile(new URL(path, root), 'utf8')

const [shared, controller, client, dialog, shipmentShim] = await Promise.all([
  read('shared.js'),
  read('task-order/controller.js'),
  read('task-order/client.js'),
  read('task-order/dialog.js'),
  read('shipment-task-order/index.js'),
])
const cockpit = await readFile(new URL('../bi_agent/web/static/cockpit/cockpit.js', import.meta.url), 'utf8')

test('all three stage risk cards share the recommendation task button and dialog', () => {
  assert.match(shared, /createTaskOrderController/)
  assert.match(shared, /<task-order-dialog/)
  assert.match(shared, /stage-risk-analysis__draft/)
  assert.match(shared, /openOrGenerate/)
  assert.match(shared, /actionTypeLabel/)
  assert.match(shared, /analysisDimensions/)
  assert.match(controller, /可按所选建议生成核查任务/)
  assert.match(controller, /当前没有可选择的业务建议/)
})

test('draft requests send selected ids only and dispatch stays server-owned', () => {
  assert.match(client, /recommendationIds: recommendationIds\.map\(String\)/)
  assert.match(client, /\/analyses\/\$\{encodeURIComponent\(analysisId\)\}\/draft/)
  assert.match(client, /\/tasks\/\$\{encodeURIComponent\(taskId\)\}\/dispatch/)
  assert.match(client, /retry: false/)
  assert.doesNotMatch(client, /18837823993|recipients|mobile|phoneNumber/i)
})

test('controller deduplicates by selection and prevents repeated dispatch', () => {
  assert.match(controller, /taskSelectionKey/)
  assert.match(controller, /taskMatchesSelection/)
  assert.match(controller, /按当前建议生成草稿/)
  assert.match(controller, /当前没有选中的建议/)
  assert.match(controller, /client\.save/)
  assert.match(controller, /client\.dispatch/)
  assert.match(controller, /if \(busy\.value \|\| dispatched\.value\) return/)
})

test('shared dialog exposes editable structured fields and explicit confirmation', () => {
  assert.match(dialog, /role="dialog"/)
  assert.match(dialog, /v-model="task\.title"/)
  assert.match(dialog, /v-model="measure\.action"/)
  assert.match(dialog, /v-model="measure\.owner"/)
  assert.match(dialog, /v-model="measure\.deadline"/)
  assert.match(dialog, /v-model="measure\.acceptance"/)
  assert.match(dialog, /ownerConfirmed/)
  assert.match(dialog, /deadlineConfirmed/)
  assert.match(dialog, /确认下发待办/)
  assert.match(dialog, /保存草稿/)
  assert.doesNotMatch(dialog, /18837823993|mobile|phoneNumber|recipients\s*:/i)
})

test('the legacy shipment task slot is hidden after consolidating the entry point', () => {
  assert.match(shipmentShim, /Compatibility shim/)
  assert.match(shipmentShim, /display:none/)
  assert.match(shipmentShim, /registerInsightComponent\('shipment-task-order'/)
  assert.doesNotMatch(shipmentShim, /生成任务令草稿/)
  assert.match(cockpit, /filter\(item => item\.id !== 'shipment-task-order'\)/)
})

test('task creation opens a structured dialog rather than an agent chat', () => {
  assert.match(dialog, /任务正文由已交付建议生成/)
  assert.doesNotMatch(shared + controller + dialog, /agent-?chat|chat-dialog|发送给智能体/i)
})
