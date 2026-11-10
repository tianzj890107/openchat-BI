"""Opt-in real-model replay of published frozen records; never refresh production.

This is a bounded evidence-subset canary, not full AP or end-to-end acceptance.
No model runs on import. Explicit --allow-model and a report path are required.
"""
from __future__ import annotations
import argparse
from collections import OrderedDict
from contextlib import contextmanager
import json
from pathlib import Path
import re
import tempfile
import threading
import time
import urllib.request

STAGES = ('opportunity','order','shipment','combined','bid','quotation')


def replay_queries(evidence):
    groups = OrderedDict()
    for record in evidence.get('records') or []:
        scope=record.get('scope') or {}
        request=scope.get('request')
        row=record.get('data')
        if not isinstance(request,dict) or not isinstance(row,dict):continue
        key=json.dumps(request,ensure_ascii=False,sort_keys=True)
        output=groups.setdefault(key,{'request':request,'columns':{},'rows':[]})
        normalized={}
        for label,value in row.items():
            match=re.search(r'\[([^\]]+)\]$',label)
            if not match:continue
            code=match[1]
            output['columns'][code]={'identifierCode':code,'label':label.rsplit(' :: ',1)[-1].rsplit('[',1)[0]}
            normalized[code]={'value':value}
        if normalized:output['rows'].append(normalized)
    return [dict(request=g['request'],response={'result':{'columns':list(g['columns'].values()),'rows':g['rows']}})
            for g in groups.values() if g['rows']]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sources_arg=parser.add_mutually_exclusive_group(required=True)
    sources_arg.add_argument('--source-url')
    sources_arg.add_argument('--source-file')
    parser.add_argument('--capture-source')
    parser.add_argument('--output',required=True)
    parser.add_argument('--repeat',type=int,default=3,choices=range(1,6))
    parser.add_argument('--stages',nargs='+',choices=STAGES,default=list(STAGES))
    parser.add_argument('--allow-model',action='store_true')
    args=parser.parse_args()
    if not args.allow_model:parser.error('--allow-model is required; this command spends model tokens')
    from dotenv import load_dotenv
    load_dotenv(Path.cwd()/'.env',override=False)
    import os
    os.environ['COCKPIT_REFRESH_ENABLED']='0'
    os.environ['LLM_PROVIDER']='team'
    os.environ['TEAM_MODEL']='direct-deepseek-v4-flash'
    import bi_agent.web.app as web
    from bi_agent.cockpit.store import Store
    from bi_agent.cockpit.dashboard_source import RELEASE, page_analysis_context
    from bi_agent.cockpit.main_service import run_main_analysis
    from bi_agent.cockpit.cards import TOOL, REPAIR_TOOL
    from bi_agent.concurrency import SessionSlotRegistry, AdmissionController, get_limits
    from open_claude.agent_def import AgentDef
    from openai import OpenAI
    from bi_agent.llm import provider_team
    provider_team.OpenAI=lambda **kw:OpenAI(**kw,timeout=90,max_retries=0)
    frozen=[]
    if args.source_file:
        frozen=json.loads(Path(args.source_file).read_text())
    else:
        for stage in args.stages:
            url=args.source_url.rstrip('/')+'/api/cockpit/ai-publications/stages/'+stage+'/evidence?id=1&format=json'
            frozen.append({'stage':stage,'publication':json.load(urllib.request.urlopen(url,timeout=30))})
    if args.capture_source:
        path=Path(args.capture_source);path.write_text(json.dumps(frozen,ensure_ascii=False));path.chmod(0o600)
    sources=[(r['stage'],r['publication'],replay_queries(r['publication'].get('evidence') or {}))
             for r in frozen if r['stage'] in args.stages]
    cases=[]
    with tempfile.TemporaryDirectory(prefix='cockpit-model-canary-') as temporary:
        web.STATE.cwd=temporary
        web.STATE.agent_def=AgentDef('cockpit-canary',tools=[],model='team-configured')
        web.STATE.sessions={};web.STATE.source_contexts={}
        web.STATE.session_slots=SessionSlotRegistry()
        web.STATE.admission=AdmissionController(get_limits())
        store=Store(Path(temporary)/'dataset/cockpit/history.sqlite3')
        for stage,raw,queries in sources:
            if not queries:
                cases.append(dict(stage=stage,status='no_replayable_records',modelCalls=0))
                continue
            receipts=[store.save_ap_result(1,'analysis',q['request'],q['response'],3600,'offline-replay','canary','frozen-record-subset') for q in queries]
            request=dict(id=1,engine='main',source='service',page='analysis',stage=stage,defaultView=True,
                period=raw.get('period') or '2026',department='全部产品部',filters={},chartSnapshotId=RELEASE,
                chartQueries=[json.dumps(q['request'],ensure_ascii=False,sort_keys=True) for q in queries],
                apReceiptIds=[r['id'] for r in receipts],unavailableQueries=[],
                clarifications={'instruction':'本轮为已发布证据的冻结记录子集回放，不是实时取数；仅分析保留样本，不能外推总体。'})
            resolved=page_analysis_context(request,store,data_mode='ap',resolve_fallback=False,allow_expired=True)
            context={**request,**resolved}
            for repeat in range(args.repeat):
                captured={};deliveries=[]
                @contextmanager
                def factory(ctx,cancel):
                    with web._cockpit_main_turn(ctx,cancel) as (session,events):
                        captured['session']=session
                        original=session._tool_executors[TOOL]
                        original_repair=session._tool_executors[REPAIR_TOOL]
                        def delivery(params,cwd):
                            output=original(params,cwd)
                            value=json.loads(output)
                            deliveries.append(dict(actionAcceptances=[a.get('acceptance') for a in params.get('recommendations') or []],accepted=bool(value.get('accepted')),
                                issuePaths=[i.get('loc',[]) for i in value.get('issues') or []],
                                issueMessages=[str(i.get('message',''))[:1200] for i in value.get('issues') or []],
                                rejectedTexts=[i.get('rejectedText') for i in value.get('issues') or [] if i.get('rejectedText')]))
                            return output
                        session._tool_executors[TOOL]=delivery
                        def repair(params,cwd):
                            output=original_repair(params,cwd)
                            value=json.loads(output)
                            deliveries.append(dict(tool=REPAIR_TOOL,patches=params.get('patches'),accepted=bool(value.get('accepted')),issues=value.get('issues',[]),fingerprintMatches=params.get('draftHash')==getattr(session,'cockpit_pending_delivery',(None,))[0]))
                            return output
                        session._tool_executors[REPAIR_TOOL]=repair
                        def traced_events():
                            for event in events:
                                if event.get('type')=='llm_response':
                                    captured.setdefault('modelResponses',[]).append({k:event.get(k) for k in ('stop_reason','usage')})
                                yield event
                        yield session,traced_events()
                start=time.monotonic()
                try:
                    result,_=run_main_analysis(context,threading.Event(),lambda *_:None,factory)
                    case=dict(stage=stage,repeat=repeat+1,status='accepted',contentStatus=result['_status'])
                    case['deliveredCounts']={k:len(result.get(k) or []) for k in ('findings','analysisDimensions','causes','recommendations')}
                    from bi_agent.cockpit.delivery import project_card
                    slots={'opportunity':'opportunity-risk','order':'order-risk-summary','shipment':'shipment-risk-summary','combined':'sales-shipment-issues','bid':'bid-summary','quotation':'quote-summary'}
                    projected=project_card({'id':'canary','status':result['_status'],'context':context,'result':result,'evidence':result['_evidence']},slots[stage])['result']
                    case['projectedCounts']={k:len(projected.get(k) or []) for k in ('findings','analysisDimensions','causes','recommendations')}
                    case['findingTitles']=[f.get('title') for f in projected.get('findings') or []]

                except Exception as exc:
                    case=dict(stage=stage,repeat=repeat+1,status='failed',errorType=type(exc).__name__,
                        errorCode=getattr(exc,'code',''),error=str(getattr(exc,'original_message',str(exc)))[:500])
                session=captured.get('session')
                case.update(sourceAnalysisId=raw.get('analysisId'),sourceDataAsOf=raw.get('dataAsOf'),modelResponses=captured.get('modelResponses',[]),toolCalls=[b.get('name') for message in getattr(session,'messages',[]) if message.get('role')=='assistant' and isinstance(message.get('content'),list) for b in message['content'] if b.get('type')=='tool_use'],
                            modelCalls=getattr(session,'_turn_model_requests',0),
                            durationSeconds=round(time.monotonic()-start,2),deliveries=deliveries,
                            replayQueries=len(queries),replayRecords=sum(len(q['response']['result']['rows']) for q in queries))
                cases.append(case)
                print(json.dumps(case,ensure_ascii=False),flush=True)
    attempted=[c for c in cases if c['status']!='no_replayable_records']
    accepted=[c for c in attempted if c['status']=='accepted']
    report=dict(kind='published-record-subset-model-canary',model='direct-deepseek-v4-flash',
        limitations=['Only replayable records retained in published evidence; excludes full AP inputs and production refresh.',
                     'Small repeated sample; not a statistical production success-rate guarantee.'],
        summary=dict(attempted=len(attempted),accepted=len(accepted),failed=len(attempted)-len(accepted),
                     acceptedFirstCall=sum(c['modelCalls']==1 for c in accepted),acceptedSecondCall=sum(c['modelCalls']==2 for c in accepted)),cases=cases)
    report_path=Path(args.output)
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    report_path.chmod(0o600)
    print(json.dumps(report['summary'],ensure_ascii=False),flush=True)


if __name__=='__main__':main()
