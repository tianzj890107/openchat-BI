import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
const source=fs.readFileSync(new URL('../bi_agent/web/static/cockpit/task-progress.js',import.meta.url),'utf8');
const {taskProgressText}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
test('each card uses its own stage status and frozen completed duration',()=>{
 const manual={running:true,stageProgress:{
   order:{status:'running',phase:'analysing',message:'模型分析第 2 轮',startedAt:100},
   bid:{status:'queued',queuedAt:90},
   shipment:{status:'completed',startedAt:50,finishedAt:80},
 }};
 assert.equal(taskProgressText(manual,'order',165000),'模型分析第 2 轮 · 耗时 1分5秒');
 assert.equal(taskProgressText(manual,'bid',165000),'排队等待 · 已等待 1分15秒');
 assert.equal(taskProgressText(manual,'shipment',165000),'已更新 · 耗时 30秒');
 assert.equal(taskProgressText(manual,'quotation',165000),'');
});

test('opportunity V2 shows database counts plus current step and total duration',()=>{
 const manual={running:true,stageProgress:{
   'opportunity-risk':{status:'running',phase:'fetching',message:'查询数据库',
     completed:6,total:10,startedAt:100,stepStartedAt:120},
 }};
 assert.equal(taskProgressText(manual,'opportunity-risk',165000),
   '查询数据库 6/10 · 本步 45秒 · 总耗时 1分5秒');
});
