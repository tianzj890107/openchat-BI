import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
const source=fs.readFileSync(new URL('../bi_agent/web/static/cockpit/task-progress.js',import.meta.url),'utf8');
const {taskProgressText,newStageFailures,failureText}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
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

test('stage failures pop once and only for a round this page saw running',()=>{
 const watch={runId:'',announced:new Set()};
 const stale={runId:'old',status:'partial',stageProgress:{order:{status:'failed',error:'旧失败'}}};
 assert.deepEqual(newStageFailures(stale,watch),[]);
 assert.deepEqual(newStageFailures({runId:'r1',status:'running',stageProgress:{
   'opportunity-risk':{status:'running',phase:'analysing'}}},watch),[]);
 const failed={runId:'r1',status:'partial',stageProgress:{
   'opportunity-risk':{status:'failed',diagnosticId:'d1',errorDetails:[{title:'调用过程',lines:['第 1 次 · 生成分析']},{title:'空',lines:[]}],
     error:'模型调用中断：模型未返回完整文本。本轮未发布，卡片已清空，请稍后重试。'},
   order:{status:'failed'}}};
 assert.deepEqual(newStageFailures(failed,watch),[
   {key:'r1:opportunity-risk',stage:'商机获取 · 风险分析卡',diagnosticId:'d1',
    message:'模型调用中断：模型未返回完整文本。本轮未发布，卡片已清空，请稍后重试。',details:[{title:'调用过程',lines:['第 1 次 · 生成分析']}]},
   {key:'r1:order',stage:'订单接收',diagnosticId:'',message:'分析失败，本轮未发布，卡片已清空，请稍后重试。',details:[]},
 ]);
 assert.deepEqual(newStageFailures(failed,watch),[]);
});

test('failure text for copying keeps the message, details and diagnostic id',()=>{
 const text=failureText({stage:'商机获取 · 风险分析卡',message:'原因：模型请求超时',diagnosticId:'d9',
   details:[{title:'调用过程',lines:['第 1 次 · 生成分析；耗时 180 秒']}]});
 assert.equal(text,['【商机获取 · 风险分析卡】','原因：模型请求超时','','[调用过程]',
   '- 第 1 次 · 生成分析；耗时 180 秒','','诊断ID：d9'].join('\n'));
});
