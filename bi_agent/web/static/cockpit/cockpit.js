/* V3 cockpit: stable ProUI components, scoped data, main-service AI slots. */
(() => {
  'use strict';
  const root = document.querySelector('meta[name="app-root"]').content.replace(/\/$/, '');
  const base = `${root}/api/cockpit`;
  const saved = (()=>{try{return JSON.parse(localStorage.getItem('cockpit-v3-state')||'{}')}catch{return {}}})();
  const params = new URLSearchParams(location.search);
  const {createApp,ref,computed,watch,onMounted,onUnmounted} = Vue;
  const bi = window.ProUIBi;
  if (!bi?.ProBiDashboard || !bi?.ProMiniCpGraph) {
    document.getElementById('app').textContent='组件资源加载失败，请刷新或检查驾驶舱静态资源。';
    document.getElementById('app').removeAttribute('v-cloak');return;
  }
  const field=(identifierCode,label=identifierCode)=>({identifierCode,label,fieldType:'Indicator',valueConfig:{numericScale:1,isThousand:true}});
  const dimension=(identifierCode,label=identifierCode)=>({identifierCode,label,fieldType:'Dimension'});
  const app=createApp({setup(){
    const pages=[{id:'overview',name:'全局经营看板'},{id:'operations',name:'运营 360 整体分析'},{id:'analysis',name:'穿透式问题分析'}];
    const role=ref(['president','analyst'].includes(params.get('role'))?params.get('role'):saved.role||'president');
    if(!['president','analyst'].includes(role.value))role.value='president';
    const page=ref(pages.some(x=>x.id===location.hash.slice(1))?location.hash.slice(1):'overview');
    const period=ref(['2025-10','2025-09'].includes(saved.period)?saved.period:'2025-10');
    const department=ref(['全部产品部','AIDC产品部','国内电力产品部','国际电力产品部'].includes(saved.department)?saved.department:'全部产品部');
    const stage=ref(['opportunity','guidance','quotation','technical','bid','order','shipment'].includes(saved.stage)?saved.stage:'shipment');
    const metric=ref('sales'),config=ref({periods:['2025-10','2025-09'],departments:[]}),snapshot=ref(null),evidence=ref(null);
    const activeAnalysis=ref(null),loading=ref(false),error=ref(''),toast=ref(''),drawer=ref(''),showDefinitions=ref(false),selectedEvidence=ref(null);
    const history=ref([]),tasks=ref([]),task=ref(null),taskBusy=ref(false),taskFeedback=ref(''),causeFilter=ref(''),sectorLabel=ref(''),scenarioAmount=ref(0);
    const overviewRuntime=bi.createBiRuntime({runtimeKey:'cockpit-overview'}),analysisRuntime=bi.createBiRuntime({runtimeKey:'cockpit-analysis'});
    let epoch=0,pollTimer=null,toastTimer=null,disposed=false,analysisStartBusy='';
    const statusNames={queued:'等待分析',running:'分析中',completed:'已完成',failed:'失败',cancelled:'已停止',interrupted:'已中断'};
    const taskStatuses={draft:'草稿',issued:'已模拟下发',accepted:'已接收',review:'待验收',closed:'已验收关闭'};
    const pageTitle=computed(()=>pages.find(x=>x.id===page.value).name);
    const pageDescription=computed(()=>page.value==='overview'?'看清目标与实绩，聚焦影响经营达成的重要风险。':page.value==='operations'?'贯穿七个业务环节，定位进展、周期与异常项目。':'从风险到证据，从原因到措施，形成可执行的经营任务。');
    const currentStage=computed(()=>snapshot.value?.stages.find(x=>x.id===stage.value)||{});
    const stageName=computed(()=>currentStage.value.name||'');
    const isRunning=computed(()=>['queued','running'].includes(activeAnalysis.value?.status));
    const analysisStatus=computed(()=>statusNames[activeAnalysis.value?.status]||'待分析');
    const filteredRecords=computed(()=>(evidence.value?.records||[]).filter(x=>!causeFilter.value||x.cause===causeFilter.value));
    const fmt=n=>n==null?'—':Number(n).toLocaleString('zh-CN',{maximumFractionDigits:1});
    const date=t=>new Date(t*1000).toLocaleString('zh-CN',{hour12:false});
    const scenarioRate=computed(()=>{
      const m=snapshot.value?.metrics;if(!m)return '—';
      const amount=Math.min(Math.max(Number(scenarioAmount.value)||0,0),m.overdue);
      return ((m.actual+amount)/m.target*100).toFixed(1);
    });
    const recordColumns=computed(()=>[
      {code:'id',label:stage.value==='shipment'?'订单编号':'项目编号',valueType:'STRING'},
      {code:'customer',label:'客户',valueType:'STRING'},
      {code:'department',label:'产品部',valueType:'STRING'},
      ...(stage.value==='quotation'?[{code:'product',label:'型号',valueType:'STRING'},{code:'tier',label:'客户分级',valueType:'STRING'},{code:'region',label:'区域',valueType:'STRING'}]:[]),
      ...(['shipment','order'].includes(stage.value)?[{code:'amount',label:stage.value==='shipment'?'超期未发 / 亿元':'变更影响 / 亿元',valueType:'NUMBER',fieldType:'Indicator',formatConfig:{numericScale:1}}]:[]),
      {code:'overdueDays',label:'超期天数',valueType:'NUMBER',fieldType:'Indicator'},
      {code:'cause',label:'处理记录 / 主因',valueType:'STRING'},
      ...(stage.value==='shipment'?[{code:'commitment',label:'承诺发货日',valueType:'STRING'}]:[{code:'status',label:'当前状态',valueType:'STRING'}]),
    ]);
    function kpi(id,title,key,subKey,label,x){return {id,type:'kpiCard',title,position:{x,y:0,w:30,h:8},dataConfig:{measure:[field(key,title)],subMeasure:[field(subKey,label)]},styleConfig:{kpiValueColor:'#234dd8',kpiValueSuffix:metric.value==='volume'?' GWh':' 亿元'}};}
    const overviewComponents=computed(()=>{
      if(!snapshot.value)return [];const vol=metric.value==='volume';
      return [kpi('actual','累计实绩',vol?'volume':'actual','attainment','目标达成率 / %',0),
        kpi('target','年度目标',vol?'volumeTarget':'target',vol?'volumeGap':'gap','距年度目标',30),
        kpi('forecast','年度业务预测',vol?'forecastVolume':'forecast','forecastRate','预计达成率 / %',60),
        kpi('backlog','订未发',vol?'backlogVolume':'backlog',vol?'overdueVolume':'overdue','其中超期未发',90),
        {id:'monthly',type:'bar',title:vol?'月度出货量 · 目标与实绩 / GWh':'月度销售额 · 目标与实绩 / 亿元',position:{x:0,y:9,w:76,h:21},dataConfig:{categoryAxis:[dimension('month','月份')],valueAxis:[field('target','目标'),field('actual','实绩'),field('forecast','未来月业务预测')]},visualization:{displayLimit:0}},
        {id:'departments',type:'horizontal-bar',title:vol?'产品部年度出货达成 / GWh':'产品部年度销售达成 / 亿元',position:{x:76,y:9,w:44,h:21},dataConfig:{categoryAxis:[dimension('name','产品部')],valueAxis:[field('target','目标'),field('actual','实绩')]}}];
    });
    function resolveOverview(c){return async()=>{
      const s=snapshot.value,m=s.metrics,volume=metric.value==='volume',factor=volume?91/319:1;
      if(c.id==='monthly')return s.monthly.map(x=>({...x,actual:x.actual==null?null:x.actual*factor,target:x.target*factor,forecast:x.forecast==null?null:x.forecast*factor}));
      if(c.id==='departments')return s.departments.map(x=>({...x,target:x.target*factor,actual:x.actual*factor}));
      return [{...m,forecastRate:Number((m.forecast/m.target*100).toFixed(1)),volumeGap:m.gap*91/319,backlogVolume:m.backlog*91/319,overdueVolume:m.overdue*91/319}];
    };}
    const graphMeta=computed(()=>({id:'pipeline',type:'mini-cpgraph',title:'运营流程链',showHeader:false,graphConfig:{defaultActiveKey:stage.value}}));
    const graphData=computed(()=>{
      const ss=snapshot.value?.stages||[];
      const parts=s=>{
        const remaining=Math.max(0,s.total-s.done),late=s.id==='shipment'?snapshot.value.metrics.overdue:remaining*.35;
        return [[s.done,'success','normal','正常完成'],[late,'normal','error','逾期未完成'],[remaining-late,'normal','success','正常未完成']].map(([value,type,status,label])=>({value,type,status,label,formatterValue:fmt(value),formatConfig:{unit:s.unit,numericScale:1},indConfig:{dimensionValue:label}}));
      };
      return {nodes:ss.map(s=>({id:s.id,name:s.name,type:'stacked-bar-mini-node',dims:[dimension('status','状态')],meta:{basicInfo:{title:s.id==='quotation'?'申请单数':s.id==='bid'?'项目数':'金额',unit:s.unit},data:parts(s)}})),
        edges:ss.slice(1).map((s,i)=>({id:'edge-'+i,source:ss[i].id,target:s.id,type:'funnel-edge',name:'独立口径',value:.6,subLabels:[{code:'实际周期',value:s.cycle,unit:'天'},{code:'基线周期',value:s.baseline,unit:'天'}]}))};
    });
    const analysisComponents=computed(()=>{
      if(!snapshot.value)return [];
      const facts=evidence.value?.facts||[];
      const result=facts.map((f,i)=>({id:'fact-'+i,type:'kpiCard',title:f.label,position:{x:(i%3)*40,y:Math.floor(i/3)*8,w:40,h:7},dataConfig:{measure:[field('value',f.label)]},styleConfig:{kpiValueSuffix:' '+f.unit}}));
      result.push({id:'cause-chart',type:'horizontal-bar',title:stage.value==='shipment'?'超期未发 · 单一主因汇总 / 亿元':'当前环节异常记录分布 / 项',position:{x:0,y:Math.ceil(facts.length/3)*8,w:120,h:17},dataConfig:{categoryAxis:[dimension('name','原因')],valueAxis:[field('amount',stage.value==='shipment'?'金额':'记录数')]}});
      return result;
    });
    const insightSlots=[{id:'diagnosis',placement:{mode:'insert',afterId:'cause-chart',widthMode:'full'}}];
    function resolveAnalysis(c){return async()=>{
      if(c.id.startsWith('fact-'))return [{value:evidence.value?.facts[Number(c.id.slice(5))]?.value||0}];
      if(stage.value==='shipment')return evidence.value?.causes||[];
      const counts={};for(const r of evidence.value?.records||[])counts[r.cause]=(counts[r.cause]||0)+1;
      return Object.entries(counts).map(([name,amount])=>({name,amount}));
    };}
    function persist(){try{localStorage.setItem('cockpit-v3-state',JSON.stringify({role:role.value,period:period.value,department:department.value,stage:stage.value,analysisId:activeAnalysis.value?.id}))}catch{}}
    function notify(s){toast.value=s;clearTimeout(toastTimer);toastTimer=setTimeout(()=>toast.value='',4200);}
    async function api(path,options={}){
      const res=await fetch(base+path,{...options,headers:{'Content-Type':'application/json',...options.headers}});
      const body=await res.json();if(!res.ok)throw new Error(typeof body.detail==='string'?body.detail:'请求未完成，请检查输入或重试');return body;
    }
    function query(){return new URLSearchParams({period:period.value,department:department.value}).toString();}
    function context(){return {role:role.value,period:period.value,department:department.value,stage:stage.value};}
    function matches(a){return a&&a.context.role===role.value&&a.context.period===period.value&&a.context.department===department.value&&a.context.stage===stage.value&&a.context.snapshotId===snapshot.value?.snapshotId;}
    function clearPoll(){clearTimeout(pollTimer);pollTimer=null;}
    async function poll(aid,version){
      if(disposed||version!==epoch)return;
      try{const a=await api('/analyses/'+encodeURIComponent(aid));if(version!==epoch||!matches(a))return;activeAnalysis.value=a;persist();
        if(['queued','running'].includes(a.status))pollTimer=setTimeout(()=>poll(aid,version),1200);
      }catch(e){if(version===epoch){error.value=e.message;pollTimer=setTimeout(()=>poll(aid,version),4000);}}
    }
    async function loadEvidence(version=epoch){const e=await api('/evidence?'+query()+'&stage='+stage.value);if(version===epoch)evidence.value=e;}
    async function loadScope(auto=true){
      const version=++epoch;clearPoll();activeAnalysis.value=null;snapshot.value=null;evidence.value=null;causeFilter.value='';sectorLabel.value='';scenarioAmount.value=0;loading.value=true;error.value='';
      try{
        const s=await api('/snapshot?'+query());if(version!==epoch)return;snapshot.value=s;
        await loadEvidence(version);if(version!==epoch)return;
        await loadTasks();if(version!==epoch)return;
        if(auto&&page.value==='analysis')await startAnalysis(false,version);
      }catch(e){if(version===epoch)error.value=e.message;}finally{if(version===epoch)loading.value=false;persist();}
    }
    async function changeScope(){closeDrawer();await loadScope();const u=new URL(location.href);u.searchParams.set('role',role.value);window.history.replaceState(null,'',u);}
    async function refreshAll(){await loadScope();}
    async function navigate(id){page.value=id;location.hash=id;persist();if(id==='analysis'&&!matches(activeAnalysis.value)&&snapshot.value)await startAnalysis(false);}
    async function selectStage(id){if(stage.value===id)return;stage.value=id;const v=++epoch;clearPoll();activeAnalysis.value=null;evidence.value=null;causeFilter.value='';sectorLabel.value='';loading.value=true;
      try{await loadEvidence(v);if(v===epoch&&page.value==='analysis')await startAnalysis(false,v);}catch(e){if(v===epoch)error.value=e.message;}finally{if(v===epoch)loading.value=false;persist();}}
    function nodeClicked(node){const id=node?.id||node?.data?.id;if(config.value.stages?.some(x=>x.id===id))selectStage(id);}
    function sectorClicked(node){nodeClicked(node);sectorLabel.value='异常处理记录';}
    async function openRisk(id){if(stage.value!==id){stage.value=id;await loadScope(false);}await navigate('analysis');}
    async function startAnalysis(refresh=false,version=epoch){
      const requestKey=JSON.stringify(context());if(analysisStartBusy===requestKey||isRunning.value)return;analysisStartBusy=requestKey;error.value='';clearPoll();
      try{const a=await api('/analyses',{method:'POST',body:JSON.stringify({...context(),refresh})});if(version!==epoch||!matches(a))return;activeAnalysis.value=a;persist();if(['queued','running'].includes(a.status))poll(a.id,version);
      }catch(e){if(version===epoch)error.value=e.message;}finally{if(analysisStartBusy===requestKey)analysisStartBusy='';}
    }
    async function stopAnalysis(){try{const id=activeAnalysis.value.id,a=await api('/analyses/'+id+'/cancel',{method:'POST'});if(matches(a))activeAnalysis.value=a;clearPoll();}catch(e){notify(e.message);}}
    function openReport(){if(activeAnalysis.value?.status==='completed')window.open(base+'/analyses/'+activeAnalysis.value.id+'/report','_blank','noopener');}
    async function openHistory(){try{history.value=await api('/analyses?role='+role.value);drawer.value='history';}catch(e){notify(e.message);}}
    async function restoreAnalysis(a){
      closeDrawer();period.value=a.context.period;department.value=a.context.department;stage.value=a.context.stage;page.value='analysis';location.hash='analysis';await loadScope(false);
      const restored=await api('/analyses/'+a.id);if(matches(restored)){activeAnalysis.value=restored;persist();if(isRunning.value)poll(a.id,epoch);}else notify('该记录属于旧数据快照，请重新分析');
    }
    async function loadTasks(){tasks.value=await api('/tasks');}
    async function openTasks(){try{await loadTasks();drawer.value='tasks';}catch(e){notify(e.message);}}
    function editTask(t){task.value=JSON.parse(JSON.stringify(t));taskFeedback.value='';drawer.value='task';}
    async function createDraft(){try{const t=await api('/analyses/'+activeAnalysis.value.id+'/draft',{method:'POST'});editTask(t);await loadTasks();}catch(e){notify(e.message);}}
    async function taskAction(action){
      if(taskBusy.value)return false;taskBusy.value=true;
      try{const t=task.value;task.value=await api('/tasks/'+encodeURIComponent(t.id),{method:'POST',body:JSON.stringify({role:role.value,revision:t.revision,action,title:t.title,goal:t.goal,measures:t.measures,feedback:taskFeedback.value})});await loadTasks();notify(action==='issue'?'任务已模拟下发，未发送真实通知':'已保存');return true;
      }catch(e){notify(e.message);return false;}finally{taskBusy.value=false;}
    }
    async function confirmIssue(){if(await taskAction('save'))await taskAction('issue');}
    function showEvidence(id){selectedEvidence.value=(activeAnalysis.value?.evidence?.evidence||[]).find(x=>x.id===id)||null;}
    function scrollEvidence(){document.getElementById('evidence-section')?.scrollIntoView({behavior:'smooth',block:'start'});}
    function closeDrawer(){drawer.value='';showDefinitions.value=false;selectedEvidence.value=null;}
    async function copyContext(){
      const text=`请分析${period.value} ${department.value} ${stageName.value}。当前角色：分析员；数据：POC演示；快照：${snapshot.value?.snapshotId}。${activeAnalysis.value?'分析ID：'+activeAnalysis.value.id:''} 请区分事实、假设和建议。`;
      try{await navigator.clipboard.writeText(text);notify('已复制，可粘贴到 Fuxi 对话；不会自动发送');}catch{notify('浏览器不支持剪贴板，请在 Fuxi 中说明当前期间、范围和环节');}
    }
    const hashChanged=()=>{const id=location.hash.slice(1);if(pages.some(x=>x.id===id)&&page.value!==id)navigate(id);};
    onMounted(async()=>{
      try{config.value=await api('/bootstrap');await loadScope(false);
        if(page.value==='analysis'){
          if(saved.analysisId){try{const a=await api('/analyses/'+saved.analysisId);if(matches(a)){activeAnalysis.value=a;if(isRunning.value)poll(a.id,epoch);}}catch{}}
          if(!activeAnalysis.value)await startAnalysis(false);
        }
      }catch(e){error.value=e.message;}
      window.addEventListener('hashchange',hashChanged);
    });
    onUnmounted(()=>{disposed=true;clearPoll();clearTimeout(toastTimer);window.removeEventListener('hashchange',hashChanged);});
    watch([role,period,department,stage],persist);
    return {pages,role,page,period,department,stage,metric,config,snapshot,evidence,activeAnalysis,loading,error,toast,drawer,showDefinitions,selectedEvidence,history,tasks,task,taskBusy,taskFeedback,causeFilter,sectorLabel,scenarioAmount,scenarioRate,statusNames,taskStatuses,pageTitle,pageDescription,currentStage,stageName,isRunning,analysisStatus,filteredRecords,recordColumns,overviewRuntime,analysisRuntime,overviewComponents,resolveOverview,graphMeta,graphData,analysisComponents,insightSlots,resolveAnalysis,fmt,date,navigate,changeScope,refreshAll,selectStage,nodeClicked,sectorClicked,openRisk,startAnalysis,stopAnalysis,openReport,openHistory,restoreAnalysis,openTasks,editTask,createDraft,taskAction,confirmIssue,showEvidence,scrollEvidence,closeDrawer,copyContext};
  }});
  ['ProBiDashboard','ProMiniCpGraph','ProDataTableAtomic'].forEach(name=>app.component(name,bi[name]));
  app.config.errorHandler=(e)=>{console.error('cockpit component error',e);};
  app.mount('#app');
})();
