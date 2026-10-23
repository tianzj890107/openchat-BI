"""Presentation adapter for the existing main-service WebSession execution.

No model call, independent tool loop, or second analysis prompt lives here.
Only committed main-service output is delivered; no JSON-repair model pass.
"""
from __future__ import annotations
import re
import json
import time
from dataclasses import asdict, is_dataclass
from .data import NAMES


def analysis_question(context):
    scope={k:context.get(k) for k in ('period','department','filters','repositoryId','chartSnapshotId','clarifications')}
    return (
        f"请分析{NAMES[context['stage']]}环节的经营异常，调查有证据支持的原因，并给出基于证据的改善建议。"
        "请沿用主服务正常意图路由、只读看板工具取数与交付校验。"
        "先调用Cockpit-DashboardQuery读取目录，再读取相关queryId。工具读取的是与网页一致的交付AP快照，不是实时数据库。范围JSON的时间和部门只是页面历史参数，实际分析范围以AP原始请求为准，不可假定已应用筛选。"
        "缺少指标映射或实体关系时明确说明，存在歧义时正常请求确认，不得自动选采购指标代替销售指标。"
        "请保持正常中文章节输出，不必生成HTML或重新绘制看板图表；不要为了填满卡片编造根因、责任角色或期限。"
        "\n范围："+json.dumps(scope,ensure_ascii=False,sort_keys=True)
    )


def split_sections(narrative):
    """Extract existing headings only; never infer a cause or an action."""
    sections={'summary':[], 'causes':[], 'recommendations':[]};active='summary'
    for line in narrative.splitlines():
        title=re.sub(r'^[#\s*]+|[：:\s*]+$', '', line)
        if title in {'根因分析','根因证据链','原因分析','原因'}:active='causes';continue
        if title in {'行动建议','建议雏形','管理建议','决策建议','执行建议','建议','下一步行动'}:active='recommendations';continue
        if title in {'结论','风险分析','风险概况'}:active='summary';continue
        sections[active].append(line)
    return {k:'\n'.join(v).strip() for k,v in sections.items()}


def run_main_analysis(context, cancel, progress, turn_factory):
    started=time.monotonic();trace=[];narrative='';done=None;policy=None;needs_input=False;usage={};rounds=0
    with turn_factory(context,cancel) as (session,events):
        for event in events:
            if cancel.is_set():raise InterruptedError('分析已停止')
            kind=event.get('type')
            if kind=='cognitive_policy':
                policy={k:event.get(k) for k in ('intent','mode','next_step','reason_code','required_tools','evidence_required','needs_human') if k in event}
                trace.append(dict(tool='MainServiceRoute',section='route',evidenceCount=0,decision=policy))
            elif kind=='llm_response':
                rounds+=1
                for key,value in (event.get('usage') or {}).items():
                    if isinstance(value,(int,float)):usage[key]=usage.get(key,0)+value
                # llm_response is an event, not a durable delivery boundary.
            elif kind=='tool_start':
                trace.append(dict(tool=event.get('name',''),section='main-service',evidenceCount=len(getattr(session,'claims',[]))))
            elif kind=='awaiting_user_choice':needs_input=True
            elif kind in {'error','session_superseded'}:
                if kind=='session_superseded':raise InterruptedError('主服务任务已失效')
                raise RuntimeError('主服务分析失败，请查看主服务执行状态；未切换到独立引擎')
            elif kind=='done':done=event.get('stop_reason','done')
            elif kind=='text_delta' and not narrative:
                # Refusals/limitations can be emitted without an llm_response.
                pass
            if kind in {'cognitive_policy','tool_start','sop_progress','recovery_state','awaiting_user_choice','done'}:
                progress('主服务：'+('等待补充分析口径' if needs_input else '路由、取证与交付校验中'),list(trace))
        claims=getattr(session,'claims',[])
        facts=[]
        for claim in claims:
            value=asdict(claim) if is_dataclass(claim) else dict(claim)
            value=json.loads(json.dumps(value,ensure_ascii=False,default=str))
            facts.append(dict(id=value['id'],label=value['statement'],value=None,unit='',definition='主服务结构化事实／结论',claim=value))
        committed=[]
        for message in getattr(session,'messages',[]):
            blocks=message.get('content',[])
            if message.get('role')=='assistant' and isinstance(blocks,list) and not any(b.get('type')=='tool_use' for b in blocks):
                text='\n'.join(b.get('text','') for b in blocks if b.get('type')=='text')
                if text:committed.append(text)
        if committed:narrative=committed[-1] if done in {'answer_blocked','delivery_incomplete'} else '\n\n'.join(committed)
        if needs_input:
            narrative=narrative or '主服务需要补充或确认指标、口径或业务对象；尚未交付根因结论。'
        elif done is None:raise RuntimeError('主服务未完成交付校验，未展示中间模型回答')
        elif not narrative:
            # Use the committed assistant text, never streamed intermediate drafts.
            for message in reversed(getattr(session,'messages',[])):
                if message.get('role')=='assistant':
                    blocks=message.get('content',[])
                    if isinstance(blocks,list) and not any(b.get('type')=='tool_use' for b in blocks):
                        narrative='\n'.join(b.get('text','') for b in blocks if b.get('type')=='text')
                        if narrative:break
        if not narrative:raise RuntimeError('主服务没有可交付的分析内容')
        status='needs_input' if needs_input else 'limited' if done in {'answer_blocked','delivery_incomplete','max_iterations'} or not facts else 'completed'
        if context.get('snapshotId','').startswith('dashboard-') and status=='completed':status='limited'
        limitations=['主服务读取当前看板同一份交付AP快照，非实时数据库；时间、部门以AP原始请求为准。没有同源明细补查接口，不能据此确认根因。',
            '展示层直接摘取主服务已交付章节，没有额外调用模型生成原因或建议。']
        records=[]
        for index,query in enumerate(getattr(session,'query_results',[])):
            data=getattr(query,'data',None)
            if isinstance(data,str):
                try:data=json.loads(data)
                except ValueError:continue
            if isinstance(data,dict):data=data.get('data',data)
            if isinstance(data,dict):data=data.get('rows',[])
            if not isinstance(data,list):continue
            for row_index,row in enumerate(data[:24]):
                if not isinstance(row,(dict,list)):continue
                encoded=json.dumps(row,ensure_ascii=False,default=str)
                if len(encoded)>8000:continue
                row=json.loads(encoded)
                records.append(dict(id=f'query-{index}:row-{row_index}',customer=f'主服务查询{index+1}记录{row_index+1}',
                    amount=None,cause='原始查询行，未独立验证因果关系',causeSupport=False,evidence='主服务本轮查询结果',data=row))
            if len(records)>=24:break
        records=records[:24]
        row_evidence=[dict(id=r['id'],label=r['customer'],value=None,unit='',definition=r['cause'],record=r) for r in records]
        evidence=dict(sourceMode='service',snapshotId=context['snapshotId'],stage=context['stage'],stageName=NAMES[context['stage']],
            period=context['period'],department=context['department'],facts=facts,records=records,causes=[],evidence=facts+row_evidence,limitations=limitations+['冻结查询行最多24条，超过8000字符的行不进入材料包；样本分布不能外推总体比例'])
        return dict(summary=split_sections(narrative)['summary'] or narrative,causes=[],recommendations=[],limitations=limitations,
            narrative=narrative,sections=split_sections(narrative),engine='main',policy=policy,clarification=getattr(session,'pending_choice_spec',None),
            _status=status,_evidence=evidence,_execution=dict(engine='main',durationSeconds=round(time.monotonic()-started,3),
                modelRounds=rounds,usage=usage,toolCalls=sum(t['tool']!='MainServiceRoute' for t in trace),route=policy,stopReason=done,claims=len(facts))),trace
