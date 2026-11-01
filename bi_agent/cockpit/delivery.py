"""Per-slot delivery contracts and reasoning checks.

One stage analysis can feed several UI slots.  This module adapts the same
evidence-backed analysis to the question each slot actually asks, and rejects
prose the evidence cannot support: phenomena presented as causes, money/energy
comparisons without a unit bridge, unverified set arithmetic, hidden target
conflicts and acceptance criteria that a single task cannot guarantee.
"""
from __future__ import annotations

import re
from copy import deepcopy

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
        kinds=('fact', 'structure', 'data_gap'), actions=True, max_causes=4,
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
        question='商机风险集中在哪些团队、客户等级和项目',
        kinds=('fact', 'structure', 'data_gap', 'hypothesis'), actions=True,
        max_causes=5,
        note='本卡交付商机缺口的结构定位；缺口分布不等于业务原因。'),
    'opportunity-coverage-note': dict(
        question='商机覆盖缺口在哪里，目标与实际的差异如何理解',
        kinds=('fact', 'structure', 'data_gap'), actions=True, max_causes=4,
        note='本卡交付覆盖结构与数据缺口，不把目标为空当成原因。'),
    'order-risk-summary': dict(
        question='订单环节有哪些风险，风险能否定位到订单或客户',
        kinds=('fact', 'structure', 'data_gap', 'hypothesis'), actions=True,
        max_causes=4,
        note='本卡交付风险定位；环节级假设不得填进具体订单行。'),
    'shipment-risk-summary': dict(
        question='发货目标缺口有多大，影响集中在哪些范围',
        kinds=('fact', 'structure', 'data_gap', 'hypothesis'), actions=True,
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
_CAUSE = ('导致', '因为', '由于', '造成', '使得', '致使', '根源')
_CHANGE_TERMS = ('变更', '取消', 'cancelled', 'canceled', 'change', 'changed')
_LOSS_TERMS = ('损失', '亏损', '减值', 'loss', 'impairment', 'write-off', 'writeoff')
_CHANGE_AMOUNT_TERMS = ('变更金额', '取消金额', 'change amount', 'changed amount',
                        'cancelled value', 'canceled value', 'change value')
_INSTRUCTION_MARKERS = ('短摘要', '事实字段', '业务数值', '具体数值见', '不重复业务数字',
                        '不新造比例', '生成说明', '模型执行', '交付说明', '不要生成', '客户摘要')
_ACCEPTANCE_OK = ('清单', '对账', '确认', '记录', '核查', '复核', '台账', '证据', '留痕')
_MISSING_CAUSE = ('证据不足：当前分页/记录内没有可引用的逐单处理记录，暂不填写具体原因，'
                  '需先补齐订单状态、计划交付期与变更记录。')


def _text(value):
    return value.strip() if isinstance(value, str) else ''


def _sentences(text):
    return [part.strip() for part in re.split(r'[。；;\n]+', _text(text)) if part.strip()]


def _has_any(text, words):
    return any(word in text for word in words)


def _has_any_ci(text, words):
    value = _text(text).lower()
    return any(str(word).lower() in value for word in words)


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
    if _has_any(description, _DATA_GAP):
        return 'data_gap'
    if _has_any(description, _STRUCTURE):
        return 'structure'
    if _has_any(text, _CAUSE):
        return 'hypothesis'
    if _has_any(text, _FACT):
        return 'fact'
    return 'hypothesis'


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


def validate_reasoning(value, evidence, *, stage='', slot=''):
    """Raise ``ValueError`` when the delivered prose outruns its evidence."""
    issues = []
    summary = _text((value or {}).get('summary'))
    causes = list((value or {}).get('causes') or [])
    actions = list((value or {}).get('recommendations') or [])
    records = _record_ids(evidence)

    # 1. Money and energy cannot be compared without an explicit bridge, and
    #    changed/cancelled value is not automatically a realised loss.
    claims = [summary]
    claims += [_text(c.get('title')) + '；' + _text(c.get('description')) for c in causes]
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
        if not ('口径' in summary and _has_any(summary, ('冲突', '不能汇总', '尚不能', '需核对', '未对账', '各自观察'))):
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

    # 6. Acceptance must be checkable.
    for action in actions:
        if not checkable_acceptance(action.get('acceptance')):
            issues.append('验收标准必须是可检查的清单、对账或确认记录，不能写“缺口不再扩大”等单一任务无法保证的结果')

    if issues:
        raise ValueError('；'.join(dict.fromkeys(issues))[:1200])
    return value


SET_REPLACEMENT = '当前汇总规模尚不能建立与出货缺口的对应关系，需按订单和计划交付期间核对'
UNIT_REPLACEMENT = '金额与电量口径不同，缺少单价、产品结构或交期映射，不能相互解释，需按统一口径补充映射后再判断'


def _bad_set_claim(sentence, evidence):
    sets = _has_any(sentence, ('取消', '变更')) and _has_any(sentence, ('中标未签', '未签'))
    claimed = _has_any(sentence, ('相加', '合计', '之和', '叠加', '不足以解释', '难以解释', '不能解释', '不足'))
    return sets and claimed and not (evidence or {}).get('setOverlapVerified')


def _bad_unit_claim(sentence):
    text = _text(sentence)
    if _has_any_ci(text, ('口径不同', '不同口径', '不能相互解释', '不能直接比较',
                          '需按统一口径', '需要映射', 'not comparable')):
        return False
    return (_has_any_ci(text, _MONEY_TERMS) and _has_any_ci(text, _ENERGY_TERMS)
            and _has_any_ci(text, _CROSS_UNIT))


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
    claim = _has_any_ci(sentence, ('量级有限', '规模有限', '占比不足', '不足以解释',
                                   '难以解释', '不能解释', '不足以', '难以', '不能',
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


def sanitize_summary(text, evidence):
    """Remove unsupported inferences instead of only labelling them."""
    kept, seen, replaced = [], set(), set()
    for sentence in _sentences(text):
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
    for word in ('导致', '因为', '由于', '造成', '使得', '致使'):
        value = value.replace(word, '；')
    return value.strip('； ')[:120]


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
    evidence = out.get('evidence') or {}
    records = _record_ids(evidence)
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
        kind = classify_cause(cause, records)
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
        cause_ids = {str(cause.get('id')) for cause in kept}
        for action in result.get('recommendations') or []:
            if not isinstance(action, dict):
                continue
            # Every referenced cause must still exist.  A partially dangling
            # reference is a contract error, not a usable suggestion.
            linked = [str(item) for item in (action.get('causeIds') or [])]
            if not linked or not set(linked) <= cause_ids:
                continue
            value = dict(action)
            value['action'] = _suggest(value.get('action'))
            value['ownerRole'] = _pending_owner(value.get('ownerRole'))
            value['acceptance'] = _checkable(value.get('acceptance'))
            actions.append(value)
    result['recommendations'] = actions
    result['summary'] = _with_note(result.get('summary'), spec.get('note'))
    result['deliveryContract'] = CONTRACT_VERSION
    result['slotQuestion'] = spec['question']
    out['result'] = result
    return out
