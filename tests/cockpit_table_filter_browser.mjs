import assert from 'node:assert/strict';
// Run with the isolated tests/cockpit_performance_preview.py fixture only.
const cdp=process.env.COCKPIT_QA_CDP||'http://127.0.0.1:9337';
const base=process.env.COCKPIT_QA_URL||'http://127.0.0.1:18986';
if(!['localhost','127.0.0.1'].includes(new URL(base).hostname))throw new Error('Only localhost QA fixtures are allowed');
const tab=await(await fetch(cdp+'/json/new?about:blank',{method:'PUT'})).json();
const ws=new WebSocket(tab.webSocketDebuggerUrl);await new Promise(r=>ws.onopen=r);let seq=0;const pending=new Map();
const refreshUrls=[];
ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(new Error(JSON.stringify(m.error))):p.resolve(m.result)}
  else if(m.method==='Network.requestWillBeSent'&&String(m.params?.request?.url||'').includes('/analyses/refresh'))refreshUrls.push(m.params.request.url)};
const send=(method,params={})=>new Promise((resolve,reject)=>{pending.set(++seq,{resolve,reject});ws.send(JSON.stringify({id:seq,method,params}))});
const evaluate=async expression=>{const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw new Error(r.exceptionDetails.exception?.description||r.exceptionDetails.text);return r.result?.value};
const wait=async expression=>{const until=Date.now()+20000;while(Date.now()<until){if(await evaluate(expression))return;await new Promise(r=>setTimeout(r,100))}throw new Error('timeout: '+expression)};
try {
 await send('Page.enable');await send('Runtime.enable');await send('Network.enable');
 await send('Page.addScriptToEvaluateOnNewDocument',{source:`const capture=setInterval(()=>{if(!window.ProUIBi?.createBiRuntime)return;const original=window.ProUIBi.createBiRuntime;window.ProUIBi.createBiRuntime=function(...args){const result=original.apply(this,args);window.__qaRuntime=result;window.__qaRuntimeCount=(window.__qaRuntimeCount||0)+1;return result};clearInterval(capture)},1);`});
 await send('Page.navigate',{url:base+'/cockpit/analysis?id=1'});
 await wait('document.querySelector(".cockpit-board") && document.body.innerText.includes("计划突破")');
 await new Promise(r=>setTimeout(r,1800));
 await wait('window.__qaRuntime && document.querySelector(".cockpit-board")');
 await evaluate('window.__qaBoard=document.querySelector(".cockpit-board");window.__qaCount=window.__qaRuntimeCount');
 const refreshBefore=refreshUrls.length;
 for(const level of ['1','2',null]) {
   await evaluate(`document.querySelector('.pro-bi-data-table__button-group-filters').dispatchEvent(new PointerEvent('pointerdown',{bubbles:true}))`);
   await evaluate(`window.__qaRuntime.setFilterConditions('table-ilzta6h7',${JSON.stringify(level ? [{identifierCode:'YWLN_D005',label:'客户等级',operator:{code:'IN',type:'STRING'},value:[level],type:'Dimension',valueType:'ABSOLUTE'}] : [])})`);
   await new Promise(r=>setTimeout(r,650));
   assert.equal(await evaluate('window.__qaBoard===document.querySelector(".cockpit-board")'),true);
   assert.equal(await evaluate('window.__qaCount===window.__qaRuntimeCount'),true);
 }
 assert.equal(refreshUrls.length,refreshBefore,'table-local filters must not start stage analysis');
 console.log('PASS customer level 1 / 2 / reset preserve mounted board, runtime and published analysis');
 await evaluate(`[...document.querySelectorAll('.pro-radio-button')].find(e=>e.textContent.trim()==='月度').click()`);
 await wait('window.__qaRuntimeCount>window.__qaCount');
 console.log('PASS global monthly filter still changes the page scope');
} finally {await send('Page.close');ws.close()}
