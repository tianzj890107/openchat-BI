import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const source = await readFile(
  new URL('../bi_agent/web/static/cockpit/insight-components/shipment-task-order/index.js', import.meta.url),
  'utf8',
)

test('shipment task order has draft, edit, save and explicit dispatch actions', () => {
  assert.match(source, /生成任务令草稿/)
  assert.match(source, /保存草稿/)
  assert.match(source, /确认下发待办/)
  assert.match(source, /role="dialog"/)
  assert.match(source, /v-model="task\.title"/)
  assert.match(source, /v-model="measure\.action"/)
  assert.match(source, /v-model="measure\.owner"/)
  assert.match(source, /v-model="measure\.deadline"/)
  assert.match(source, /v-model="measure\.acceptance"/)
  assert.match(source, /\/analyses\/\$\{encodeURIComponent\(analysisId\.value\)\}\/draft/)
  assert.match(source, /action: 'save'/)
  assert.match(source, /\/dispatch/)
  assert.match(source, /下发失败/)
})

test('task order recipients stay server-side and terminal states stop loading', () => {
  assert.doesNotMatch(source, /18837823993/)
  assert.doesNotMatch(source, /mobile|phoneNumber|recipients\s*:/i)
  assert.match(source, /接收人由服务端安全映射/)
  assert.match(source, /dialogOpen\.value = false/)
  assert.match(source, /taskError\.value = `下发失败/)
})
