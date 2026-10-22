import fs from 'node:fs';
// Usage: node scripts/extract_cockpit_layout.mjs /path/to/V3-总裁驾驶舱.html [CDP URL]
const source=process.argv[2];if(!source)throw Error('Prototype HTML path required');
const cdp=process.argv[3]||'http://127.0.0.1:9337';
const target=await(await fetch(cdp+'/json/new?'+encodeURIComponent('file://'+source),{method:'PUT'})).json();
const ws=new WebSocket(target.webSocketDebuggerUrl);await new Promise(r=>ws.onopen=r);
let seq=0;const calls=new Map();ws.onmessage=e=>{const m=JSON.parse(e.data);if(calls.has(m.id)){calls.get(m.id)(m.result);calls.delete(m.id)}};
const send=(method,params)=>new Promise(r=>{const id=++seq;calls.set(id,r);ws.send(JSON.stringify({id,method,params}))});
await send('Emulation.setDeviceMetricsOverride',{width:1440,height:1050,deviceScaleFactor:1,mobile:false});
await new Promise(r=>setTimeout(r,700));
const expr=`(()=>{
 useStory('ltc');revealed=4;cockpitLanding=false;operationsOverviewOpen=true;chainActive=-1;
 const styles=[...document.querySelectorAll('style')].map(e=>e.textContent).join('\\n');
 const views={},gaps=[];const STAGE_IDS=['opportunity','guidance','quotation','technical','bid','order','shipment'];
 document.body.innerHTML='<main class="dash-body" id="board"></main>';
 const fix=document.createElement('style');fix.textContent='html,body{height:auto!important;overflow:visible!important;background:#fff}#board{height:auto;max-height:none;overflow:visible}';document.head.append(fix);
 function blank(el,key,reason,view){
   if(!el||el.closest('[data-gap]'))return;
   const box=el.getBoundingClientRect();
   const gapId=view+':'+key+':'+gaps.filter(g=>g.view===view&&g.key===key).length;
   let node=el;
   if(el.matches('svg')){node=document.createElement('div');el.replaceWith(node);}
   node.replaceChildren();node.setAttribute('data-gap',gapId);node.setAttribute('aria-label',reason);
   node.classList.add('prototype-gap');node.style.minHeight=box.height+'px';
   gaps.push({id:gapId,view,key,reason,height:box.height,width:box.width});
 }
 function save(key){
   const board=document.getElementById('board');board.innerHTML=v1();
   const metrics=[...board.querySelectorAll('.biz-card')];metrics.forEach((el,i)=>el.dataset.metricIndex=String(i));
   board.querySelectorAll('.cockpit-primary-risk,.cockpit-small-risk').forEach(e=>blank(e,'landing-risk-card','缺少首页重点风险卡片组件和三卡布局元数据',key));
   board.querySelectorAll('.cockpit-process-node').forEach((e,i)=>{
     e.dataset.action=i<7?'stage:'+STAGE_IDS[i]:'unavailable:payment';
     blank(e,'process-node','缺少首页八节点风险链按钮组件／元数据',key);
   });
   board.querySelectorAll('.chainscroll').forEach(e=>blank(e,'helmet','交付头盔组件缺少与原型一致的双环、拓扑、几何和扇区配置',key));
   board.querySelectorAll('.ov-tile').forEach((e,i)=>{
     e.dataset.action='stage:'+STAGE_IDS[i];
     blank(e,'stage-tile','缺少运营节点入口卡片的独立组件及布局元数据',key);
   });
   board.querySelectorAll('.ov-card').forEach(e=>{if(e.querySelector('.ov-hd')?.textContent.includes('平均周期'))blank(e,'cycle-benchmark','缺少周期与标杆对照组件／元数据',key);});
   board.querySelectorAll('.ov-card').forEach(e=>{if(e.querySelector('.ov-hd b')?.textContent==='发货'){const cells=e.querySelectorAll('.ov-kpi');if(cells[3])blank(cells[3],'shipment-fulfillment','交付仅有三张发货指标卡，缺少订单履约率第四卡元数据',key);}});
   board.querySelectorAll('.sales-chart-wrap').forEach(e=>blank(e,'annual-chart','交付图表组件缺少原型逐柱预测配色、原型刻度与字体配置；保留原图尺寸空位',key));
   board.querySelectorAll('.tcard').forEach(e=>blank(e,'ai-card','缺少与原型风险／原因／建议卡片一一对应的组件及布局元数据；不展示固定AI结论',key));
   board.querySelectorAll('.biz-sales').forEach(e=>blank(e,'common-analysis','缺少共同问题分析说明区的组件与插槽布局',key));
   board.querySelectorAll('.srd-box,.srd-task,.story-actions').forEach(e=>blank(e,'special-analysis','交付未覆盖该专项分析／改善卡片与操作配置',key));
   board.querySelectorAll('svg').forEach(e=>{const r=e.getBoundingClientRect();if(r.width>120&&r.height>100)blank(e,'detail-chart','缺少与原型一致的细分图形渲染配置',key);});
   for(const el of board.querySelectorAll('*')){
     for(const a of [...el.attributes]){
       if(/^on/i.test(a.name)){
         if(a.name==='onclick'){
           const v=a.value;let action=null;
           if(v.includes('bizMetricClick'))action=v.includes('出货量')?'metric:volume':'metric:sales';
           else if(v==='openOperationsOverview()')action='route:operations';
           else if(v==='openShipRiskAnalysis()')action='route:analysis:shipment';
           else if(v.startsWith('chainNodeClick('))action='stage:'+STAGE_IDS[Number(v.match(/\d+/)?.[0])];
           else if(v.includes('月度口径'))action='unavailable:monthly';
           if(action)el.dataset.action=action;
           else if(el.matches('button')){el.disabled=true;el.setAttribute('aria-label','缺少动作配置：'+el.textContent);}
         }
         el.removeAttribute(a.name);
       }
       if(/^(src|href)$/i.test(a.name)&&/^(javascript:|https?:|file:)/i.test(a.value))el.removeAttribute(a.name);
     }
   }
   board.querySelectorAll('script,iframe,object,embed').forEach(e=>e.remove());
   board.querySelectorAll('.prototype-gap').forEach(e=>{
     const action=e.dataset.action;
     e.removeAttribute('disabled');
     if(!action)e.removeAttribute('data-action');
     e.setAttribute('role',action?'button':'presentation');
     if(action)e.tabIndex=0;
   });
   views[key]=board.innerHTML;
 }
 cockpitLanding=true;operationsOverviewOpen=false;save('overview');
 cockpitLanding=false;for(const name of ['销售额','出货量']){globalMetricPick=name;save(name==='销售额'?'overview-sales':'overview-volume');}
 operationsOverviewOpen=true;bizKpiPick=null;chainView='s1';chainActive=-1;save('operations');
 for(let i=0;i<7;i++){chainActive=i;save('operations-'+STAGE_IDS[i]);}
 bizKpiPick='销售额';chainView='sales';
 for(let i=0;i<4;i++){chainActive=i;save('analysis-'+['opportunity','bid','order','shipment'][i]);}
 return JSON.stringify({styles,views,gaps});
})()`;
const out=await send('Runtime.evaluate',{expression:expr,returnByValue:true});
if(out.exceptionDetails)throw Error(JSON.stringify(out.exceptionDetails));
const captured=JSON.parse(out.result.value);const raw=fs.readFileSync(source);
const {createHash}=await import('node:crypto');
const manifest={source:{file:source.split('/').at(-1),sha256:createHash('sha256').update(raw).digest('hex')},views:captured.views,gaps:captured.gaps};
const folder='bi_agent/web/static/cockpit/layout/';fs.writeFileSync(folder+'prototype.css',captured.styles);fs.writeFileSync(folder+'views.json',JSON.stringify(manifest,null,2)+'\n');console.log('captured',Object.keys(manifest.views).length,'views,',manifest.gaps.length,'empty slots');ws.close();
