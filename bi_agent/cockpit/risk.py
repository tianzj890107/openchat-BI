"""Structured risk findings and top-level risk counts."""
from __future__ import annotations

import hashlib
import math
import re
from typing import Any


RISK_FACT = 'risk_fact'
RISK_IDENTITY_VERSION = 'cockpit-risk-identity-v2'
DOMAINS = ('sales', 'shipment')

_TARGET = re.compile(r'(?:年度|全年|月度|当月|累计|预算|计划|目标)(?:值|数)?$', re.I)
_TARGET_ANY = re.compile(r'目标|预算|计划值|target|budget', re.I)
_ACTUAL_ANY = re.compile(r'实际|当前|已完成|完成值|actual|current|real', re.I)
_HIGHER_IS_WORSE = ('天数', '周转', '超期', '逾期', '账龄', '周期', '成本', '费用',
                    '库存', '用量', '风险', '时长', 'delay', 'days')
_SALES_WORDS = ('销售', '签单', '签约', '商机', '投标', '报价', '订单接收', '订单',
                '金额', '收入', '利润', '毛利', '净利', '应收', '回款', 'sales',
                'quotation', 'bid', 'opportunity', 'order')
_SHIPMENT_WORDS = ('发货', '出货', '交付', '超期', '逾期', '物流', '运输', 'shipment',
                   'delivery', 'overdue', 'logistics')


def _text(value: Any) -> str:
    return '' if value is None else str(value).strip()


def _normalise(value: Any) -> str:
    return re.sub(r'[\s·•,，。；;：:()（）\[\]【】/\\_-]+', '', _text(value)).lower()


def _available_evidence(evidence: dict | None) -> set[str]:
    found = set()
    for key in ('facts', 'records', 'evidence'):
        for item in (evidence or {}).get(key) or []:
            if not isinstance(item, dict) or not item.get('id'):
                continue
            found.add(str(item['id']))
            if isinstance(item.get('record'), dict) and item['record'].get('id'):
                found.add(str(item['record']['id']))
    return found


def _scope_key(context: dict | None) -> str:
    context = context or {}
    return _text(context.get('dataFingerprint') or context.get('snapshotId')
                 or context.get('scope') or context.get('page'))


def _domain_from_text(*values: Any) -> str:
    text = ' '.join(_text(value) for value in values).lower()
    shipment = any(word.lower() in text for word in _SHIPMENT_WORDS)
    sales = any(word.lower() in text for word in _SALES_WORDS)
    if shipment and not sales:
        return 'shipment'
    if sales and not shipment:
        return 'sales'
    return ''


def _slot_domain(slot: dict | None) -> str:
    stage = _text((slot or {}).get('stage'))
    if stage == 'shipment':
        return 'shipment'
    if stage in {'opportunity', 'bid', 'quotation', 'order'}:
        return 'sales'
    return ''


def _finding_domain(finding: dict, slot: dict | None = None) -> str:
    explicit = _text(finding.get('riskDomain')).lower()
    if explicit in DOMAINS:
        return explicit
    inferred = _domain_from_text(
        ' '.join(str(value) for value in finding.get('metricCodes') or []),
        finding.get('title'), finding.get('description'))
    return inferred or _slot_domain(slot)


def _metric_codes(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [value for value in dict.fromkeys(_text(item) for item in raw) if value][:12]


def _fingerprint(*parts: Any) -> str:
    value = '|'.join(_normalise(part) for part in parts if _text(part))
    return hashlib.sha256(value.encode('utf-8')).hexdigest()[:16]


def _business_issue(finding: dict) -> tuple[str, str]:
    """Versioned business identity shared by node cards and combined cards.

    Codes identify measures, not incidents. Only reviewed semantic rules merge
    different titles; unknown issues retain their title rather than collapsing
    all risks mentioning the same measure.
    """
    codes = set(finding.get('metricCodes') or [])
    title = _normalise(finding.get('title'))
    if ('出货量' in title or '发货电量' in title) and any(w in title for w in ('目标', '达成')):
        customer = any(w in title for w in ('客户', '等级'))
        return ('shipment', 'customer-shipment-target-gap' if customer else 'shipment-target-gap')
    if {'YWLN_M_CUSTOMER_TARGET_ENERGY', 'YWLN_M_CUSTOMER_ACTUAL_ENERGY'} <= codes and '客户' in title and '商机' not in title:
        return 'shipment', 'customer-shipment-target-gap'
    if '商机' in title and any(w in title for w in ('目标', '覆盖')) and any(w in title for w in ('不足', '低于', '缺口', '未达')) and not any(w in title for w in ('客户', '等级')):
        return 'sales', 'opportunity-target-gap'
    if '商机' in title and '未签单' in title and any(w in title for w in ('为零', '零值')):
        return 'sales', 'unsigned-opportunity-zero'
    if '报价' in title and '逾期' in title:
        return 'sales', 'quotation-overdue'
    if '投标' in title and '周期' in title:
        return 'sales', 'bid-cycle-overrun'
    if '投标' in title and '丢标' in title:
        return 'sales', 'bid-lost'
    if '投标' in title and '逾期' in title:
        return 'sales', 'bid-overdue'
    if '订单' in title and any(w in title for w in ('逾期','超期')):
        return 'sales','order-overdue'
    if '订单' in title and '周期' in title:
        return 'sales','order-cycle-overrun'
    if ('出货' in title or '发货' in title) and any(w in title for w in ('连续下降','连续回落','骤降','峰值后','持续回落')):
        segment = next((word for word in ('pack','电芯','模组') if word in title),'overall')
        return 'shipment','shipment-trend:'+segment
    if '订单' in title and any(w in title for w in ('取消', '变更')) and '中标未签' not in title:
        return 'sales', 'order-cancel-change'
    if '商机' in title and any(w in title for w in ('未进入投标', '未投标')):
        # PACK and other populations must not collapse into a global issue.
        return 'sales', 'opportunity-not-bidding:' + ('pack' if 'pack' in title else title)
    return '', 'title:' + title


def _dedupe_key(finding: dict) -> str:
    domain, issue = _business_issue(finding)
    domain = domain or _finding_domain(finding)
    return domain + ':' + issue


def _model_finding(item: Any, evidence: dict | None, context: dict | None,
                   slot: dict | None) -> dict | None:
    if not isinstance(item, dict) or item.get('kind') != RISK_FACT:
        return None
    codes = _metric_codes(item.get('metricCodes'))
    ids = [str(value) for value in item.get('evidenceIds') or [] if _text(value)]
    available = _available_evidence(evidence)
    if not codes or not ids or not set(ids) <= available:
        return None
    title = _text(item.get('title'))
    if not title:
        return None
    finding = dict(
        id=_text(item.get('id')) or 'risk-' + _fingerprint(codes, title),
        kind=RISK_FACT,
        title=title[:80],
        description=_text(item.get('description'))[:320],
        metricCodes=codes,
        evidenceIds=list(dict.fromkeys(ids))[:20],
        scopeKey=_scope_key(context or ((slot or {}).get('context') or {})),
    )
    explicit = _text(item.get('riskDomain')).lower()
    finding['riskDomain'] = explicit if explicit in DOMAINS else _finding_domain(finding, slot)
    finding['dedupeKey'] = _dedupe_key(finding)
    return finding


def _legacy_cause_finding(cause: Any, evidence: dict | None, context: dict | None,
                          slot: dict | None) -> dict | None:
    if not isinstance(cause, dict):
        return None
    kind = _text(cause.get('kind'))
    if not kind:
        from .delivery import classify_cause
        kind = classify_cause(cause)
    if kind != 'fact':
        return None
    ids = [str(value) for value in cause.get('evidenceIds') or [] if _text(value)]
    if not ids or not set(ids) <= _available_evidence(evidence):
        return None
    title = _text(cause.get('title'))
    if not title:
        return None
    codes = _metric_codes(cause.get('metricCodes')) or ['label:' + _normalise(title)]
    finding = dict(
        id='legacy-' + _fingerprint(cause.get('id'), title, codes),
        kind=RISK_FACT,
        title=title[:80],
        description=_text(cause.get('description'))[:320],
        metricCodes=codes,
        evidenceIds=list(dict.fromkeys(ids))[:20],
        scopeKey=_scope_key(context),
    )
    finding['riskDomain'] = _finding_domain(finding, slot)
    finding['dedupeKey'] = _dedupe_key(finding)
    return finding


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _fact_parts(item: Any) -> dict | None:
    if not isinstance(item, dict) or not item.get('id'):
        return None
    label = _text(item.get('label') or item.get('name'))
    if not label:
        return None
    match = re.match(r'^(.*?)(?:\[([^\]]+)\])?$', label)
    label = _text(match.group(1)) if match else label
    code = _text(item.get('identifierCode') or item.get('metricCode')
                 or (match.group(2) if match else ''))
    unit_match = re.search(r'[（(]([^）)]+)[）)]', label)
    unit = _text(item.get('unit') or (unit_match.group(1) if unit_match else ''))
    clean = re.sub(r'[（(][^）)]*[）)]', '', label)
    target = bool(_TARGET_ANY.search(clean) or _TARGET_ANY.search(code))
    actual = bool(_ACTUAL_ANY.search(clean) or _ACTUAL_ANY.search(code))
    base = clean
    if target:
        base = _TARGET.sub('', base)
        base = re.sub(r'目标|预算|计划', '', base)
    if actual:
        base = re.sub(r'实际|当前|已完成|完成值', '', base)
    base = re.sub(r'^(年度|全年|月度|当月|累计)', '', base).strip()
    base = re.sub(r'(值|数)$', '', base).strip()
    if not base:
        return None
    value = _number(item.get('value'))
    return dict(id=str(item['id']), label=label.strip(), code=code, unit=unit,
                base=base, target=target, actual=actual, value=value)


def _metric_findings(evidence: dict | None, context: dict | None,
                     slot: dict | None) -> list[dict]:
    groups: dict[tuple[str, str], list[dict]] = {}
    for item in (evidence or {}).get('facts') or []:
        parts = _fact_parts(item)
        if not parts:
            continue
        groups.setdefault((_normalise(parts['base']), _normalise(parts['unit'])), []).append(parts)
    findings = []
    for (_, _unit), values in groups.items():
        targets = [item for item in values if item['target'] and item['value'] is not None]
        if len(targets) != 1:
            continue
        target = targets[0]
        actuals = [item for item in values if item is not target
                   and item['value'] is not None and not item['target']]
        if len(actuals) != 1:
            continue
        actual = actuals[0]
        base_text = target['base'].lower()
        higher_worse = any(word in base_text for word in _HIGHER_IS_WORSE)
        worse = actual['value'] > target['value'] if higher_worse else actual['value'] < target['value']
        relation = '高于' if actual['value'] > target['value'] else '低于'
        if not worse:
            continue
        domain = _domain_from_text(target['base'], actual['base'], target['code'], actual['code'],
                                   (slot or {}).get('stage'))
        codes = [value for value in (target['code'], actual['code']) if value]
        if not codes:
            codes = ['label:' + _normalise(target['base'])]
        finding = dict(
            id='metric-' + _fingerprint(domain, target['base'], codes),
            kind=RISK_FACT,
            title=f"{target['base']}{relation}目标"[:80],
            description=f"当前口径下{target['base']}{relation}目标，需核实影响范围与口径一致性。",
            metricCodes=list(dict.fromkeys(codes))[:12],
            evidenceIds=[target['id'], actual['id']],
            scopeKey=_scope_key(context),
            riskDomain=domain,
        )
        finding['dedupeKey'] = _dedupe_key(finding)
        findings.append(finding)
    return findings


def risk_priority_key(finding):
    """Versioned display order, not an unapproved quantitative severity grade."""
    _domain,issue=_business_issue(finding)
    title=_normalise(finding.get('title'))
    if 'overdue' in issue or any(w in title for w in ('超期未发','逾期未完成','交付违约')):
        priority=0
    elif 'target-gap' in issue or any(w in title for w in ('连续下降','连续回落','骤降','持续下降')):
        priority=1
    elif issue in {'bid-cycle-overrun','order-cycle-overrun','bid-lost','order-cancel-change'} or 'not-bidding' in issue:
        priority=2
    else:
        priority=3
    return priority,_dedupe_key(finding)


def build_risk_findings(result: dict, evidence: dict | None, context: dict | None,
                        slot: dict | None) -> list[dict]:
    """Return deduplicated, evidence-backed risk facts for one delivered slot."""
    accepted: list[dict] = []
    issue_keys: set[str] = set()

    def add(finding: dict | None):
        if not finding:
            return
        domain, _issue = _business_issue(finding)
        if domain:
            finding['riskDomain'] = domain
        key = _dedupe_key(finding)
        if key in issue_keys:
            return
        issue_keys.add(key)
        finding['riskKey'] = key
        finding['dedupeKey'] = key
        accepted.append(finding)

    for item in (result or {}).get('findings') or []:
        add(_model_finding(item, evidence, context, slot))
    for item in _metric_findings(evidence, context, slot):
        add(item)
    if not accepted:
        for cause in (result or {}).get('causes') or []:
            add(_legacy_cause_finding(cause, evidence, context, slot))
    return sorted(accepted,key=risk_priority_key)


def summarize_risk_counts(slots: dict[str, dict]) -> dict[str, dict]:
    """Count current-scope risk facts by top-level KPI domain."""
    result = {}
    for domain in DOMAINS:
        relevant = [slot for slot in slots.values()
                    if _slot_domain(slot) == domain or any(
                        (_business_issue(item)[0] or _finding_domain(item, slot)) == domain
                        for item in (((slot.get('payload') or {}).get('result') or {}).get('findings') or [])
                        if isinstance(item, dict))]
        ready = [slot for slot in relevant
                 if slot.get('status') == 'ready'
                 and isinstance((slot.get('payload') or {}).get('result'), dict)]
        unique = {}
        for slot_id, slot in slots.items():
            if slot.get('status') != 'ready' or not isinstance((slot.get('payload') or {}).get('result'), dict):
                continue
            for item in ((slot.get('payload') or {}).get('result') or {}).get('findings') or []:
                if not isinstance(item, dict) or item.get('kind') != RISK_FACT:
                    continue
                resolved_domain = _business_issue(item)[0] or _finding_domain(item, slot)
                if resolved_domain != domain:
                    continue
                key = _dedupe_key({**item, 'riskDomain': resolved_domain})
                entry = unique.setdefault(key, dict(riskKey=key, title=item.get('title', ''),
                    description=item.get('description', ''), riskDomain=domain, sources=[]))
                entry['sources'].append(dict(slotId=slot_id,
                    analysisId=(slot.get('payload') or {}).get('id', ''),
                    evidenceIds=list(item.get('evidenceIds') or [])))
        scope_match = all(slot.get('scopeMatch') is not False for slot in relevant)
        complete = bool(relevant) and len(ready) == len(relevant)
        known = complete and scope_match
        result[domain] = dict(
            identityVersion=RISK_IDENTITY_VERSION,
            count=len(unique),
            known=known,
            complete=complete,
            scopeMatch=scope_match,
            sourceSlots=len(relevant),
            readySlots=len(ready),
            findingKeys=sorted(unique),
            findings=[unique[key] for key in sorted(unique)],
        )
    return result
