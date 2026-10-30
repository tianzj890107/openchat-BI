import test from 'node:test'
import assert from 'node:assert/strict'
import {quotationStatus} from '../bi_agent/web/static/cockpit/insight-components/quote-summary/status.js'
const row = (status, value) => ({data: {'报价办理状态[YWLN_D021]': status, '报价电量（GWh）[YWLN_M0031]': value}})
test('quote sums mutually exclusive AP states and preserves absent states', () => {
 const result = quotationStatus([row('normal_completed',25.57),row('overdue_completed',.56),row('overdue_uncompleted',.6)])
 assert.equal(result.completed,26.13);assert.equal(result.pending,.6);assert.equal(result.total,26.73)
 assert.equal(result.values.normal_uncompleted,undefined)
})
test('zero is valid, null is missing, duplicate records do not double count', () => {
 const result = quotationStatus([row('normal_completed',0),row('normal_completed',0),row('overdue_completed',null)])
 assert.equal(result.completed,0);assert.equal(result.total,0);assert.equal(result.pending,null)
 assert.equal(quotationStatus([]).total,null)
})
