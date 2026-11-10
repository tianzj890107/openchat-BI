"""Validated card delivery inside the main WebSession, with no extra LLM pass."""
from __future__ import annotations
import json
import hashlib
from copy import deepcopy
import re
from typing import Literal
from pydantic import Field, ValidationError
from .agent import StrictModel, Result, Cause, Recommendation, Finding, validate_result
from .delivery import SLOT_SPECS, evidence_count as distinct_evidence_count, validate_reasoning

CONTRACT='cockpit-cards-v1'
TOOL='CockpitDeliverCards'


def valid_card(item) -> bool:
    """Whether a persisted analysis can be rendered as a complete AI card.

    A database row or a merely non-empty result is not enough: every public
    slot needs the delivered card contract and the fields consumed by the
    composition slot.  This is intentionally shared by publication reads and
    background preheat so status cannot claim ready for an unusable payload.
    """
    result = (item or {}).get('result') if isinstance(item, dict) else None
    if not isinstance(result, dict) or result.get('cardContract') != CONTRACT:
        return False
    if not isinstance(result.get('summary'), str) or not result['summary'].strip():
        return False
    return all(isinstance(result.get(key), list)
               for key in ('causes', 'recommendations', 'limitations'))


def card_delivery_state(item, slot=None) -> dict:
    """Separate renderability from evidence/content completeness per slot.

    A status-only card (quotation, bid status, table row positioning) does not
    owe a root cause or an action.  Completeness follows the slot contract and
    counts each evidence id once, even when facts and records overlap.
    """
    if not isinstance(item, dict) or not item:
        return dict(status="missing", renderable=False, complete=False,
                    evidenceCount=0, riskFindingCount=0, gaps=["CARD_MISSING"])
    if not valid_card(item):
        return dict(status="invalid", renderable=False, complete=False,
                    evidenceCount=0, riskFindingCount=0, gaps=["CARD_CONTRACT_INVALID"])
    result = item.get("result") or {}
    evidence = item.get("evidence") or {}
    evidence_count = distinct_evidence_count(evidence)
    spec = SLOT_SPECS.get(slot or "") or {}
    causes_required = spec.get("causes_required", True)
    actions_required = spec.get("actions_required", False)
    gaps = []
    if str(item.get("status") or "") != "completed":
        gaps.append("ANALYSIS_LIMITED")
    if evidence_count == 0:
        gaps.append("EVIDENCE_EMPTY")
    if causes_required and not result.get("causes") and not result.get("analysisDimensions"):
        gaps.append("CAUSES_EMPTY")
    if actions_required and not result.get("recommendations"):
        gaps.append("ACTION_EMPTY")
    complete = not gaps
    return dict(status="complete" if complete else "limited", renderable=True,
                complete=complete, evidenceCount=evidence_count,
                riskFindingCount=len(result.get("findings") or []), gaps=gaps)

class CardCause(Cause):
    findingIds:list[str]=Field(default_factory=list,max_length=8,description='明确关联本卡风险ID；不要根据相同证据自动猜关联')
    kind:Literal["verified","hypothesis"]=Field(default="hypothesis",description="仅证实机制或待验证机制；异常表现放风险发现，结构与缺数放限制，不作原因")
    title:str=Field(min_length=1,max_length=32)
    description:str=Field(min_length=1,max_length=160)

class CardRecommendation(Recommendation):
    actionType:Literal["investigation","remediation"]=Field(default="investigation",description="无证实原因时只用investigation核查动作")
    acceptance:str=Field(min_length=1,max_length=180,description="必须是可检查的核查清单、对账记录或确认记录，不承诺经营结果")
    action:str=Field(min_length=1,max_length=64)

class AnalysisDimension(StrictModel):
    stage:Literal['overview','opportunity','quotation','bid','contract','order','shipment']=Field(description='分析维度指业务环节：经营概况/商机获取/报价/投标/合同签订/订单接收/发货')
    id:str=Field(min_length=1,max_length=80)
    title:str=Field(min_length=1,max_length=32,description='该业务环节内的原因分析主题；时间、客户、产品等只作环节内下钻，不作同级业务维度')
    description:str=Field(min_length=1,max_length=240,description='用已有数值展开该维度的分布、差异、趋势或流程表现，不复述风险标题，不输出缺数、无法评估、待验证假设')
    findingIds:list[str]=Field(min_length=1,max_length=8)
    evidenceIds:list[str]=Field(min_length=1,max_length=20)

class Cards(Result):
    summary:str=Field(min_length=1,max_length=240)
    causes:list[CardCause]=Field(default_factory=list,max_length=4)
    analysisDimensions:list[AnalysisDimension]=Field(default_factory=list,max_length=4)
    recommendations:list[CardRecommendation]=Field(default_factory=list,max_length=4)
    findings:list[Finding]=Field(default_factory=list,max_length=4,description="按重要性列出最多4个独立经营风险；有多个重要问题时逐项交付，不能合成一句摘要，不以数据缺口凑数")

SCHEMA=dict(name=TOOL,description='提交现有AI插槽的经营摘要、结构化风险、analysisDimensions原因分析、建议与限制。分析维度必须以findingIds关联本卡风险，以真实数值展开分布、趋势和流程表现；缺数和无法评估放limitations。summary必须是纯文本单段结论，禁止Markdown标题、加粗、列表、表格和行动建议清单，行动建议只能写入recommendations。必须先读取看板证据；引用工具返回的evidenceIds。findings只列证据支持的风险事实，不把原因、数据缺口或结构定位计入。根因未确认时可交付空原因，但商机、订单、发货和共同分析有可定位业务事实时必须给出有证据的核查建议；不得编造原因或改善措施。此工具不取数、不执行任务。',input_schema=Cards.model_json_schema())


REPAIR_TOOL='CockpitRepairCards'
REPAIR_SCHEMA=dict(name=REPAIR_TOOL,description='修复刚被拒绝的卡片。只提交JSON Patch局部修改，不重新生成整张卡；其他字段服务端原样保留，之后仍完整校验。缺失字段用add，修改用replace，删除用remove。',
    input_schema={'type':'object','properties':{'draftHash':{'type':'string','pattern':'^[0-9a-f]{12}$','description':'原样复制上次拒绝响应中的12位draftHash'},'patches':{'type':'array','minItems':1,'maxItems':30,'items':{
        'type':'object','properties':{'op':{'type':'string','enum':['add','replace','remove']},'path':{'type':'string'},'value':{}},'required':['op','path'],'additionalProperties':False}}},
        'required':['draftHash','patches'],'additionalProperties':False})


def apply_card_patch(candidate, patches):
    """Bounded JSON Patch on card data only; never execute user text."""
    value=deepcopy(candidate)
    if not isinstance(patches,list) or not 1 <= len(patches) <= 30:
        raise ValueError('patches必须是1至30项局部修改')
    for patch in patches:
        if not isinstance(patch,dict) or patch.get('op') not in {'add','replace','remove'}:
            raise ValueError('无效的patch操作')
        path=patch.get('path')
        if not isinstance(path,str) or not path.startswith('/'):
            raise ValueError('patch必须使用JSON Pointer路径')
        parts=[p.replace('~1','/').replace('~0','~') for p in path[1:].split('/')]
        if not 1 <= len(parts) <= 6 or parts[0] not in {'summary','causes','recommendations','findings','analysisDimensions','limitations'}:
            raise ValueError('patch只能修改卡片内容字段')
        parent=value
        for part in parts[:-1]:
            if isinstance(parent,list) and part.isdigit() and int(part)<len(parent):parent=parent[int(part)]
            elif isinstance(parent,dict) and part in parent:parent=parent[part]
            else:raise ValueError('patch父路径不存在')
        leaf=parts[-1];op=patch['op']
        if op!='remove' and 'value' not in patch:raise ValueError('add/replace需要value')
        if isinstance(parent,dict):
            if op!='add' and leaf not in parent:raise ValueError('patch目标不存在，缺失字段请用add')
            if op=='remove':del parent[leaf]
            else:parent[leaf]=deepcopy(patch['value'])
        elif isinstance(parent,list) and (leaf.isdigit() or (leaf=='-' and op=='add')):
            index=len(parent) if leaf=='-' else int(leaf)
            if index>len(parent) or (index==len(parent) and op!='add'):raise ValueError('patch数组索引越界')
            if op=='remove':parent.pop(index)
            elif op=='add':parent.insert(index,deepcopy(patch['value']))
            else:parent[index]=deepcopy(patch['value'])
        else:raise ValueError('无效的patch目标')
    return value


def summary_structure_issue(summary) -> str:
    """A card summary is one plain-text conclusion, not a delivery document."""
    value = str(summary or '')
    if re.search(r'(?m)^\s{0,3}#{1,6}\s*', value) or '**' in value:
        return 'summary 含 Markdown 标题或加粗标记'
    if re.search(r'(?m)^\s{0,3}[-*+•]\s+', value):
        return 'summary 含项目符号列表'
    if '行动建议' in value or re.search(r'建议\s*\d+\s*[：:]', value):
        return 'summary 含行动建议清单'
    return ''


def install_delivery(session,context):
    from .main_service import session_evidence
    def deliver(params,cwd):
        evidence=session_evidence(session,context)
        try:
            if not session.query_results:raise ValueError('请先读取本轮看板数据')
            value=validate_result(params,evidence,{e['id'] for e in evidence['evidence']},result_model=Cards)
            if context.get('businessDimensions'):
                from .business_presentation import validate_dimensions,business_finding,present_business_result
                if any(not business_finding(f) for f in value.get('findings') or []):raise ValueError('风险发现不能是字段为空、口径冲突或无法评估；这些内容应移入limitations')
                presentation=present_business_result(value)
                value['summary']=presentation['businessSummary'][:240] or '本轮暂无新增经营结论。'
                value['limitations']=presentation['limitations']
                validate_dimensions(value,{e['id'] for e in evidence['evidence']})
            validate_reasoning(value,evidence,stage=str(context.get('stage') or ''),business_only=bool(context.get('businessDimensions')))
            summary_issue=summary_structure_issue(value.get('summary'))
            if summary_issue:
                raise ValueError(summary_issue+'；summary只能写纯文本结论，行动建议写入recommendations。')
        except ValueError as exc:
            # Invalid model arguments are repairable business feedback, not a
            # transport failure that terminates the main Tool Runtime.
            session.cockpit_card_delivery=None
            issues=([dict(loc=list(e['loc']),message=e['msg']) for e in exc.errors(include_input=False,include_url=False)]
                if isinstance(exc,ValidationError) else [dict(loc=['summary'] if 'summary' in str(exc) else [],message=str(exc)[:1200])])
            if 'analysisDimensions' in str(exc) or '分析维度' in str(exc):
                issues.append(dict(loc=['analysisDimensions'],message=str(exc)[:1200]))
            from .delivery import reasoning_repair_locations
            # Report independent semantic gaps with schema errors, so the
            # single repair does not discover them only after fixing a field.
            if str(context.get('stage') or '') in {'opportunity','order','shipment','combined'} and not params.get('recommendations') and evidence.get('evidence'):
                issues.append(dict(loc=['recommendations'],message='已有业务证据，必须同时补至少一项investigation核查建议，直接引用真实evidenceIds，causeIds可为空；写明action、ownerRole、deadlineDays、acceptance核查清单。不能因为原因未证实而清空建议。'))
            issues.extend(reasoning_repair_locations(params,evidence))
            if isinstance(exc,ValidationError):
                try:
                    validate_reasoning(deepcopy(params),evidence,stage=str(context.get('stage') or ''),business_only=bool(context.get('businessDimensions')))
                except ValueError as semantic:
                    issues.append(dict(loc=[],message=str(semantic)[:1200]))
                except (TypeError,AttributeError,KeyError):
                    pass  # Malformed field types are already in schema feedback.
            if not isinstance(exc,ValidationError):
                available_ids={e['id'] for e in evidence['evidence']}
                for field in ('findings','causes','recommendations'):
                    for index,entry in enumerate(params.get(field) or []):
                        if not isinstance(entry,dict):continue
                        bad=set(entry.get('evidenceIds') or [])-available_ids
                        if bad:issues.append(dict(loc=[field,index,'evidenceIds'],message='这些证据ID不存在：'+','.join(sorted(bad))+'；请按原对象从已读证据选择正确ID，不能换成其他事实。'))
            draft_hash=hashlib.sha256(json.dumps(params,ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:12]
            session.cockpit_pending_delivery=(draft_hash,deepcopy(params),len(session.query_results))
            empty_candidate=not any(params.get(key) for key in ('summary','findings','causes','recommendations'))
            session.model_tools_override=[TOOL] if empty_candidate else [REPAIR_TOOL]
            return json.dumps(dict(accepted=False,issues=issues,draftHash=draft_hash,
                evidenceIds=[e['id'] for e in evidence['evidence']][:100],
                instruction=('上一条工具参数截断为空。仅剩一次机会，调用CockpitDeliverCards提交完整卡片，按完整schema填写所有必填字段及子对象id、kind等；不要调用修补工具。' if empty_candidate else '仅剩一次修复机会，只调用CockpitRepairCards。按loc及rejectedText局部修改，其他字段原样保留；缺失字段用add。行动清单放recommendations。可删除无依据原因，但需同步修正建议causeIds并保留真实evidenceIds。验收写可检查的核查清单/对账记录，不承诺结果。')),ensure_ascii=False)
        session.cockpit_card_delivery=(len(session.query_results),value)
        return json.dumps(dict(accepted=True,contract=CONTRACT,summary=value['summary']),ensure_ascii=False)
    def repair(params,cwd):
        pending=getattr(session,'cockpit_pending_delivery',None)
        if not pending or params.get('draftHash')!=pending[0] or len(session.query_results)!=pending[2]:
            return json.dumps(dict(accepted=False,issues=[dict(message='草稿或证据版本不匹配，拒绝修补')]),ensure_ascii=False)
        try:
            value=apply_card_patch(pending[1],params.get('patches'))
        except ValueError as exc:
            return json.dumps(dict(accepted=False,issues=[dict(message=str(exc))]),ensure_ascii=False)
        return deliver(value,cwd)
    session._tool_executors[TOOL]=deliver
    session._tool_executors[REPAIR_TOOL]=repair


def delivery_summary(session):
    """Only a validated, current delivery can terminate the main tool loop."""
    delivery = getattr(session, 'cockpit_card_delivery', None)
    if delivery and delivery[0] == len(session.query_results):
        return delivery[1]['summary']
    return None
