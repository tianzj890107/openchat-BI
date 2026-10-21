"""Compile delivered layout metadata against explicitly bound V3 demo fixtures.

Source JSON is immutable. No AP purchase query or synthetic fallback is run.
Every runtime override and unavailable binding is returned in the gap report.
"""
from __future__ import annotations
import json
import re
from copy import deepcopy
from pathlib import Path
from .data import NAMES

ROOT=Path(__file__).resolve().parents[1]/'web/static/cockpit/metadata/iba-demo-1021'
FIXTURE=Path(__file__).parent/'fixtures/v3-prototype.json'
PAGE_IDS={'overview':'2112001069107167233','operations':'2112434004503347202','analysis':'2112061604959928321'}
OPS_NODES=dict(zip(NAMES,['2109848488855519233','2109848488910045186','2112022555167604737','2109848488914239490','2109848488918433794','2109848488926822401','2109848488926822402']))
RISK_NODES=dict(zip(['opportunity','bid','order','shipment'],['2109840325158682625','2109840573985767425','2109840573998350338','2109840696539136002']))
STAGE_TEMPLATES={'opportunity':'2112026770145329154','guidance':'2112059168287408129','quotation':'2112059463654490114','technical':'2112059620722786305','bid':'2112059751740260354','order':'2112060211964461057','shipment':'cockpit-shipment-operations'}
RISK_TEMPLATES={'opportunity':'2112062888320483329','bid':'2112059751740260354','order':'2112064105591390209','shipment':'2112064144187375617'}
CONTAINERS={'template','tab-container','group','segmented-strip','title','button-group','composite-filter'}

def prototype():return json.loads(FIXTURE.read_text())
def text(value):return re.sub('<[^>]+>','',str(value)).replace('&nbsp;',' ')
def field(key,label,unit=''):return dict(identifierCode=key,label=label,fieldType='Indicator',valueConfig=dict(numericScale=1,isThousand=True),unit=unit)
def dim(key,label):return dict(identifierCode=key,label=label,fieldType='Dimension')
def rows_table(headers,rows):return [dict(zip([f'f{i}' for i in range(len(headers))],[text(v) for v in row])) for row in rows]

def ring_for(p,stage,risk=False):
    if risk:return p[{'opportunity':'PROJ_RING','bid':'SALES_BID_RING','order':'SALES_ORDER_RING','shipment':'SALES_SHIP_RING'}[stage]]
    return p[{'opportunity':'S1_OPP_RING','order':'S1_ORDER_RING','shipment':'S1_SHIP_RING'}[stage]] if stage in {'opportunity','order','shipment'} else p['S1_STAGE_RINGS'][NAMES[stage]]

def ring_rows(ring):
    out=[]
    for group in ring['groups']:
        for seg in group.get('segs',[]):out.append(dict(name=group['n']+' · '+seg['g'] if group['n']!=seg['g'] else seg['g'],value=seg.get('v',0),group=group['n']))
    return out

def graph(p,risk=False):
    ids=RISK_NODES if risk else OPS_NODES
    nodes=[]
    for sid,node_id in ids.items():
        ring=ring_for(p,sid,risk);unit='亿元' if risk and sid in {'opportunity','bid'} else 'GWh'
        data=[dict(label=r['name'],value=r['value'],formatterValue=str(r['value']),formatConfig=dict(unit=unit,numericScale=1),indConfig=dict(dimensionValue=r['name'])) for r in ring_rows(ring)]
        nodes.append(dict(id=node_id,name=NAMES[sid],type='pie-mini-node',dims=[dim('status','原型业务状态')],meta=dict(basicInfo=dict(title='金额' if unit=='亿元' else '电量',unit=unit),data=data)))
    return dict(nodes=nodes,edges=[dict(id='v3-'+str(i),source=nodes[i]['id'],target=nodes[i+1]['id'],type='funnel-edge',name='',value=.6) for i in range(len(nodes)-1)])


def build_bundle():
    p=prototype();source=json.loads((ROOT/'template-registry.json').read_text());registry=deepcopy(source)
    roots=json.loads((ROOT/'components.json').read_text());datasets={};bindings={};gaps=[];overrides=[]
    def issue(code,description,**kw):gaps.append(dict(code=code,description=description,**kw))
    def bind(c,tid,data,config=None,title=None,columns=None):
        key=tid+'/'+c['id'];c['cockpitBindingKey']=key
        c['dataConfig']={'sourceType':'request',**(config or {})}
        if title is not None:c['title']=title
        if columns is not None:c['tableColumnConfig']=columns
        datasets[key]=data;bindings[key]=dict(templateId=tid,componentId=c['id'],title=c['title'],type=c['type'],fixture=p['_source']['sha256'])
    def kpi(c,tid,title,value,unit=''):
        bind(c,tid,[dict(value=value)],dict(measure=[field('value',title)]),title)
        c.setdefault('styleConfig',{})['kpiValueSuffix']=' '+unit
    def table(c,tid,headers,rows,title=None):
        columns=[dict(code=f'f{i}',label=text(label),valueType='STRING',fieldType='BusinessAttribute',showSource=True) for i,label in enumerate(headers)]
        bind(c,tid,rows_table(headers,rows),dict(tableFields=[dim(x['code'],x['label']) for x in columns]),title,columns)
        c.setdefault('styleConfig',{})['autoHeight']=True
    def chart(c,tid,data,labels=('name','value'),series=None):
        config=dict(categoryAxis=[dim(labels[0],labels[0])],valueAxis=[field(labels[1],labels[1])])
        if series:config['valueAxis']=[field(k,l) for k,l in series]
        bind(c,tid,data,config)
        c.setdefault('visualization',{})['displayLimit']=0
    def array_table(c,tid,array,title=None):table(c,tid,array[0],array[1:],title)

    sales_ids=['kpiCard-4ixysjkn','kpiCard-lhq115j7','kpiCard-ya7bp5lj','kpiCard-cc868izo','kpiCard-xof3pdoj']
    sales_values=[('年度销售目标',319,'亿元'),('年度销售实绩',191.4,'亿元'),('年度销售达成率',60,'%'),('预计年销售额',280,'亿元'),('预计年销售达成率',round(280/319*100,1),'%')]
    volume_ids=['kpiCard-zcuylwjq','kpiCard-2y08ml3i','kpiCard-2umsa334','kpiCard-br6xwau0','kpiCard-sbwfb1zy','kpiCard-s6l8tg6j','kpiCard-csgntrwh']
    volume_values=[('年度出货量目标',91,'GWh'),('出货量实绩',54.6,'GWh'),('出货达成率',60,'%'),('年度时间消耗',78.4,'%'),('还可出货量',25.3,'GWh'),('预计出货量',79.9,'GWh'),('预计出货达成率',87.8,'%')]
    kpimap=dict(zip(sales_ids,sales_values))|dict(zip(volume_ids,volume_values))
    annual=p['SALES_ANNUAL'];conversion=91/319
    monthly=[dict(name=m,target=annual['monthlyTarget'][i],actual=annual['monthlyActual'][i],rate=round(annual['monthlyActual'][i]/annual['monthlyTarget'][i]*100,1)) for i,m in enumerate(annual['months'])]
    teams=[dict(name=n,target=annual['teamTarget'][i],actual=annual['teamActual'][i],rate=round(annual['teamActual'][i]/annual['teamTarget'][i]*100,1)) for i,n in enumerate(annual['teams'])]
    product=[dict(name=n,cell=annual['cell'][i],pack=annual['pack'][i],other=annual['other'][i]) for i,n in enumerate(annual['productMonths'])]
    volume_months=[dict(name=n,target=annual['monthlyTarget'][i]*conversion,actual=(annual['productActual'][i] if i<len(annual['productActual']) else 0)*conversion,forecast=annual['monthlyActual'][i]*conversion) for i,n in enumerate(annual['months'])]
    volume_teams=[dict(name=n,target=annual['teamTarget'][i]*conversion,actual=annual['teamActual'][i]*conversion,forecast=next(float(r[2]) for r in p['PROJ_MONEY'][1:] if r[0]==n)*conversion) for i,n in enumerate(annual['teams'])]
    # Explicit bindings by template/component identity, never by purchase metric code.
    annual_charts={
        'bar-line-stx32yim':(monthly,False),'bar-line-swk58lta':(teams,False),
        'bar-uvogx9g6':(teams,True),'bar-nfodriiq':(monthly,True)}
    for tid,t in registry.items():
        for c in t['components']:
            cid=c['id'];kind=c['type']
            if cid in kpimap:kpi(c,tid,*kpimap[cid]);continue
            if kind=='progress':
                if tid==PAGE_IDS['analysis'] and cid=='progress-zkznh2kf':c['title']='提升盈利 ｜ 净利率'
                name=next((x for x in p['BIZ_KPI'] if x[0] in c['title']),None)
                if not name and '应收周转' in c['title']:name=p['BIZ_KPI'][-1]
                if name:
                    bind(c,tid,[dict(current=name[1],target=name[3])],dict(measure=[field('current','实绩')],target=[field('target','目标')]),c['title'])
                    if name[4]=='down':c.setdefault('styleConfig',{}).update(surplusLabel='超目标（越低越好）',surplusBarColor='#ef4444',surplusTextColor='#ef4444')
                    continue
            if kind=='mini-cpgraph':
                risk=tid==PAGE_IDS['analysis'];bind(c,tid,graph(p,risk));c['cockpitGraphData']=datasets[tid+'/'+cid]
                c['graphConfig']['defaultActiveKey']=(RISK_NODES if risk else OPS_NODES)['shipment' if risk else 'opportunity']
                c['graphConfig'].pop('processCode',None)
                for rule in c['graphConfig'].get('graphTemplateSwitchRules',[]):
                    sid=next((s for s,n in (RISK_NODES if risk else OPS_NODES).items() if n==rule['nodeId']),None)
                    if sid:rule['templateId']=(RISK_TEMPLATES if risk else STAGE_TEMPLATES)[sid]
                overrides.append(dict(componentId=cid,reason='使用原型业务状态图；修正无效默认节点和发货目标模板；不调用未配置的远程拓扑接口'))
                continue
            if cid in annual_charts:
                raw,volume=annual_charts[cid];data=deepcopy(raw)
                if volume:
                    data=deepcopy(volume_months if cid=='bar-nfodriiq' else volume_teams)
                    if cid=='bar-nfodriiq':
                        for i,row in enumerate(data):
                            if i<9:row['forecast']=0
                if kind=='bar-line':
                    bind(c,tid,data,dict(categoryAxis=[dim('name','月份' if raw is monthly else '产品部')],leftAxis=[field('target','目标'),field('actual','实绩／预测')],rightAxis=[{**field('rate','达成率'),'seriesType':'line'}]))
                else:chart(c,tid,data,series=[('target','目标'),('actual','实绩'),('forecast','业务预测')])
                continue
            if cid=='bar-tebs5kjx':chart(c,tid,product,series=[('cell','电芯'),('pack','PACK'),('other','其他')]);continue
            if cid in {'table-54yeopj2','table-6teuq4qa','table-j282l5b0','table-3qcm5ah3'}:
                data=teams if cid in {'table-6teuq4qa','table-j282l5b0'} else monthly
                vol=tid=='2112010750949113858';unit='GWh' if vol else '亿元'
                if vol:
                    data=volume_teams if cid=='table-j282l5b0' else volume_months
                    headers=['分类']+[x['name'] for x in data]+['合计']
                    items=[['出货量目标']+[f"{x['target']:.2f}" for x in data]+['91.00'],['出货量实绩']+[f"{x['actual']:.2f}" for x in data]+['54.60'],['出货达成率']+[f"{x['actual']/x['target']*100:.1f}%" for x in data]+['60.0%'],['出货实绩／预测']+[f"{x['forecast']:.2f}" for x in data]+[f"{sum(x['forecast'] for x in data):.2f}"]]
                    if cid=='table-j282l5b0':
                        items[3:]=[['还可出货量']+[f"{x['forecast']-x['actual']:.2f}" for x in data]+[f"{sum(x['forecast'] for x in data)-54.6:.2f}"],['预计出货量']+[f"{x['forecast']:.2f}" for x in data]+[f"{sum(x['forecast'] for x in data):.2f}"],['预计出货达成率']+[f"{x['forecast']/x['target']*100:.1f}%" for x in data]+[f"{sum(x['forecast'] for x in data)/91*100:.1f}%"]]
                    table(c,tid,headers,items);continue
                table(c,tid,['产品部／月份','目标 / '+unit,'实绩／预测 / '+unit,'达成率 / %'],[[x['name'],round(x['target']*(conversion if vol else 1),2),round(x['actual']*(conversion if vol else 1),2),x['rate']] for x in data]);continue
            if cid=='table-ys9za5oh':table(c,tid,['月份','电芯 / 亿元','PACK / 亿元','其他 / 亿元'],[[x['name'],x['cell'],x['pack'],x['other']] for x in product]);continue
            if cid in {'horizontal-bar-cuksxfkt','horizontal-bar-izawt6gf'} or (tid=='2112060211964461057' and kind=='horizontal-bar'):
                chart(c,tid,[dict(name=x[0],value=x[1]) for x in p['ORDER_PRODUCTS' if '产品' in c['title'] else 'ORDER_CUSTOMERS']]);continue
            if tid=='2112060211964461057' and kind=='table':
                pending=[r for r in p['NODE_PROJ']['合同签订'] if r[0] in {'P61','P62','P63','P64'}]
                table(c,tid,['项目','客户','中标金额 / 亿元','电量 / GWh','下一步'],[[r[0],r[1],r[3]/10000,round(r[3]/10000*91/319,1),'完成合同条款确认与签署'] for r in pending]);continue
            if tid=='2112059751740260354' and kind in {'kpiCard','share-bar'}:
                ring=ring_for(p,'bid')
                if kind=='share-bar':chart(c,tid,ring_rows(ring));continue
                items=[('总电量',37.6),('已完成',8.9),('进行中',28.7)]
                siblings=[z['id'] for z in t['components'] if z['type']=='kpiCard'];kpi(c,tid,*items[siblings.index(cid)],'GWh');continue
            if cid=='table-nu6hm1ge':
                items=[]
                for team in volume_teams:
                    targets=[m['target']*team['target']/91 for m in volume_months]
                    actuals=[m['actual']*team['actual']/54.6 for m in volume_months]
                    items.extend([[team['name']+' · 目标']+[f'{v:.2f}' for v in targets]+[f"{team['target']:.2f}"],[team['name']+' · 实绩']+[f'{v:.2f}' for v in actuals]+[f"{team['actual']:.2f}"],[team['name']+' · 达成率']+[f'{a/t*100:.1f}%' for a,t in zip(actuals,targets)]+[f"{team['actual']/team['target']*100:.1f}%"]])
                table(c,tid,['团队／指标']+annual['months']+['合计'],items)
                continue
            if cid=='template-rjjcf4v1':c['baseConfig']={'defaultTemplateId':STAGE_TEMPLATES['opportunity']}
            if cid=='template-ryfsat5y':c['baseConfig']={'defaultTemplateId':RISK_TEMPLATES['shipment']}
            if cid=='funnel-qexcz5h3':
                chart(c,tid,[dict(name=n['n'],value=n['tot']) for n in p['S1_NODES_A']]);continue
            # Operations summary cards inherit the parent group, not arbitrary IDs.
            parent=c.get('parentId');stage_by_group={'group-tpr32caj':'guidance','group-ftrsjcmy':'quotation','group-wraxt9z6':'technical','group-4croqift':'bid','group-fbf8l4il':'order','group-f70etg8b':'shipment'}
            sid=stage_by_group.get(parent)
            if sid and kind in {'kpiCard','share-bar'}:
                ring=ring_for(p,sid);values=ring_rows(ring);unit='GWh'
                if kind=='share-bar':
                    if sid in {'guidance','quotation','technical'}:values=[dict(name=z['g'],value=z['v']) for z in ring['groups'][1]['segs']]
                    elif sid=='order':values=[dict(name='已签单',value=236),dict(name='已中标未签单',value=8)]
                    elif sid=='shipment':values=[dict(name='正常订未发',value=15.3),dict(name='计划外发货',value=5),dict(name='超期订未发',value=24.3)]
                    chart(c,tid,values);continue
                siblings=[z for z in t['components'] if z.get('parentId')==parent and z['type']=='kpiCard'];idx=[z['id'] for z in siblings].index(cid)
                group_values=[(g['n'],g.get('v',sum(z.get('v',0) for z in g.get('segs',[])))) for g in ring['groups']]
                candidates=[('总电量',sum(v for _,v in group_values))]+group_values
                if sid in {'guidance','quotation','technical'}:candidates=group_values+[(ring['groups'][1]['segs'][0]['g'],ring['groups'][1]['segs'][0]['v'])]
                elif sid=='bid':candidates=[('已完成',8.9),('进行中',28.7),('中标',3.7)]
                elif sid=='order':
                    label,value,unit=[('已签单',236,'亿元'),('已中标未签单',8,'亿元'),('待签单占比',3.3,'%')][idx];kpi(c,tid,label,value,unit);continue
                elif sid=='shipment':candidates=[('已发货',54.6),('未发货',12.7),('出货目标达成率',60)]
                label,value=candidates[min(idx,len(candidates)-1)];kpi(c,tid,label,value,'%' if sid=='shipment' and idx==2 else unit);continue
            # Node-specific operations detail templates.
            sid=next((s for s,dtid in STAGE_TEMPLATES.items() if tid==dtid),None)
            if sid and kind in {'horizontal-bar','table'}:
                deep=p['S1_STAGE_DEEP'].get(NAMES[sid])
                if sid=='opportunity':
                    if kind=='table':table(c,tid,p['OPP_HEAD'],p['OPP_ROWS'],'商机明细');continue
                    if '产品' in c['title']:chart(c,tid,[dict(name=g['n'],value=g['amtV']) for g in p['PROJ_RING']['groups']]);continue
                    chart(c,tid,[dict(name=x[0],value=x[1]) for x in p['OPPORTUNITY_CUSTOMERS']]);continue
                if deep:
                    if kind=='horizontal-bar':chart(c,tid,[dict(name=x[0],value=x[-1]) for x in deep['products' if '产品' in c['title'] else 'customers']]);continue
                    table(c,tid,['项目','客户','产品／产品部','电量 / GWh','异常','处理措施'],deep['exceptions']);continue
            if tid=='2112062888320483329':
                if cid=='table-ilzta6h7':array_table(c,tid,p['SD']['proj'][1]);continue
                if cid=='table-qx1k3riz':array_table(c,tid,p['PROJ_MONEY']);continue
                if cid=='table-8uc5pvas':table(c,tid,p['OPP_HEAD'],p['OPP_ROWS']);continue
                if cid=='horizontal-bar-i2gi98l6':chart(c,tid,[dict(name=x[0],value=float(x[2])) for x in p['PROJ_MONEY'][1:-1]]);continue
                if kind=='kpiCard':
                    ids=['kpiCard-xewwlgmz','kpiCard-qeic86rz','kpiCard-r3h38ebc'];values=[('商机预测',280,'亿元'),('目标缺口',39,'亿元'),('未签单商机',70,'亿元')]
                    kpi(c,tid,*values[ids.index(cid)]);continue
            if tid=='2112064144187375617':
                if kind=='share-bar':chart(c,tid,[dict(name='正常订未发',value=15.3),dict(name='超期订未发',value=24.3)]);continue
                if kind=='table':table(c,tid,['订单','客户／分级','产品部','超期未发 / 亿元','天数','主因','具体根因','承诺发货日'],[[r['so'],r['cust'],r['biz'],r['amt'],r['days'],r['cause'],r['detail'],r['promise']] for r in p['SHIP_EXEC_ROWS']]);continue
            if tid=='2112064105591390209':
                table(c,tid,['订单','客户','产品','类型','影响电量 / GWh','金额 / 亿元','原因','措施'],[[r[k] for k in ['id','customer','product','type','gwh','amt','cause','action']] for r in p['SALES_ORDER_RISK_ROWS']]);continue
            if kind=='table' and cid=='table-jmrpjwsj':
                array_table(c,tid,p['CUSTOMER_GRADE']);continue
            if cid in {'horizontal-bar-cuksxfkt','horizontal-bar-izawt6gf'}:
                deep=p['S1_STAGE_DEEP'].get('订单接收')
                if deep:chart(c,tid,[dict(name=x[0],value=x[-1]) for x in deep['products' if '产品' in c['title'] else 'customers']]);continue
    issue('MISSING_INTERACTIONS','交付未包含红区报价专项跳转、毛利率／净利率／回款明细、年度／月度独立状态、图表下钻与客户操作列动作；只启用可核对的销售额／出货量切换及节点模板切换。其他交互仍缺对应模板、动作契约和数据')
    issue('LAYOUT_DIFFERENCE','交付采用120列画布布局，与原型HTML的折叠块、卡片密度、分页、配色和宿主侧栏不完全相同；当前保留元数据布局，尚缺与原型一致的完整布局及主题配置；运营页还缺周期／标杆对照组件和发货第四项订单履约率卡片')
    issue('VOLUME_CONVERSION','原型部分电量展示按91／319由金额折算；当前沿用该原型规则，不视为真实电量实绩。月度达成10–12月包含预测，不能与累计实绩直接相加')
    overview=registry[PAGE_IDS['overview']]['components']
    bottom=max(c['position']['y']+c['position']['h'] for c in overview if not c.get('parentId'))
    overview.append(dict(id='cockpit-prototype-risks',type='cockpit-risk-list',title='重要经营风险',position=dict(x=0,y=bottom+1,w=120,h=36),
        risks=[dict(level=r[0],summary=r[1],metric=r[2],category=r[3],stage={'出货':'shipment','投标':'bid','订单签单':'order','订单变更':'order','技术方案':'technical'}.get(r[3]),missing=r[4]=='price') for r in p['RISKS']]))
    overrides.append(dict(componentId='cockpit-prototype-risks',reason='交付未含首页风险列表；保留原型7条风险文案，使用宿主只读卡片补充，不调用任务令写接口'))
    # Reuse delivered shipment detail and volume annual metadata, rather than a wrong target.
    ship=deepcopy(registry['2112064144187375617']['components']);height=max(c['position']['y']+c['position']['h'] for c in ship)
    ship.append(dict(id='cockpit-shipment-annual',type='template',title='年度出货',position=dict(x=0,y=height,w=120,h=40),baseConfig=dict(defaultTemplateId='2112010750949113858')))
    registry[STAGE_TEMPLATES['shipment']]=dict(templateId=STAGE_TEMPLATES['shipment'],meta=dict(name='发货履约与年度出货（交付组件组合）'),components=ship)
    # Fill genuinely missing source cells with a visible gap, never a guessed chart.
    for tid,t in list(registry.items()):
        ids={c['id'] for c in t['components']}
        for c in list(t['components']):
            for child in c.get('children',[]):
                if child not in ids:
                    t['components'].append(dict(id=child,type='cockpit-gap',title='交付元数据缺失组件',parentId=c['id'],gap='缺少 '+child+' 的定义，无法按原型渲染'))
                    issue('CHILD_DEFINITION_MISSING','缺少 '+child+' 的组件定义',templateId=tid,componentId=child)
    for tid,t in registry.items():
        for c in t['components']:
            key=c.get('cockpitBindingKey',tid+'/'+c['id'])
            if c['type'] not in CONTAINERS|{'cockpit-gap','cockpit-risk-list'} and key not in datasets:
                c['cockpitBindingKey']=key;c['dataConfig']={'sourceType':'request'}
                datasets[key]={'data':None,'error':'此组件缺少与原型一致的数据或字段配置，见差异清单'}
                issue('DATA_BINDING_MISSING','缺少原型一致的数据／字段配置：'+c['title'],templateId=tid,componentId=c['id'])
    issue('PROTOTYPE_CONFLICT','原型同时存在订未发44.6／39.6／45.0亿元及2025／2026时点；当前保留各页面原文口径，尚缺统一业务快照')
    issue('AP_BINDINGS_CONFLICT','交付AP中采购金额、采购时间维度与经营标题不符；当前显式绑定原型演示数据，真实指标编码与数据源尚缺')
    issue('GRAPH_RENDER_DIFFERENCE','交付缺少静态头盔拓扑；以原型分类值和源节点ID重建业务环图。ProUI图形几何、内外环与原型手绘头盔不能逐像素一致')
    issue('PRICE_TEMPLATE_MISSING','交付缺少红区报价专项模板、原因与改善专题布局；当前只保留报价环节明细和分析／任务抽屉，不能直接还原红区报价专项页面')
    issue('PLATFORM_SHELL_EXCLUDED','原型外围Fuxi聊天／联系人／专家界面由宿主负责；cockpit保持无独立聊天区')
    # Source slot embed paths contain the original outer Tab; page roots are mounted directly.
    slots=json.loads((ROOT/'insights.json').read_text())
    for slot in slots:slot['embedPath']['segments']=slot['embedPath']['segments'][1:]
    return dict(pages=PAGE_IDS,roots=roots,templates=registry,datasets=datasets,bindings=bindings,insights=slots,
        nodeStages={v:k for k,v in (OPS_NODES|{}).items()}|{v:k for k,v in RISK_NODES.items()},
        gaps=gaps,overrides=overrides,sourceMode='prototype',source=p['_source'])
