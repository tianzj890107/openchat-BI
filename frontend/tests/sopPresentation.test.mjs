import test from 'node:test';
import assert from 'node:assert/strict';
import { presentSop } from '../src/sopPresentation.js';
test('unneeded stages are separated from cancelled executions and completion counts',()=>{
 const result=presentSop([{text:'识别',status:'completed'},{text:'根因分析',status:'skipped'}]);
 assert.equal(result.total,1);assert.equal(result.done,1);assert.deepEqual(result.skipped,['根因分析']);
 assert.equal(result.active.some(i=>i.status==='skipped'),false);
});
test('a real cancellation remains visible as an incomplete stage',()=>{
 const result=presentSop([{text:'取数',status:'cancelled'},{text:'交付',status:'pending'}]);
 assert.equal(result.total,2);assert.equal(result.done,0);assert.equal(result.active[0].status,'cancelled');
});
