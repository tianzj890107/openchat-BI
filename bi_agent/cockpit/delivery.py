"""Per-slot delivery contracts and reasoning checks.

One stage analysis can feed several UI slots.  This module adapts the same
evidence-backed analysis to the question each slot actually asks, and rejects
prose the evidence cannot support: phenomena presented as causes, money/energy
comparisons without a unit bridge, unverified set arithmetic, hidden target
conflicts and acceptance criteria that a single task cannot guarantee.
"""
from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from .risk import build_risk_findings

CONTRACT_VERSION = 'cockpit-delivery-v2'

KIND_LABELS = {
    'verified': '记录支持',
    'fact': '异常表现',
    'structure': '结构定位',
    'data_gap': '数据缺口',
    'hypothesis': '待验证假设',
}

# Each slot states the question it must answer.  ``kinds`` limits which parts of
# a shared stage analysis may be shown there; ``actions`` controls whether a
# slot may carry suggested measures at all.
SLOT_SPECS = {
    'quote-summary': dict(
        question='报价办理状态如何，哪些状态需要业务关注',
        kinds=None, actions=False, max_causes=0, causes_required=False,
        note='本卡只交付报价状态概况与异常提醒，不作根因判断。'),
    'bid-status-note': dict(
        question='投标办理状态是否异常，异常集中在哪个状态',
        kinds=('fact', 'data_gap'), actions=False, max_causes=3, causes_required=False,
        note='本卡只交付投标状态与异常定位，不判定根因。'),
    'bid-summary': dict(
        question='投标环节有哪些异常表现和排查方向',
        kinds=('fact', 'structure', 'data_gap'), actions=True, max_causes=4,
        note='此处只交付异常表现与排查方向，不把现象写成已确认原因。'),
    'order-sign-summary': dict(
        question='订单接收结构如何，已签与未签、产品与客户分布在哪里',
        kinds=('fact', 'structure', 'data_gap', 'hypothesis'), actions=True, max_causes=4,
        causes_required=False,
        note='本卡交付签单结构与风险定位；结构分布不等于业务原因。'),
    'star-product-order-list': dict(
        question='每个明星产品的订单电量、占比与口径是否可解释',
        kinds=('fact', 'structure', 'data_gap'), actions=False, max_causes=4,
        causes_required=False, table_slot=True,
        note='按产品逐行交付口径与占比；不把通用摘要当作逐产品结论。'),
    'affected-order-list': dict(
        question='受影响订单有哪些，原因与责任动作是否有逐单证据',
        kinds=('fact', 'structure', 'data_gap'), actions=True, max_causes=4,
        causes_required=False, table_slot=True,
        note='按订单行交付风险定位；没有逐单证据时不填写已确认原因。'),
    'overdue-order-list': dict(
        question='哪些订单超期，超期原因是否有逐单证据',
        kinds=('fact', 'data_gap'), actions=True, max_causes=4,
        causes_required=False, table_slot=True,
        note='按订单行交付超期定位；发货状态缺失时只给出待补数据与核查动作。'),
    'sales-shipment-issues': dict(
        question='销售额与出货量的共同问题是什么，能否形成管理结论',
        kinds=('fact', 'structure', 'data_gap', 'hypothesis', 'verified'),
        actions=True, max_causes=5,
        note='跨环节结论必须同口径；口径冲突未对账前只交付各自观察，不汇总缺口。'),
    'opportunity-risk': dict(
        question='哪些商机风险已由本体规则触发，原因与行动是否有证据',
        kinds=('fact', 'structure', 'data_gap', 'hypothesis', 'verified'), actions=True,
        max_causes=5,
        note='程序按 V2 规则取证并计算数值；模型逐项判断风险证据、原因和建议，程序复核数字与关联。'),
    'opportunity-coverage-note': dict(
        question='商机覆盖缺口在哪里，目标与实际的差异如何理解',
        kinds=('fact', 'structure', 'data_gap'), actions=True, max_causes=4,
        note='本卡交付覆盖结构与数据缺口，不把目标为空当成原因。'),
    'order-risk-summary': dict(
        question='订单环节有哪些风险，风险能否定位到订单或客户',
        kinds=('fact', 'structure', 'data_gap', 'hypothesis', 'verified'), actions=True,
        max_causes=4,
        note='本卡交付风险定位；环节级假设不得填进具体订单行。'),
    'shipment-risk-summary': dict(
        question='发货目标缺口有多大，影响集中在哪些范围',
        kinds=('fact', 'structure', 'data_gap', 'hypothesis', 'verified'), actions=True,
        max_causes=4,
        note='商机储备不足只作为上游关联假设，不作为已确认的发货原因。'),
    'shipment-overdue-note': dict(
        question='哪些客户订单超期，超期原因是什么',
        kinds=('fact', 'data_gap'), actions=True, max_causes=3,
        causes_required=False,
        note='发货状态缺失时只交付待补数据与核查动作，不复用出货目标缺口分析。'),
    'shipment-cause-breakdown': dict(
        question='超期原因如何拆解，哪些原因有证据',
        kinds=('fact', 'data_gap', 'hypothesis'), actions=True, max_causes=4,
        causes_required=False,
        note='原因拆解必须有逐单或状态证据；否则只交付缺口与核查方向。'),
    'shipment-task-order': dict(
        question='针对当前风险应形成什么待确认的任务令草稿',
        kinds=('fact', 'structure', 'data_gap', 'hypothesis', 'verified'),
        actions=True, max_causes=5, actions_required=True,
        note='任务令为草稿：期限为建议值，责任角色待确认。'),
}

_MONEY = ('金额', '亿元', '万元', '元')
_ENERGY = ('电量', 'GWh', 'kWh', 'MWh', '兆瓦时', '度电', '出货量', '订单量', '数量', '台数')
_MONEY_TERMS = _MONEY + ('销售额', '发货金额', '订单金额', '变更金额', '损失金额', '营收',
                          'value', 'amount', 'revenue', 'sales value', 'price', 'cost', 'currency')
_ENERGY_TERMS = _ENERGY + ('发货量', '出货数量', 'shipment volume', 'shipment quantity',
                            'volume', 'quantity', 'units', 'energy')
_CROSS_UNIT = ('解释', '说明', '换算', '相加', '比较', '不足', '难以', '不能', '无法', '排除',
               '证明', '验证', '推断', '意味着', '支撑',
               'prove', 'proves', 'proven', 'explain', 'explains', 'explained',
               'cannot explain', 'cannot be explained', 'can not explain', "can't explain",
               'does not explain', "doesn't explain", 'insufficient to explain',
               'derive', 'derives', 'imply', 'implies', 'correspond', 'corresponds',
               'equal', 'equals')
_CAUSAL = ('导致', '因为', '由于', '造成', '使得', '致使', '因此', '根源', '之所以')
_DATA_GAP = ('缺失', '未返回', '为空', '空值', '无数据', '未取得', '无法取得', '查询失败',
             '口径不明', '未对账', '缺失值', '空记录', '证据缺口', '数据缺口', '口径冲突',
             '口径不一致', '口径差异', '证据不足')
_STRUCTURE = ('集中', '主要来自', '分布', '占比', '结构', '团队', '客户等级', '产品线', '区域')
_FACT = ('低于', '高于', '缺口', '逾期', '偏离', '超出', '下降', '上升', '未完成', '超期')
_UNDONE = ('逾期未完成', '超期未完成', '逾期且未完成', '逾期但未完成',
           '逾期仍未完成', '超期且未完成', '逾期未办结', '超期未办结')
_CAUSE = ('导致', '因为', '由于', '造成', '使得', '致使', '根源')
_CHANGE_TERMS = ('变更', '取消', 'cancelled', 'canceled', 'change', 'changed')
_LOSS_TERMS = ('损失', '亏损', '减值', 'loss', 'impairment', 'write-off', 'writeoff')
_CHANGE_AMOUNT_TERMS = ('变更金额', '取消金额', 'change amount', 'changed amount',
                        'cancelled value', 'canceled value', 'change value')
_INSTRUCTION_MARKERS = ('短摘要', '事实字段', '业务数值', '具体数值见', '不重复业务数字',
                        '不新造比例', '生成说明', '模型执行', '交付说明', '不要生成', '客户摘要')
_ACCEPTANCE_OK = ('清单', '对账', '确认', '记录', '核查', '复核', '台账', '证据', '留痕',
                  '拆解', '样本', '明细')
_MISSING_CAUSE = ('证据不足：当前分页/记录内没有可引用的逐单处理记录，暂不填写具体原因，'
                  '需先补齐订单状态、计划交付期与变更记录。')

ACTION_INVESTIGATION = 'investigation'
ACTION_REMEDIATION = 'remediation'
ACTION_PENDING = 'pending'
ACTION_TYPES = (ACTION_INVESTIGATION, ACTION_REMEDIATION, ACTION_PENDING)
DRAFTABLE_ACTION_TYPES = (ACTION_INVESTIGATION, ACTION_REMEDIATION)

_CAUSE_KINDS = ('verified', 'fact', 'structure', 'data_gap', 'hypothesis')
_INVESTIGATION_TERMS = ('核查', '核实', '核对', '对账', '补齐', '补数', '补充证据', '确认',
                        '复核', '排查', '检查', '验证', '梳理', '盘点', '取证',
                        'verify', 'check', 'confirm', 'reconcile', 'audit',
                        'investigate', 'validate')
_REMEDIATION_TERMS = ('调整', '重排', '优化', '协调', '提升', '增加', '减少', '更换',
                      '催办', '推进', '修订', '更新', '处置', '关闭',
                      'adjust', 'optimize', 'expedite', 'update', 'resolve')


def _text(value):
    return value.strip() if isinstance(value, str) else ''


def _sentences(text):
    return [part.strip() for part in re.split(r'[。；;\n]+', _text(text)) if part.strip()]


def _has_any(text, words):
    return any(word in text for word in words)


def _has_any_ci(text, words):
    value = _text(text).lower()
    return any(str(word).lower() in value for word in words)


def _strings(values):
    return [str(value) for value in (values or []) if str(value).strip()]


def _all_evidence_ids(evidence):
    ids = set()
    for key in ('facts', 'records', 'evidence'):
        for item in (evidence or {}).get(key) or []:
            if isinstance(item, dict) and item.get('id'):
                ids.add(str(item['id']))
    return ids


def _record_ids(evidence):
    ids = set()
    for item in (evidence or {}).get('records') or []:
        if isinstance(item, dict) and item.get('causeSupport', True) and item.get('id'):
            ids.add(str(item['id']))
    for item in (evidence or {}).get('evidence') or []:
        if isinstance(item, dict) and isinstance(item.get('record'), dict) and item.get('id'):
            ids.add(str(item['id']))
    return ids


def classify_cause(cause, records=None):
    """Classify a delivered cause by what the evidence actually supports.

    The title carries the claim; a causal word in the description must not turn
    a plain observation like "出货完成度低于目标" into a hypothesis.  Empty and
    missing-value statements are data quality, not structure.
    """
    records = records or set()
    title = _text((cause or {}).get('title'))
    description = _text((cause or {}).get('description'))
    text = title + '；' + description
    status = (cause or {}).get('status')
    if status == 'supported' and set(map(str, (cause or {}).get('evidenceIds') or [])) & records:
        return 'verified'
    if _has_any(title, _DATA_GAP):
        return 'data_gap'
    if _has_any(title, _STRUCTURE):
        return 'structure'
    if _has_any(title, _FACT):
        return 'fact'
    if (cause or {}).get('kind')=='hypothesis' and status=='hypothesis' and (_has_any(text,_CAUSE) or _has_any(title,('排程','排产','需求节奏','节点停滞','同步','等待','审批','产能','物料','资源','响应','协同'))):
        # A mechanism title already passed the factual/structure/gap checks.
        # Dimension names in its verification scope do not change its kind.
        return 'hypothesis'
    if _has_any(description, _DATA_GAP):
        return 'data_gap'
    if _has_any(description, _STRUCTURE):
        return 'structure'
    if _has_any(text, _CAUSE):
        return 'hypothesis'
    if _has_any(text, _FACT):
        return 'fact'
    return 'hypothesis'


def infer_action_type(action):
    """Classify an action without upgrading ambiguous legacy prose.

    New model output must state ``actionType`` explicitly.  This inference is
    retained for old cached cards: wording that clearly asks for verification
    becomes an investigation; wording that clearly asks for a business change
    becomes remediation.  Anything else stays ``pending`` and is not draftable.
    """
    declared = _text((action or {}).get('actionType'))
    if declared in ACTION_TYPES:
        return declared
    text = '；'.join(_text((action or {}).get(key)) for key in ('action', 'detail', 'acceptance'))
    if _has_any_ci(text, _INVESTIGATION_TERMS):
        return ACTION_INVESTIGATION
    if _has_any_ci(text, _REMEDIATION_TERMS):
        return ACTION_REMEDIATION
    return ACTION_PENDING


def normalize_delivery_contract(value, evidence=None):
    """Add v2 classifications without destroying legacy payloads.

    This function is deliberately non-rejecting: display can still show an old
    card while server-side draft selection applies the stricter rules.  User
    confirmation flags are always reset on model/cached output and can only be
    set while saving an editable draft.
    """
    out = deepcopy(value or {})
    records = _record_ids(evidence)
    causes = []
    for raw in out.get('causes') or []:
        if not isinstance(raw, dict):
            continue
        cause = deepcopy(raw)
        kind = _text(cause.get('kind'))
        if kind not in _CAUSE_KINDS:
            kind = classify_cause(cause, records)
        cause['kind'] = kind
        cause['evidenceIds'] = _strings(cause.get('evidenceIds'))
        cause['missingEvidence'] = _strings(cause.get('missingEvidence'))
        causes.append(cause)
    by_id = {str(cause.get('id')): cause for cause in causes if cause.get('id')}
    actions = []
    for raw in out.get('recommendations') or []:
        if not isinstance(raw, dict):
            continue
        action = deepcopy(raw)
        action['actionType'] = infer_action_type(action)
        action['causeIds'] = _strings(action.get('causeIds'))
        evidence_ids = _strings(action.get('evidenceIds'))
        if not evidence_ids:
            for cause_id in action['causeIds']:
                evidence_ids.extend(by_id.get(cause_id, {}).get('evidenceIds') or [])
        action['evidenceIds'] = list(dict.fromkeys(evidence_ids))
        action['ownerConfirmed'] = False
        action['deadlineConfirmed'] = False
        actions.append(action)
    out['causes'] = causes
    out['recommendations'] = actions
    return out


def validate_action_contract(value, evidence=None, *, seen=None, strict=False):
    """Validate action type, cause/evidence references and remediation support."""
    issues = []
    causes = {str(item.get('id')): item for item in (value or {}).get('causes') or []
              if isinstance(item, dict) and item.get('id')}
    available = _all_evidence_ids(evidence)
    queried = set(map(str, seen)) if seen is not None else set(available)
    for action in (value or {}).get('recommendations') or []:
        if not isinstance(action, dict):
            continue
        aid = _text(action.get('id')) or '未命名建议'
        action_type = _text(action.get('actionType')) or infer_action_type(action)
        if strict and action_type not in DRAFTABLE_ACTION_TYPES:
            issues.append(f'建议“{aid}”尚未明确为核查或改善动作，不能作为可下发建议')
            continue
        linked = set(_strings(action.get('causeIds')))
        unknown_causes = linked - set(causes)
        if unknown_causes:
            issues.append(f'建议“{aid}”引用了不存在或已被过滤的原因：{", ".join(sorted(unknown_causes))}')
        evidence_ids = set(_strings(action.get('evidenceIds')))
        if available:
            unknown_evidence = evidence_ids - available
            unread_evidence = evidence_ids - queried
            if unknown_evidence:
                issues.append(f'建议“{aid}”引用了不存在的证据：{", ".join(sorted(unknown_evidence))}')
            if unread_evidence:
                issues.append(f'建议“{aid}”引用了本轮未读取的证据：{", ".join(sorted(unread_evidence))}')
        if not evidence_ids and (strict or available):
            issues.append(f'建议“{aid}”缺少证据引用；需关联原因证据或数据缺口记录')
        if action_type == ACTION_REMEDIATION:
            if not linked:
                issues.append(f'改善建议“{aid}”必须关联已核实原因，不能直接引用风险事实或数据缺口')
            supported = [causes[item] for item in linked if item in causes
                         and causes[item].get('kind') == 'verified'
                         and causes[item].get('status') == 'supported']
            if linked and not supported:
                issues.append(f'改善建议“{aid}”关联的原因尚未得到记录支持，应先形成核查任务')
    if issues:
        raise ValueError('；'.join(dict.fromkeys(issues))[:1200])
    return value


def draft_selection_key(recommendation_ids):
    value = '|'.join(sorted(set(map(str, recommendation_ids or []))))
    return hashlib.sha256(value.encode('utf-8')).hexdigest()[:20]


def draftable_actions(value, evidence=None, recommendation_ids=None):
    """Return only actions that may become a task draft.

    ``recommendation_ids=None`` means all currently open draftable actions.
    Explicit ids are validated against the analysis, not trusted as task text.
    """
    normalized = normalize_delivery_contract(value, evidence)
    available = _all_evidence_ids(evidence)
    all_actions = {str(item.get('id')): item for item in normalized.get('recommendations') or []
                   if isinstance(item, dict) and item.get('id')}
    requested = None if recommendation_ids is None else list(dict.fromkeys(map(str, recommendation_ids)))
    ids = list(all_actions) if requested is None else requested
    missing = [item for item in ids if item not in all_actions]
    if missing:
        raise ValueError('建议已关闭、已过滤或不属于当前分析：' + '、'.join(missing))
    selected = [all_actions[item] for item in ids]
    rejected = []
    for action in selected:
        action_type = action.get('actionType') or infer_action_type(action)
        if action_type not in DRAFTABLE_ACTION_TYPES:
            rejected.append(f'建议“{action.get("id")}”尚待确认')
            continue
        try:
            validate_action_contract({'causes': normalized.get('causes') or [],
                                      'recommendations': [action]}, evidence,
                                     strict=bool(available))
        except ValueError as exc:
            rejected.append(str(exc))
    if rejected:
        raise ValueError('；'.join(dict.fromkeys(rejected))[:1200])
    return selected, draft_selection_key([action['id'] for action in selected])


def recommendation_empty_state(causes, recommendations):
    """Human-readable gap that matches what is actually missing."""
    causes = [item for item in causes or [] if isinstance(item, dict)]
    recommendations = [item for item in recommendations or [] if isinstance(item, dict)]
    if recommendations:
        types = {item.get('actionType') or infer_action_type(item) for item in recommendations}
        if types <= {ACTION_INVESTIGATION}:
            return '可先生成核查任务，改善措施待核实后补充。'
        return ''
    if causes and any((item.get('kind') or classify_cause(item)) == 'hypothesis' for item in causes):
        return '以下为待验证假设；当前无核查建议，暂不能生成任务草稿。'
    if causes:
        return '当前缺少明确核查对象或必要口径，暂不能生成任务草稿。'
    return '当前只能定位异常，缺少处理记录，尚未形成原因判断。'


def checkable_acceptance(text):
    return _has_any(_text(text), _ACCEPTANCE_OK)


def _evidence_text(evidence):
    parts = []
    for item in (evidence or {}).get('facts') or []:
        if isinstance(item, dict):
            parts.extend(_text(item.get(key)) for key in ('label', 'claim', 'definition'))
    for item in (evidence or {}).get('evidence') or []:
        if isinstance(item, dict):
            parts.append(_text(item.get('claim')) or _text(item.get('name')))
    parts.extend(_text(item) for item in (evidence or {}).get('limitations') or [])
    return '\n'.join(part for part in parts if part)


def _has_target_conflict(evidence):
    text = _evidence_text(evidence)
    return '冲突' in text or ('口径' in text and ('不一致' in text or '差异' in text))


def _missing_signing_structure(evidence):
    text = _evidence_text(evidence)
    return not any(word in text for word in ('已签', '未签', '签约', '签单', '订单状态'))


def _missing_overdue_status(evidence):
    text = _evidence_text(evidence).lower()
    return ('超期' in text or '逾期' in text or '发货状态' in text) and _has_any(
        text, ('缺失', '无数据', '未返回', '失败', '未取得'))


def _undone_status_evidence(evidence):
    """Evidence that actually reports an overdue *and* unfinished state.

    An enum description, a stage note or a bare "逾期" value is not support:
    only a fact with that status label and a value, or a record whose status
    carries it, may back "逾期未完成".
    """
    for item in (evidence or {}).get('facts') or []:
        if not isinstance(item, dict) or item.get('value') is None:
            continue
        if _has_any(_text(item.get('label')), _UNDONE):
            return True
    for key in ('records', 'evidence'):
        for item in (evidence or {}).get(key) or []:
            if not isinstance(item, dict):
                continue
            record = item.get('record') if isinstance(item.get('record'), dict) else item
            data = record.get('data') if isinstance(record.get('data'), dict) else {}
            nested = ' '.join(str(value) for name, value in data.items()
                              if '状态' in str(name) or str(name).lower() == 'status')
            if _has_any((_text(record.get('status')) + ' ' + nested).strip(), _UNDONE):
                return True
    return False


def reasoning_repair_locations(value, evidence=None):
    """Locate rejected unit comparisons without changing acceptance rules."""
    claims=[(['summary'],_text((value or {}).get('summary')))]
    claims += [(['findings',i],_text(f.get('title'))+'；'+_text(f.get('description')))
               for i,f in enumerate((value or {}).get('findings') or []) if isinstance(f,dict)]
    claims += [(['causes',i],_text(c.get('title'))+'；'+_text(c.get('description')))
               for i,c in enumerate((value or {}).get('causes') or []) if isinstance(c,dict)]
    claims += [(['recommendations',i],_text(a.get('action'))+'；'+_text(a.get('detail')))
               for i,a in enumerate((value or {}).get('recommendations') or []) if isinstance(a,dict)]
    issues=[dict(loc=loc,message='此句混用金额与电量；拆成独立观察，或删除比较推断，不要新增数字。',rejectedText=sentence)
            for loc,text in claims for sentence in _sentences(text) if _bad_unit_claim(sentence)]
    for loc,text in claims:
        for sentence in _sentences(text):
            if _bad_change_loss_claim(sentence,evidence):
                issues.append(dict(loc=loc,rejectedText=sentence,message='取消/变更金额不能写成损失；删去损失判断，保留状态金额事实与待核查范围。'))
            if _bad_set_claim(sentence,evidence) or _bad_attrition_claim(sentence,evidence):
                issues.append(dict(loc=loc,rejectedText=sentence,message='集合重叠和期间未核实，不能合计或排除缺口；删除该集合推断，分别保留原始观察。'))
    for i,cause in enumerate((value or {}).get('causes') or []):
        if not isinstance(cause,dict):continue
        kind=classify_cause(cause,_record_ids(evidence))
        text=_text(cause.get('title'))+'；'+_text(cause.get('description'))
        if kind in {'fact','structure','data_gap'} and _has_any(text,_CAUSE):
            issues.append(dict(loc=['causes',i],rejectedText=text,message='此对象是异常/结构/缺数，不能冒充原因。仅在确有机制线索时将标题与描述改成待验证机制，否则删除此原因并同步修改建议causeIds；保留直接引用证据的核查建议。'))
    for i,action in enumerate((value or {}).get('recommendations') or []):
        if isinstance(action,dict) and not checkable_acceptance(action.get('acceptance')):
            issues.append(dict(loc=['recommendations',i,'acceptance'],rejectedText=action.get('acceptance',''),
                message='验收改为可检查的清单、对账记录或确认记录；不要承诺经营结果。'))
    return issues


def validate_reasoning(value, evidence, *, stage='', slot='', business_only=False):
    """Raise ``ValueError`` when the delivered prose outruns its evidence."""
    issues = []
    original_actions = list((value or {}).get('recommendations') or [])
    strict_contract = any(any(key in action for key in (
        'actionType', 'evidenceIds', 'ownerConfirmed', 'deadlineConfirmed'))
        for action in original_actions if isinstance(action, dict))
    normalized = normalize_delivery_contract(value, evidence)
    summary = _text(normalized.get('summary'))
    causes = list(normalized.get('causes') or [])
    actions = list(normalized.get('recommendations') or [])
    records = _record_ids(evidence)

    # 1. Money and energy cannot be compared without an explicit bridge, and
    #    changed/cancelled value is not automatically a realised loss.
    claims = [summary]
    claims += [_text(d.get('title')) + '；' + _text(d.get('description'))
               for d in value.get('analysisDimensions') or [] if isinstance(d,dict)]
    claims += [_text(c.get('title')) + '；' + _text(c.get('description')) for c in causes]
    claims += [_text(f.get('title'))+'；'+_text(f.get('description')) for f in (value or {}).get('findings') or [] if isinstance(f,dict)]
    claims += [_text(a.get('action')) + '；' + _text(a.get('detail')) for a in actions]
    for claim in claims:
        for sentence in _sentences(claim):
            if _bad_unit_claim(sentence):
                issues.append('同一判断混用金额与电量口径：需要单价、产品结构或交期映射才能比较，请拆分或删除该推断')
            if _bad_set_claim(sentence, evidence):
                issues.append('取消/变更与中标未签两个集合的期间、重叠关系和是否对应当期应发货订单尚未验证，不能相加或据此排除缺口；请改为“尚不能建立与出货缺口的对应关系，需按订单和计划交付期间核对”')
            if _bad_attrition_claim(sentence, evidence):
                issues.append('变更/取消金额的占比或量级不能单独解释电量或出货缺口；需先核对集合关系、期间和单位口径')
            if _bad_change_loss_claim(sentence, evidence):
                issues.append('订单变更或取消金额不等于已实现损失；需先核实变更方向、净额、生效状态及订单集合')

    # 3. A target-total conflict must be visible in the summary, not only limits.
    if _has_target_conflict(evidence):
        disclosure='；'.join(value.get('limitations') or []) if business_only else summary
        if not ('口径' in disclosure and _has_any(disclosure, (
                '冲突', '不能汇总', '尚不能', '需核对', '未核对', '未对账',
                '未核实', '不一致', '不作比较', '不据此下结论', '各自观察',
                '各自口径', '不作达成结论', '口径并存'))):
            issues.append('证据披露了目标或指标口径冲突：摘要必须同时说明“各自口径下的观察”与“尚不能汇总对账”，不能只给明确缺口结论')

    # 4. Phenomena, structure and data gaps are not causes.
    for cause in causes:
        kind = classify_cause(cause, records)
        cause['kind'] = kind
        text = _text(cause.get('title')) + _text(cause.get('description'))
        if kind in {'fact', 'structure', 'data_gap'} and _has_any(text, _CAUSE):
            issues.append(f'原因“{_text(cause.get("title"))[:20]}”属于{KIND_LABELS[kind]}，不能写成因果关系；'
                          '请改成“可能为什么”的待验证假设，或移动为发现/结构定位')

    # 5. Missing overdue status cannot become per-order causes.
    if stage in {'shipment', 'combined'} and _missing_overdue_status(evidence):
        for cause in causes:
            if _has_any(_text(cause.get('title')), ('超期原因', '逾期原因', '根因')):
                issues.append('发货/超期状态数据缺失时不能给出超期原因或根因，只能交付待补数据与核查动作')
        for action in actions:
            if not _has_any(_text(action.get('action')), ('核查', '核对', '补齐', '确认', '复核', '对账')):
                issues.append('发货状态缺失时建议必须是核查/补齐动作，不能直接承诺改善结果')

    # 5b. "Overdue and unfinished" needs its own status value. Overdue alone,
    #     or an unreturned completion status, cannot prove "未完成".
    if any(_has_any(_text(claim), _UNDONE) for claim in claims) and not _undone_status_evidence(evidence):
        issues.append('“逾期未完成/超期未完成”必须有同环节明确的状态值或明细记录支持；'
                      '只有“逾期”或完成状态未返回时不能推出“未完成”。'
                      '请改为仅陈述逾期，并把完成状态缺口写入limitations。')

    # 6. Acceptance must be checkable.
    for action in actions:
        if not checkable_acceptance(action.get('acceptance')):
            issues.append('验收标准必须是可检查的清单、对账或确认记录，不能写“缺口不再扩大”等单一任务无法保证的结果')

    if strict_contract:
        try:
            validate_action_contract(normalized, evidence, strict=True)
        except ValueError as exc:
            issues.append(str(exc))

    # Lack of verified causality must not silently erase the next step.
    if stage in {'opportunity', 'order', 'shipment', 'combined'}:
        actionable = any(isinstance(f, dict) and f.get('id') and f.get('value') is not None
                         for f in (evidence or {}).get('facts') or [])
        actionable = actionable or any(isinstance(r, dict) and r.get('id') and r.get('data')
                                      for r in (evidence or {}).get('records') or [])
        if business_only and not (value.get('findings') or value.get('analysisDimensions')):
            actionable=False
        if actionable and not actions:
            issues.append('已有可定位的业务事实，不能仅因根因未确认而清空建议；请提交至少一项investigation核查动作，'
                          '直接引用已读取的证据，明确核查范围和可检查的清单/对账验收。'
                          'causes可以为空；禁止为挂建议编造原因，不得承诺改善结果，责任与期限待确认。')

    if issues:
        raise ValueError('；'.join(dict.fromkeys(issues))[:1200])
    return value


SET_REPLACEMENT = '当前汇总规模尚不能建立与出货缺口的对应关系，需按订单和计划交付期间核对'
UNIT_REPLACEMENT = '金额与电量口径不同，缺少单价、产品结构或交期映射，不能相互解释，需按统一口径补充映射后再判断'


def _without_comparison_prohibitions(sentence):
    # Remove only explicit prohibitions, not assertions such as "金额不足以解释电量".
    return re.sub(r'(?:不与|不将|不把|不做|不作|不进行|不得|不能|不可|不应|禁止|避免|未(?=相加|合计|比较|换算|合并)|未进行)[^，,。；;]{0,80}(?:比较|换算|相加|合计|合并)[^，,。；;]*', '', _text(sentence))


def _bad_set_claim(sentence, evidence):
    sentence = _without_comparison_prohibitions(sentence)
    sets = _has_any(sentence, ('取消', '变更')) and _has_any(sentence, ('中标未签', '未签'))
    claimed = _has_any(sentence, ('相加', '合计', '之和', '叠加', '不足以解释', '难以解释', '不能解释', '不足以', '规模不足'))
    if not (sets and claimed):
        return False
    # A sentence may legitimately sum two loss states and separately mention
    # cancellation and unsigned-contract amounts. Require the aggregation word
    # to follow both set subjects before rejecting it as a cross-set sum.
    first=max(sentence.find('取消'), sentence.find('变更'))
    second=max(sentence.find('中标未签'), sentence.find('未签'))
    if first < 0 or second < 0:
        return False
    tail=sentence[max(first, second):]
    return _has_any(tail, ('相加', '合计', '之和', '叠加', '不足以解释', '难以解释', '不能解释', '不足以', '规模不足')) and not (evidence or {}).get('setOverlapVerified')


def _bad_unit_claim(sentence):
    text = _without_comparison_prohibitions(sentence)
    text = re.sub(r'待验证(?:假设)?|待核实(?:假设)?', '', text)
    if re.search(r'(?:说明|核对|核查|确认|明确)[^，,。；;]{0,20}(?:金额与电量|金额和电量|电量与金额)[^，,。；;]{0,12}(?:计量口径|各自口径|单位定义)', text) and not _has_any(text,_CAUSAL):
        return False
    if _has_any(text,_DATA_GAP) and _has_any(text,('尚不能量化','无法量化','尚不能对账','尚不能汇总对账','尚不能判断','暂不能判断')) and not _has_any(text,('证明','解释','相加','换算','意味着')):
        return False
    if _has_any_ci(text, ('口径不同', '不同口径', '不能相互解释', '不能直接比较',
                          '需按统一口径', '需要映射', 'not comparable')):
        return False
    clauses = [part for part in re.split(r'[，,]', text) if part.strip()]
    if len(clauses)>1 and not _has_any_ci(text,('解释','证明','意味着','换算','相加','比较','补足','弥补','explain','prove')) and all(_has_any_ci(part,_MONEY_TERMS) or _has_any_ci(part,_ENERGY_TERMS) for part in clauses):
        return any(_bad_unit_claim(part) for part in clauses)
    bridge = ('换算','相加','比较','解释','证明','意味着','补足','弥补','覆盖',
              'prove','explain','derive','imply','correspond','equal')
    inferred = _has_any_ci(text,bridge)
    for prefix, suffix in (text.split('说明',1),) if '说明' in text else ():
        inferred = inferred or ((_has_any_ci(prefix,_MONEY_TERMS) and _has_any_ci(suffix,_ENERGY_TERMS))
                               or (_has_any_ci(prefix,_ENERGY_TERMS) and _has_any_ci(suffix,_MONEY_TERMS)))
    return (_has_any_ci(text, _MONEY_TERMS) and _has_any_ci(text, _ENERGY_TERMS) and inferred)


def _change_loss_verified(evidence):
    return any((evidence or {}).get(key) for key in (
        'changeDirectionVerified', 'netDecreaseVerified', 'changeEffectiveVerified', 'lossVerified'))


def _bad_change_loss_claim(sentence, evidence):
    text = _text(sentence)
    if _has_any_ci(text, ('不是损失', '不等于损失', '不能视为损失', 'not a loss',
                          'not equal to loss', 'cannot be treated as loss', 'no evidence of loss')):
        return False
    change_amount = (_has_any_ci(text, _CHANGE_AMOUNT_TERMS)
                     and _has_any_ci(text, _MONEY_TERMS))
    asserted_loss = (_has_any_ci(text, _LOSS_TERMS)
                     and _has_any_ci(text, ('是', '为', '等于', '构成', '造成', '计入',
                                            'is', 'are', 'equal', 'equals', 'means', 'represents')))
    return change_amount and asserted_loss and not _change_loss_verified(evidence)


def _bad_attrition_claim(sentence, evidence):
    sentence = _without_comparison_prohibitions(sentence)
    claim = _has_any_ci(sentence, ('量级有限', '规模有限', '占比不足', '不足以解释',
                                   '难以解释', '不能解释', '不足以',
                                   'insufficient to explain', 'cannot explain',
                                   'does not explain', "doesn't explain"))
    return (not (evidence or {}).get('setOverlapVerified')
            and _has_any_ci(sentence, _CHANGE_TERMS) and claim)


def _unsupported_inference(text, evidence):
    return any(_bad_set_claim(sentence, evidence) or _bad_unit_claim(sentence)
               or _bad_attrition_claim(sentence, evidence)
               or _bad_change_loss_claim(sentence, evidence)
               for sentence in _sentences(text))


def _norm(text):
    return re.sub(r'[。；;，,\s（）()]', '', _text(text))


_MD_IMAGE_RE = re.compile(r'!\[[^\]]*\]\([^)]*\)')
_MD_LINK_RE = re.compile(r'\[([^\]]*)\]\([^)]*\)')
_MD_HEADING_RE = re.compile(r'^\s{0,3}#{1,6}\s*', re.MULTILINE)
_MD_BLOCKQUOTE_RE = re.compile(r'^\s{0,3}>\s?', re.MULTILINE)
_MD_RULE_RE = re.compile(r'^\s{0,3}(?:-{3,}|\*{3,}|_{3,})\s*$', re.MULTILINE)
_MD_CODE_RE = re.compile(r'`([^`]*)`')
_MD_EMPHASIS_RE = re.compile(r'(\*\*|__)(.+?)\1')
_MD_BULLET_RE = re.compile(r'^\s{0,3}(?:[-*+•]|\d+[.)])\s+', re.MULTILINE)
_MD_INLINE_BULLET_RE = re.compile(r'(?<=[。；;，,\n])\s*[-*+•]\s+')


def plain_summary_text(value):
    """The card summary is plain text; never leak Markdown syntax into the UI."""
    text = _text(value)
    if not text:
        return ''
    text = _MD_IMAGE_RE.sub('', text)
    text = _MD_LINK_RE.sub(r'\1', text)
    text = _MD_HEADING_RE.sub('', text)
    text = _MD_BLOCKQUOTE_RE.sub('', text)
    text = _MD_RULE_RE.sub('', text)
    text = _MD_CODE_RE.sub(r'\1', text)
    text = _MD_EMPHASIS_RE.sub(r'\2', text)
    text = _MD_BULLET_RE.sub('', text)
    text = _MD_INLINE_BULLET_RE.sub(' ', text)
    text = text.replace('|', ' ')
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\s*\n\s*', ' ', text)
    return text.strip()


def sanitize_summary(text, evidence):
    """Remove unsupported inferences instead of only labelling them."""
    kept, seen, replaced = [], set(), set()
    for sentence in _sentences(plain_summary_text(text)):
        if any(token in sentence for token in ('短摘要不含业务数字', '具体数值见事实字段', '提交后用正常中文', '不要生成HTML')):
            continue
        key = _norm(sentence)
        if not key or key in seen:
            continue
        if _bad_set_claim(sentence, evidence) or _bad_unit_claim(sentence):
            replacement = UNIT_REPLACEMENT if _bad_unit_claim(sentence) else SET_REPLACEMENT
            if replacement not in replaced:
                kept.append(replacement)
                replaced.add(replacement)
            seen.add(key)
            continue
        if _bad_change_loss_claim(sentence, evidence):
            replacement = '订单变更金额不等于损失金额，需核实变更方向、净额及生效状态'
            if replacement not in replaced:
                kept.append(replacement)
                replaced.add(replacement)
            seen.add(key)
            continue
        clauses = [part.strip() for part in re.split(r'[,，]', sentence) if part.strip()]
        unsupported = [claim for claim in clauses
                       if (_bad_set_claim(claim, evidence) or _bad_unit_claim(claim)
                           or _bad_attrition_claim(claim, evidence)
                           or _bad_change_loss_claim(claim, evidence))]
        clean = [claim for claim in clauses
                 if claim not in unsupported and not _has_any_ci(claim, _INSTRUCTION_MARKERS)]
        if clean:
            kept.append('，'.join(clean))
            seen.add(key)
            continue
        if not unsupported:
            # The sentence only contained generation/delivery instructions.
            # Remove it without inventing an unrelated business conclusion.
            seen.add(key)
            continue
        replacement = UNIT_REPLACEMENT if any(_bad_unit_claim(claim) for claim in unsupported) \
            else SET_REPLACEMENT
        if replacement not in replaced:
            kept.append(replacement)
            replaced.add(replacement)
        seen.add(key)
    return ('。'.join(kept) + '。') if kept else ''


def evidence_count(evidence):
    """Count distinct evidence ids; the same record is not a second fact."""
    counts = (evidence or {}).get("counts") or {}
    if isinstance(counts, dict):
        try:
            distinct = int(counts.get("distinct"))
            if distinct >= 0:
                return distinct
        except (TypeError, ValueError):
            pass
    ids, extra = set(), 0
    for key in ('facts', 'records', 'evidence'):
        for item in (evidence or {}).get(key) or []:
            if isinstance(item, dict) and item.get('id'):
                ids.add(str(item['id']))
            elif item:
                extra += 1
    return len(ids) + extra


_LABEL_RE = re.compile(r'^\[(异常表现|结构定位|数据缺口|待验证假设|记录支持)\]\s*')


def _label(kind, title):
    label = KIND_LABELS.get(kind, '待验证假设')
    value = f'[{label}] {_LABEL_RE.sub("", _text(title))}'
    return value[:32]


def _strip_causal(text):
    value = _text(text)
    return value[:120]


def _suggest(action):
    value = _text(action)
    if not value.startswith('建议'):
        value = '建议：' + value
    return value[:64]


def _pending_owner(owner):
    value = _text(owner) or '待确认责任角色'
    if '待确认' not in value:
        value = f'{value}（建议角色，待确认）'
    return value[:40]


def _checkable(acceptance):
    value = _text(acceptance)
    if not checkable_acceptance(value):
        value = (value + '；以核查清单与对账记录为准').strip('；')
    return value[:180]


def suggestion_action(action):
    """Prefix a delivered measure so it reads as a suggestion, not a decision."""
    return _suggest(action)


def pending_owner(owner):
    return _pending_owner(owner)


def ensure_checkable(acceptance):
    return _checkable(acceptance)


def _balance(value):
    if value.count('（') > value.count('）'):
        value += '）'
    return value


def _with_note(summary, note):
    value = _text(summary).rstrip('。')
    if note and _norm(note) not in _norm(value):
        note = _text(note).strip('。；; ')
        value = (value + '。' + note) if value else note
    value = value + '。'
    if len(value) > 240:
        cut = value.rfind('。', 0, 240)
        value = value[:cut + 1] if cut >= 40 else value[:239] + '。'
    return _balance(value)[:240]


def project_card(item, slot):
    """Adapt one persisted stage card to the question a slot asks."""
    spec = SLOT_SPECS.get(slot)
    if not isinstance(item, dict) or not spec:
        return item
    out = deepcopy(item)
    result = out.get('result')
    if not isinstance(result, dict):
        return out
    if isinstance(result.get('ontologyJudgement'), dict):
        # Rule-first card: every risk, cause and advice is already settled by
        # the ontology judgement.  The projection below was built for
        # model-written cards (caps, re-ranking, rewording, filler dimensions)
        # and would change those results, so the card is delivered as built.
        findings = []
        for finding in result.get('findings') or []:
            finding = dict(finding)
            key = 'opp-v2:' + str(finding.get('riskCode') or finding.get('id'))
            finding.setdefault('riskKey', key)
            finding.setdefault('dedupeKey', key)
            findings.append(finding)
        result['findings'] = findings
        result['riskFindingCount'] = len(findings)
        result['deliveryContract'] = CONTRACT_VERSION
        result['slotQuestion'] = spec['question']
        out['result'] = result
        return out
    evidence = out.get('evidence') or {}
    result = normalize_delivery_contract(result, evidence)
    out['result'] = result
    records = _record_ids(evidence)
    available_evidence = _all_evidence_ids(evidence)
    # Missing per-order overdue status must not be answered with the shipment
    # target-gap analysis that happens to share the stage.
    suppress_gap = (slot in {'shipment-overdue-note', 'shipment-cause-breakdown', 'overdue-order-list'}
                    and _missing_overdue_status(evidence))
    kept = []
    for cause in result.get('causes') or []:
        if not isinstance(cause, dict):
            continue
        if _unsupported_inference(
                _text(cause.get('title')) + '；' + _text(cause.get('description')), evidence):
            continue
        kind = cause.get('kind') or classify_cause(cause, records)
        cause['kind'] = kind
        if spec['kinds'] is not None and kind not in spec['kinds']:
            continue
        if suppress_gap and kind != 'data_gap':
            continue
        if len(kept) >= spec['max_causes']:
            continue
        value = dict(cause)
        value['title'] = _label(kind, value.get('title'))
        if kind in {'fact', 'structure', 'data_gap'}:
            value['description'] = (_strip_causal(value.get('description')) +
                                    '（现象定位，不是已确认原因）')[:160]
        kept.append(value)
    order = {'fact': 0, 'structure': 1, 'data_gap': 2, 'hypothesis': 3, 'verified': 4}
    kept.sort(key=lambda cause: order.get(cause.get('kind'), 5))
    result['causes'] = kept
    result['summary'] = sanitize_summary(result.get('summary'), evidence)
    if suppress_gap:
        result['summary'] = _with_note(
            result.get('summary'), '当前缺少逐单超期状态证据，不复用出货目标缺口分析')
    if slot == 'order-sign-summary' and _missing_signing_structure(evidence):
        result['summary'] = _with_note(
            result.get('summary'), '当前证据未包含订单状态与已签/未签结构，不能解释签单结构')
    actions = []
    if spec['actions']:
        cause_map = {str(cause.get('id')): cause for cause in kept}
        for action in result.get('recommendations') or []:
            if not isinstance(action, dict):
                continue
            linked = [str(item) for item in (action.get('causeIds') or [])]
            # A linked cause that was filtered out is a dangling reference.  A
            # data-gap investigation may deliberately have no cause and cite
            # evidence directly.
            if linked and not set(linked) <= set(cause_map):
                original_ids={str(c.get('id')) for c in result.get('causes') or [] if isinstance(c,dict)}
                # result.causes is already projected; use the original stage causes.
                original_ids |= {str(c.get('id')) for c in (item.get('result') or {}).get('causes') or [] if isinstance(c,dict)}
                ids=set(_strings(action.get('evidenceIds')))
                independent=(action.get('actionType')==ACTION_INVESTIGATION and ids
                    and ids<=available_evidence and set(linked)<=original_ids
                    and not spec.get('table_slot') and not suppress_gap
                    and all(not _unsupported_inference(_text(c.get('title'))+'；'+_text(c.get('description')),evidence)
                            for c in (item.get('result') or {}).get('causes') or [] if str(c.get('id')) in linked))
                if not independent:
                    continue
                linked=[cid for cid in linked if cid in cause_map]
            evidence_ids = set(_strings(action.get('evidenceIds')))
            if available_evidence and evidence_ids - available_evidence:
                continue
            value = dict(action)
            value['causeIds']=linked
            action_type = value.get('actionType') or infer_action_type(value)
            reasons = []
            if action_type == ACTION_REMEDIATION:
                supported = [cause_map[item] for item in linked if item in cause_map
                             and cause_map[item].get('kind') == 'verified'
                             and cause_map[item].get('status') == 'supported']
                if not linked:
                    reasons.append('改善建议缺少已核实原因')
                elif not supported:
                    reasons.append('关联原因尚未得到记录支持')
            if available_evidence and not evidence_ids:
                reasons.append('缺少证据引用')
            if reasons:
                action_type = ACTION_PENDING
                value['actionTypeIssue'] = '；'.join(reasons)
            value['actionType'] = action_type
            value['action'] = _suggest(value.get('action'))
            value['ownerRole'] = _pending_owner(value.get('ownerRole'))
            value['acceptance'] = _checkable(value.get('acceptance'))
            actions.append(value)
    result['recommendations'] = actions
    context = out.get('context') or {}
    result['findings'] = build_risk_findings(
        result, evidence, context, dict(slotId=slot, stage=context.get('stage')))
    result['riskFindingCount'] = len(result['findings'])
    from .business_presentation import BUSINESS_SLOTS,present_business_result
    if slot in BUSINESS_SLOTS:
        result['limitations']=list(dict.fromkeys((result.get('limitations') or [])+([spec['note']] if spec.get('note') else [])))
    else:
        result['summary'] = _with_note(result.get('summary'), spec.get('note'))
    if slot in BUSINESS_SLOTS:
        result=present_business_result(result)
        result['riskFindingCount']=len(result['findings'])
    result['deliveryContract'] = CONTRACT_VERSION
    result['slotQuestion'] = spec['question']
    out['result'] = result
    return out


def publication_payload(item):
    """Trim browser delivery only; full evidence remains in analysis history."""
    if not item:
        return item
    from copy import deepcopy
    result = deepcopy(item)
    context = result.get('context') or {}
    for key in ('chartQueries', 'unavailableQueries', 'apReceiptIds', 'pgReceiptIds', 'clarifications'):
        context.pop(key, None)
    for fact in (result.get('evidence') or {}).get('facts') or []:
        if isinstance(fact.get('claim'), dict):
            fact['claim'] = {key: fact['claim'][key] for key in ('id', 'statement') if key in fact['claim']}
    return result
