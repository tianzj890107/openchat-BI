/* Run against tests/cockpit_performance_preview.py only. No real AP/model/user data. */
import assert from 'node:assert/strict';
const base=process.env.COCKPIT_QA_URL||'http://127.0.0.1:8896';
if(!['127.0.0.1','localhost'].includes(new URL(base).hostname))throw new Error('Browser fault tests are restricted to localhost QA fixtures');
const cdp=process.env.COCKPIT_QA_CDP||'http://127.0.0.1:9337';
const target=await(await fetch(cdp+'/json/new?about:blank',{method:'PUT'})).json();const ws=new WebSocket(target.webSocketDebuggerUrl);await new Promise(r=>ws.onopen=r);let seq=0;const pending=new Map(),errors=[],resources=[];
ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id){const p=pending.get(m.id);if(p){pending.delete(m.id);m.error?p.reject(new Error(JSON.stringify(m.error))):p.resolve(m.result)}}if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails.text);if(m.method==='Network.requestWillBeSent')resources.push(m.params.request.url)};
const send=(method,params={})=>new Promise((resolve,reject)=>{pending.set(++seq,{resolve,reject});ws.send(JSON.stringify({id:seq,method,params}))});
const evaluate=async expression=>{const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw new Error(r.exceptionDetails.text);return r.result?.value};
const wait=async(expression,timeout=15000)=>{const until=Date.now()+timeout;while(Date.now()<until){if(await evaluate(expression))return;await new Promise(r=>setTimeout(r,100));}throw new Error('Browser condition timeout: '+expression)};
const change=body=>fetch(base+'/debug/change',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
const debug=async()=>await(await fetch(base+'/debug/state')).json();
const navigate=page=>send('Page.navigate',{url:base+'/cockpit/'+page+'?id=1'});
await send('Page.enable');await send('Page.bringToFront');await send('Runtime.enable');await send('Network.enable');await send('Network.setCacheDisabled',{cacheDisabled:true});await send('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
try {
 await change({revision:1,fail:false});await navigate('analysis');
 await wait('document.querySelector("#app:not([v-cloak]) .cockpit-publication-state")?.innerText.includes("完整看板")');
 await wait('document.querySelectorAll(".insight-runtime-state").length===3');
 assert.equal(await evaluate('document.title'),'储能经营风险驾驶舱 · 穿透式问题分析');
 const loaded=resources.filter(u=>/insight-components\/[^/]+\/index.js/.test(u));
 assert.equal(loaded.length,3);assert.ok(loaded.every(u=>/sales-shipment-issues|opportunity-risk|opportunity-coverage-note/.test(u)));
 console.log('PASS initial route, 3 visible AI modules, server-published complete page');
 // All layout/data must survive an upstream failure, even across a frame reload.
 await change({fail:true});await send('Page.reload',{ignoreCache:true});
 await wait('document.querySelector(".sales-shipment-issues__summary")?.innerText.includes("测试卡片 1")');
 await wait('document.querySelector("#app:not([v-cloak]) .cockpit-publication-state")?.innerText.includes("继续展示上次完整内容")');
 assert.equal(await evaluate('document.querySelectorAll(".insight-loading").length'),0);
 console.log('PASS AP failure retains full charts and cards');
 await change({fail:false});
 await evaluate('[...document.querySelectorAll(".pro-radio-button")].find(e=>e.textContent.trim()==="月度").click()');
 await wait('document.querySelector("#app:not([v-cloak]) .cockpit-publication-state")?.innerText.includes("完整看板")');
 assert.deepEqual(await evaluate('[...document.querySelectorAll(".pro-radio-button.is-active")].map(e=>e.innerText)'),['月度']);
 assert.ok((await debug()).pages>=2);
 console.log('PASS filter invalidation, republish and monthly selection retained');
 await evaluate('[...document.querySelectorAll(".pro-radio-button")].find(e=>e.textContent.trim()==="年度").click()');
 await wait('document.querySelector("#app:not([v-cloak]) .cockpit-publication-state")?.innerText.includes("完整看板")');
 assert.deepEqual(await evaluate('[...document.querySelectorAll(".pro-radio-button.is-active")].map(e=>e.innerText)'),['年度']);
 console.log('PASS returning to a cached filter keeps the correct selection');
 await change({revision:2});await send('Page.reload',{ignoreCache:true});
 await wait('document.querySelector(".sales-shipment-issues__summary")?.innerText.includes("测试卡片 1")');
 await wait('document.querySelector(".sales-shipment-issues__summary")?.innerText.includes("测试卡片 2")');
 await wait('!document.querySelector("#app:not([v-cloak]) .cockpit-publication-state")?.innerText.includes("正在后台更新")');
 assert.equal(await evaluate('document.querySelectorAll(".insight-loading").length'),0);
 console.log('PASS old-first/new-complete background replacement');
 for(const page of ['overview','operations']) {
  await navigate(page);await wait('document.querySelector("#app:not([v-cloak]) .cockpit-publication-state")?.innerText.includes("完整看板")');
  assert.equal(await evaluate('document.querySelectorAll(".insight-loading").length'),0);
  console.log('PASS full-page publication '+page);
 }
 assert.deepEqual(errors,[]);
 console.log('PASS no browser exceptions; tests used only isolated fixtures');
} catch(error){console.log(JSON.stringify(await evaluate('({text:document.body.innerText.slice(0,2200),selected:[...document.querySelectorAll(".pro-radio-button.is-active")].map(e=>e.innerText)})')));throw error;} finally {await send('Page.close');ws.close();}
