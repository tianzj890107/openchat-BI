"""Validated card delivery inside the main WebSession, with no extra LLM pass."""
from __future__ import annotations
import json
from pydantic import Field, ValidationError
from .agent import Result, Cause, Recommendation, validate_result
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
    if causes_required and not result.get("causes"):
        gaps.append("CAUSES_EMPTY")
    if actions_required and not result.get("recommendations"):
        gaps.append("ACTION_EMPTY")
    complete = not gaps
    return dict(status="complete" if complete else "limited", renderable=True,
                complete=complete, evidenceCount=evidence_count,
                riskFindingCount=len(result.get("findings") or []), gaps=gaps)

class CardCause(Cause):
    title:str=Field(min_length=1,max_length=32)
    description:str=Field(min_length=1,max_length=160)

class CardRecommendation(Recommendation):
    action:str=Field(min_length=1,max_length=64)

class Cards(Result):
    summary:str=Field(min_length=1,max_length=240)
    causes:list[CardCause]=Field(default_factory=list,max_length=8)
    recommendations:list[CardRecommendation]=Field(default_factory=list,max_length=8)

SCHEMA=dict(name=TOOL,description='提交现有AI插槽的短摘要、原因、结构化风险发现、建议与限制。必须先读取看板证据；引用工具返回的evidenceIds。findings只列证据支持的风险事实，不把原因、数据缺口或结构定位计入。根因未确认时可交付空原因，但商机、订单、发货和共同分析有可定位业务事实时必须给出有证据的核查建议；不得编造原因或改善措施。此工具不取数、不执行任务。',input_schema=Cards.model_json_schema())


def install_delivery(session,context):
    from .main_service import session_evidence
    def deliver(params,cwd):
        evidence=session_evidence(session,context)
        try:
            if not session.query_results:raise ValueError('请先读取本轮看板数据')
            value=validate_result(params,evidence,{e['id'] for e in evidence['evidence']},result_model=Cards)
            validate_reasoning(value,evidence,stage=str(context.get('stage') or ''))
        except ValueError as exc:
            # Invalid model arguments are repairable business feedback, not a
            # transport failure that terminates the main Tool Runtime.
            session.cockpit_card_delivery=None
            issues=([dict(loc=list(e['loc']),message=e['msg']) for e in exc.errors(include_input=False,include_url=False)]
                if isinstance(exc,ValidationError) else [dict(message=str(exc)[:400])])
            return json.dumps(dict(accepted=False,issues=issues,evidenceIds=[e['id'] for e in evidence['evidence']][:100],
                instruction='请按上述校验问题修正后再次调用本工具；不需要重复取数，不能编造缺失事实。'),ensure_ascii=False)
        session.cockpit_card_delivery=(len(session.query_results),value)
        return json.dumps(dict(accepted=True,contract=CONTRACT,summary=value['summary']),ensure_ascii=False)
    session._tool_executors[TOOL]=deliver
