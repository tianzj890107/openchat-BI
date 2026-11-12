"""Presentation adapter for the existing main-service WebSession execution.

No model call, independent tool loop, or second analysis prompt lives here.
Validated card fields are delivered through the same main-service tool loop.
No additional model pass rewrites the result.
"""
from __future__ import annotations
import re
import json
import time
from dataclasses import asdict, is_dataclass
from .data import NAMES

LIMITED_STOP_REASONS = frozenset({'answer_blocked', 'delivery_incomplete',
                                  'max_iterations', 'max_tokens'})


def analysis_question(context):
    scope={k:context.get(k) for k in ('period','department','filters','repositoryId','chartSnapshotId','clarifications')}
    if context.get('apReceiptIds') or context.get('pgReceiptIds'):
        for key in ('period','department','filters'):scope.pop(key,None)
    stage_gap=context.get('stageEvidence') or {}
    stage_note=''
    if context.get('stage') == 'combined':
        stage_note = ('这是跨环节共同问题分析。联合核对商机覆盖、订单接收、实际发货与目标；'
                      '先核对每条原始请求的时间、单位、过滤口径，禁止把各环节金额直接相加或将关联说成因果。'
                      '证据来自本轮独立取证或本轮复用的同口径AP响应，不依赖其他AI任务完成。说明各查询观察时间与缺失覆盖；'
                      '有证据的环节仍须分析，不得因发货维度缺失而省略商机和订单。')
    if stage_gap:
        stage_note+=(f"本轮只为{NAMES[context['stage']]}环节提供{stage_gap.get('kept',0)}条匹配查询；"
                    f"另有{stage_gap.get('excluded',0)}条其他环节查询已排除，不得引用或改写成该环节证据。")
        if stage_gap.get('failed'):
            values=stage_gap.get('failedLabels') or []
            labels='、'.join(values[:6])+('等' if len(values)>6 else '') or '若干指标'
            stage_note+=f"本环节另有{stage_gap['failed']}条指标查询因上游数据失败未纳入（{labels}）；不得据此推断该环节正常，原因与建议必须说明该缺口。"
    return (
        f"请分析{NAMES[context['stage']]}环节的经营异常，调查有证据支持的原因，并给出基于证据的改善建议。"
        "请沿用主服务正常意图路由、只读看板工具取数与交付校验。本任务为无对话自动卡片交付，遇到口径歧义请交付受限卡片说明缺失，不要等待交互。"
        "部分AP查询成功、部分失败时，必须使用已成功取得的证据继续完成分析并交付受限卡片；不得因为还有指标未返回而整卡等待或只回一句“尚无分析结果”。"
        "只在限制中列明哪些未返回，摘要呈现已取得的经营数值和业务变化，再按已取得事实给出可执行的核查动作；缺失项不得推测成结论，也不得用其他环节数据替代。"
        + ("本轮证据已由服务端读取并登记，见后附冻结查询材料。第一次必须直接调用CockpitDeliverCards交付，第二次按拒绝响应指定工具修复：正常草稿用CockpitRepairCards局部修补，截断空草稿用CockpitDeliverCards完整重交；不能再读目录、补取查询或询问用户。材料不足时说明限制，不编造原因。" if context.get('preparedEvidence') else "先调用Cockpit-DashboardQuery读取目录，再用queryIds批量读取相关查询（每批最多6项，尽量一次并列发起所需批次）。")
        + "工具读取的是与网页同一次取数的冻结结果；是否为实时AP取数以工具返回live标记为准。范围JSON的时间和部门只是页面历史参数，实际分析范围以AP原始请求为准，不可假定已应用筛选。"
        "缺少指标映射或实体关系时明确说明，存在歧义时在限制中说明缺失口径，不等待用户确认，不得自动选采购指标代替销售指标。"
        "业务链条必须区分商机、报价/投标、合同签订、订单接收、发货。未签单指合同未签订，不是没有订单。合同已签订只能依据明确合同确认/状态、合同编号或签订日期；订单存在、订单数及销售订单审批不能证明合同签订。合同未签订也需要明确未签状态；上游非已签分组可能含缺失值，只能说合同签订未确认，不能把未知算成未签。没有合同证据时在limitations说明合同环节缺口，不在订单和商机之间虚构合同状态。"
        "交付内容按“发现什么／集中在哪里／可能为什么／下一步怎么做”组织：异常表现、结构定位、数据缺口不得写成原因；"
        "金额与电量缺少单价、产品结构或交期映射时不得比较或相加；取消/变更与中标未签集合未验证重叠和期间对应时，不得相加或据此排除缺口；"
        "目标或口径冲突时，limitations必须说明各自口径观察和“尚不能汇总对账”，不要把缺数说明当经营结论；建议的责任角色标为待确认、期限标为建议值，验收必须可检查。"
        "只有汇总指标或原始查询行时，原因status只能用hypothesis、kind用hypothesis，明确是待验证假设；不得标supported或verified。没有原因线索可为空，仍可给直接引用事实的investigation核查建议。原因kind只用hypothesis或verified；事实、结构定位和缺数不放入causes，未证明原因在missingEvidence写明缺失材料。建议要给出actionType：核查、补数、对账、确认口径用investigation，可关联待验证假设、数据缺口或直接引用证据；调整交付、资源或价格等改善动作用remediation，必须关联已得到记录支持的原因。原因未证明时只能先给核查任务，不能把假设直接变成改善措施。所有建议的causeIds与evidenceIds必须真实存在，责任人和期限的确认标记由服务端保持false，待用户确认。"
        "请读取工具返回的evidenceIds，最终调用CockpitDeliverCards提交短摘要、原因、风险发现、建议、限制供既有AI插槽展示；summary必须是纯文本单段结论，不得包含Markdown标题、加粗、列表、表格或“行动建议”清单，行动建议只能写入recommendations；短摘要可引用同源真实业务数值、趋势和差异，不得新造数字或比例；有合理线索时保留hypothesis并说明待验证材料，没有原因证据时causes可以为空；对商机、订单、发货和共同分析，只要取得可定位的业务事实，必须至少交付一项核查建议，不得因原因未确认一并清空建议。建议需明确要核对的对象/范围、具体字段或处理记录与验收清单；不得编造具体订单号、责任人或改善效果。仅状态概况且没有业务分析职责的插槽不强求建议。数据缺口核查建议可独立引用证据，不必为了挂建议而伪造原因。findings只列证据直接支持的风险事实或异常表现，不含原因、数据缺口和结构分布；同一风险只列一次。不要生成HTML或重新绘制图表，不得编造根因、责任角色或期限。每轮风险、原因、建议各最多4条，文字简短。风险优先实际履约逾期、经营目标偏离及持续恶化，再考虑转化或过程异常；同口径内结合影响范围与影响规模排序，不跨单位比较。已有多个重要独立问题时findings应逐项呈现3至4条，不要全塞入summary。负数、正常在途或余额规模本身不等于风险；缺口方向必须有明确公式或同口径目标/实际比较才能判断。逐条检查推进停滞、交期/排程、记录同步、客户变更等是否有独立机制线索；有3至4个不同机制时分别交付，不要把全部原因概括成一条“缺少明细”。同一机制可解释多个风险，不为凑数拆分。只有1至2条重要问题时保留真实数量，不拆分重复、不以数据缺口凑数。原因只保留解释重要风险的机制假设并写缺失证据；建议对应这些风险或原因，核查类可直接引用风险证据；同一目的的补字段、对账动作应合并，不按缺失字段数量机械拆成多条建议；证据足够即调用交付工具，不逐条追加查询。提交成功后系统直接展示，不需要再生成确认文案。"
        + ('\n本轮业务展示按风险、分析维度、建议交付：analysisDimensions（原因分析）用findingIds关联本卡风险，并引用同源evidenceIds。各风险都要通过findingIds明确关联分析条目；如果输出causes，也用findingIds关联对应风险。多组独立风险按商机获取、报价、投标、合同签订、订单接收、发货等业务环节展开；优先每条风险对应一条主要原因，同一风险必要时可有多个条目，确属同一问题也可关联多个风险。analysisDimensions.stage必须明确业务环节，标题写环节内主题；时间、客户、产品等只用于环节内部展开数字分析，不机械一风险一原因，不把全部风险笼统归成一个假设。描述已观察的数字、分布、差异和变化，可直接引用证据原值；不要补造原因。summary只呈现已返回的经营数值、异常及趋势，控制在200字内；指标为空、口径冲突、无法评估和方法规则只放limitations，不作为风险或分析维度。不要求为了展示生成causes，缺少已证实机制时causes可为空；核查建议直接引用证据即可。' if context.get('businessDimensions') else '')
        +("\n证据范围："+stage_note if stage_note else '')
        +"\n范围："+json.dumps(scope,ensure_ascii=False,sort_keys=True)
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
                from .diagnostics import AnalysisFailure
                raise AnalysisFailure(event.get('message') or event.get('error') or 'Empty main-service error event',
                    phase='main_service',code=event.get('error_code') or 'MAIN_SERVICE_ERROR',
                    last_tool=next((v.get('tool','') for v in reversed(trace) if v.get('tool')), ''))
            elif kind=='done':done=event.get('stop_reason','done')
            elif kind=='text_delta' and not narrative:
                # Refusals/limitations can be emitted without an llm_response.
                pass
            if kind in {'cognitive_policy','tool_start','sop_progress','recovery_state','awaiting_user_choice','llm_request','llm_response','done'}:
                if needs_input:message='等待补充分析口径'
                elif kind=='llm_request':message=f'模型分析第 {rounds+1} 轮'
                elif kind=='tool_start':message='交付校验' if event.get('name')=='CockpitDeliverCards' else '读取看板证据'
                elif kind=='done':message='分析完成，正在发布'
                else:message=f'模型分析已完成 {rounds} 轮' if rounds else '路由与证据准备'
                progress(message,list(trace))
        if getattr(session, 'require_validated_delivery', False):
            delivery=getattr(session, 'cockpit_card_delivery', None)
            if not delivery or delivery[0] != len(getattr(session,'query_results',[])):
                from .diagnostics import AnalysisFailure
                raise AnalysisFailure('两轮内未形成有效卡片交付，保留上次已发布结果',
                                      phase='card_delivery',code='CARD_DELIVERY_NOT_ACCEPTED',
                                      last_tool=next((v.get('tool','') for v in reversed(trace) if v.get('tool')),''))
        evidence=session_evidence(session,context)
        facts=evidence['facts']
        committed=[]
        for message in getattr(session,'messages',[]):
            blocks=message.get('content',[])
            if message.get('role')=='assistant' and isinstance(blocks,list) and not any(b.get('type')=='tool_use' for b in blocks):
                text='\n'.join(b.get('text','') for b in blocks if b.get('type')=='text')
                if text:committed.append(text)
        if committed:narrative=committed[-1] if done in LIMITED_STOP_REASONS else '\n\n'.join(committed)
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
        status='needs_input' if needs_input else 'limited' if done in LIMITED_STOP_REASONS or not facts else 'completed'
        if context.get('snapshotId','').startswith(('dashboard-','ap-')) and status=='completed':status='limited'
        limitations=evidence['limitations']
        from .cards import CONTRACT
        delivery=getattr(session,'cockpit_card_delivery',None)
        card_value=delivery[1] if delivery and delivery[0]==len(getattr(session,'query_results',[])) and not needs_input and done not in {'answer_blocked','delivery_incomplete','max_iterations'} else None
        # A partially successful AP read must still produce a usable card.
        # When the tool-level delivery could not pass the full contract, keep
        # the evidence-backed narrative as a limited card with no fabricated
        # causes or recommendations.  This is deliberately only a fallback:
        # validated tool output always wins when it exists.
        from .delivery import plain_summary_text
        if (not card_value and not needs_input
                and done in LIMITED_STOP_REASONS
                and (facts or (evidence.get('records') or []))
                and narrative.strip()):
            card_value=dict(
                summary=plain_summary_text(split_sections(narrative)['summary'] or narrative)[:240],
                causes=[], recommendations=[], findings=[],
                limitations=list(dict.fromkeys(limitations))[:8])
            if card_value['summary']:
                status='limited'
        return dict(summary=(plain_summary_text(card_value['summary']) if card_value else plain_summary_text(split_sections(narrative)['summary'] or narrative)[:600]),
            causes=card_value['causes'] if card_value else [],recommendations=card_value['recommendations'] if card_value else [],
            findings=card_value.get('findings',[]) if card_value else [],
            analysisDimensions=card_value.get('analysisDimensions',[]) if card_value else [],
            limitations=list(dict.fromkeys(limitations+(card_value['limitations'] if card_value else []))),cardContract=CONTRACT if card_value else None,
            narrative=narrative,sections=split_sections(narrative),engine='main',policy=policy,clarification=getattr(session,'pending_choice_spec',None),
            _status=status,_evidence=evidence,_execution=dict(engine='main',durationSeconds=round(time.monotonic()-started,3),
                modelRounds=rounds,usage=usage,toolCalls=sum(t['tool']!='MainServiceRoute' for t in trace),route=policy,stopReason=done,claims=len(facts))),trace

def session_evidence(session,context):
    facts=[]
    for claim in getattr(session,'claims',[]):
        value=asdict(claim) if is_dataclass(claim) else dict(claim)
        value=json.loads(json.dumps(value,ensure_ascii=False,default=str))
        statement=value['statement'];label=statement;number=None
        match=re.fullmatch(r'(.+)=(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)',statement)
        if match:label=re.sub(r'\[[^\]]+\]$','',match[1]);number=float(match[2])
        label=label.split(' :: ',1)[-1]
        facts.append(dict(id=value['id'],label=label,value=number,unit='',definition=statement,claim=value))
    stage_filter=getattr(session,'cockpit_stage_filter',None) or {}
    if context.get('snapshotId','').startswith('ap-'):
        if context.get('dataSource')=='pg':
            basis='页面本次AP取数全部失败；主服务按同一筛选口径从主库（PostgreSQL）补查，结果标注来源且未混用AP'
        else:
            basis='主服务读取页面本次实时AP响应的冻结结果' + ('，并对页面失败的指标按同一口径补查主库' if stage_filter.get('fallback') else '')
    else:
        basis='主服务读取当前看板同一份交付AP快照，非实时数据库'
    limitations=[basis+'；时间、部门以AP原始请求为准。没有同源明细补查接口，不能据此确认根因。',
        '展示层直接摘取主服务已交付章节，没有额外调用模型生成原因或建议。']
    if stage_filter.get('fallback'):
        limitations.append('已从主库（PostgreSQL）补查：'+'、'.join(stage_filter['fallback'][:8])+'。补查与页面AP为不同装载时点的副本，同一计算范围只用一种来源。')
    if stage_filter.get('fallbackBlocked'):
        limitations.append('另有失败指标未补查，原因代码：'+'、'.join(sorted(set(stage_filter['fallbackBlocked']))[:6])+'；未用其他指标替代。')
    if stage_filter.get('excluded'):
        limitations.append(f"已排除{stage_filter['excluded']}条与{NAMES.get(stage_filter.get('stage'),stage_filter.get('stage'))}环节无关的页面查询；未使用其他环节数据代替。")
    if stage_filter.get('failed'):
        values=stage_filter.get('failedLabels') or []
        labels='、'.join(values[:6])+('等' if len(values)>6 else '') or '指标'
        limitations.append(f"本环节有{stage_filter['failed']}条指标查询失败未纳入（{labels}）；未用其他数据替代，相关结论应视为不完整。")
    read_ids, sampled_ids = set(), set()
    for query in getattr(session,'query_results',[]):
        output=getattr(query,'data',None)
        try:output=json.loads(output) if isinstance(output,str) else output
        except (ValueError,TypeError):continue
        if not isinstance(output,dict):continue
        parts=output.get('queries') or [output]
        for part in parts:
            if not isinstance(part,dict) or not part.get('queryId'):continue
            read_ids.add(part['queryId'])
            if (part.get('coverage') or {}).get('sampleOnly'):sampled_ids.add(part['queryId'])
    if sampled_ids:
        limitations.append(f'{len(sampled_ids)}条查询仅提供有界样本，不能外推总体比例；原始AP凭据保留完整响应。')
    if stage_filter.get('kept',0)>len(read_ids):
        limitations.append(f"本轮读取{len(read_ids)}/{stage_filter['kept']}条匹配查询，未读查询不作为结论依据。")
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
            row_query=row.get('__queryId') if isinstance(row,dict) else None
            row_scope=getattr(query,'scope',{})
            if row_query:
                row={key.split(' :: ',1)[-1]:value for key,value in row.items() if key!='__queryId'}
                row_scope=(row_scope.get('queries') or {}).get(row_query,row_scope)
            records.append(dict(id=f'query-{index}:row-{row_index}',customer=f'主服务查询{index+1}记录{row_index+1}',
                amount=None,cause='原始查询行，未独立验证因果关系',causeSupport=False,evidence='主服务本轮查询结果',data=row,scope=row_scope))
        if len(records)>=24:break
    records=records[:24]
    row_evidence=[dict(id=r['id'],label=r['customer'],value=None,unit='',definition=r['cause'],record=r) for r in records]
    evidence=dict(sourceMode='service',dataSource=context.get('dataSource',''),snapshotId=context['snapshotId'],stage=context['stage'],stageName=NAMES[context['stage']],
        period='以AP原始请求为准' if context.get('snapshotId','').startswith('ap-') else context['period'],department='以AP原始请求为准' if context.get('snapshotId','').startswith('ap-') else context['department'],facts=facts,records=records,causes=[],evidence=facts+row_evidence,limitations=limitations+['冻结查询行最多24条，超过8000字符的行不进入材料包；样本分布不能外推总体比例'])
    return evidence
