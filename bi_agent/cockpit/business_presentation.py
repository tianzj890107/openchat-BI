"""Evidence-backed business dimensions, separate from causal claims and data gaps."""
from copy import deepcopy
import re

BUSINESS_SLOTS={'opportunity-risk','order-risk-summary','shipment-risk-summary','sales-shipment-issues'}
CONTRACT_METRIC_CODES={'YWLN_M0142','YWLN_M0179','YWLN_M0194','YWLN_M0195','YWLN_M0198'}


def normalize_business_terms(text, metric_codes=()):
    """Use contract wording only when the source actually carries contract semantics."""
    value=str(text or '')
    contract_signal='合同' in value or '中标未签' in value
    opportunity_signing='商机' in value and any(w in value for w in ('未签单','已签单','待签单'))
    if not contract_signal and not opportunity_signing and not (set(metric_codes or ()) & CONTRACT_METRIC_CODES):
        return value
    replacements=(('已中标未签单','已中标合同签订未确认'),('中标未签单','中标合同签订未确认'),
                  ('中标未签','中标合同签订未确认'),
                  ('未签单','合同签订未确认'),('已签单','合同已签订'),
                  ('待签单','待合同签订'),('商机签单','合同签订确认状态'))
    for source,target in replacements:value=value.replace(source,target)
    return value


def business_text(text, metric_codes=()):
    """Keep business observations; move data-gap sentences to limitations."""
    value=normalize_business_terms(text,metric_codes)
    kept=[];removed=[]
    for sentence in re.split(r'(?<=[。；;])\s*',value):
        sentence=sentence.strip()
        if not sentence:continue
        (removed if data_limitation(sentence) else kept).append(sentence)
    return ''.join(kept).strip(),removed


def data_limitation(text):
    text=str(text or '')
    if any(w in text for w in ('为空','空值','未返回','未提供','未配置','无法评估','无法计算','无法判断','尚不能汇总','不能汇总对账','尚不能对账')):return True
    if any(w in text for w in ('指标','字段','数据','口径','SQL','AP','接口','查询','取数','证据')) and any(w in text for w in ('缺失','缺少','不足','失败','不一致','冲突','不完整')):return True
    return any(w in text for w in ('待验证假设','本次分析未取得','本轮暂无新增经营结论','缺口分布不等于业务原因','原因尚待验证','原因尚未验证','原因仍待核实','原因均为待验证','跨环节结论必须','不汇总缺口','只交付各自观察','本轮已取到','本轮仅取到','本轮已取得','本卡交付','本卡只交付','此处只交付','不作为已确认','不得填入'))


def business_finding(finding):
    if not isinstance(finding,dict) or not finding.get('title') or data_limitation(finding['title']):return False
    text=normalize_business_terms(str(finding.get('title',''))+'；'+str(finding.get('description','')),finding.get('metricCodes') or ())
    if any(w in text for w in ('未签单','已签单','未签商机','已签商机','待签单','中标未签')) and '合同' not in text:return False
    return True


STAGE_LABELS={'overview':'经营概况','opportunity':'商机获取','quotation':'报价','bid':'投标','contract':'合同签订','order':'订单接收','shipment':'发货'}


def finding_stage(finding):
    if finding.get('stage') in STAGE_LABELS:return finding['stage']
    text=str(finding.get('title') or '')
    for stage,words in [('contract',('合同','签单')),('quotation',('报价',)),('bid',('投标','中标','丢标','弃标')),('shipment',('发货','出货','未发','交付')),('opportunity',('商机','获客')),('order',('订单','接收'))]:
        if any(w in text for w in words):return stage
    return 'overview'


def legacy_dimensions(findings):
    """One observed risk per business-stage row; no invented root cause."""
    return [dict(id='dimension-'+str(i+1),stage=finding_stage(f),title=STAGE_LABELS[finding_stage(f)],
                 description=str(f.get('description') or f['title'])[:640],findingIds=[f['id']],evidenceIds=f.get('evidenceIds',[])[:20])
            for i,f in enumerate(findings[:4])]


def present_business_result(result):
    """Projection only: preserve source records and internal task/cause contracts."""
    out=deepcopy(result);limits=list(out.get('limitations') or [])
    original=out.get('findings') or []
    for f in original:
        if not isinstance(f,dict):continue
        codes=f.get('metricCodes') or ()
        f['title']=normalize_business_terms(f.get('title'),codes)
        f['description']=normalize_business_terms(f.get('description'),codes)
    out['summary']=normalize_business_terms(out.get('summary'))
    for dimension in out.get('analysisDimensions') or []:
        if isinstance(dimension,dict):
            codes={code for f in original if f.get('id') in (dimension.get('findingIds') or []) for code in (f.get('metricCodes') or [])}
            dimension['title'],title_gaps=business_text(dimension.get('title'),codes)
            dimension['description'],description_gaps=business_text(dimension.get('description'),codes)
            limits.extend(title_gaps+description_gaps)
    finding_ids={str(f.get('id')) for f in out.get('findings') or [] if isinstance(f,dict) and f.get('id')}
    for action in out.get('recommendations') or []:
        if isinstance(action,dict):
            action['action']=normalize_business_terms(action.get('action'))
            action['detail']=normalize_business_terms(action.get('detail'))
            action['acceptance']=normalize_business_terms(action.get('acceptance'))
            action['findingIds']=[fid for fid in action.get('findingIds') or () if str(fid) in finding_ids]
    out['findings']=[f for f in original if business_finding(f)]
    for f in original:
        if not business_finding(f):limits.append(str(f.get('title',''))+'：'+str(f.get('description','')))
    clean=[];removed=False
    original_summary=str(out.get('summary') or '')
    for clause in re.split(r'[。；;]+|(?<!\d)[，,]|[，,](?!\d)',original_summary):
        clause=clause.strip()
        if not clause:continue
        if data_limitation(clause) or (any(w in clause for w in ('可能','推测','假设','疑似')) and any(w in clause for w in ('因为','导致','造成','根因'))):limits.append(clause);removed=True
        else:clean.append(clause)
    summary='；'.join(clean) if removed else original_summary.strip()
    if not summary:summary='；'.join(str(f.get('description') or f['title']) for f in out['findings'][:2])
    out['businessSummary']=summary[:480]
    visible={str(f['id']):f for f in out['findings'][:4]}
    dimensions=[]
    for dimension in out.get('analysisDimensions') or []:
        if not isinstance(dimension,dict) or not dimension.get('title') or not dimension.get('description') or dimension.get('stage') not in STAGE_LABELS:continue
        ids=[fid for fid in dimension.get('findingIds') or [] if fid in visible]
        if not ids:continue
        dimensions.append({**dimension,'findingIds':ids})
    # Old publications have no dimensions. Use their actual delivered findings,
    # never rebrand unsupported hypotheses as factual analysis.
    covered={fid for dimension in dimensions for fid in dimension['findingIds']}
    missing=[finding for fid,finding in visible.items() if fid not in covered]
    if missing:
        offset=len(dimensions)
        fallback=legacy_dimensions(missing)
        for index,dimension in enumerate(fallback):
            dimension['id']=f'dimension-{offset+index+1}'
        dimensions=(dimensions[:max(0,4-len(fallback))] if len(fallback)<4 else [])+fallback
    out['analysisDimensions']=dimensions[:4]
    business_actions=[]
    for action in out.get('recommendations') or []:
        title=str(action.get('action') or '')
        if re.search(r'(补齐|补录|补充|核对|核查|确认|修正).*(字段|指标|取数|统计口径)',title) or any(w in title for w in ('补齐指标','补齐字段','补录字段','修正取数','核对口径','核查口径','补数','确认口径','指标定义','统计口径')):
            limits.append('数据核查：'+title)
        else:business_actions.append(action)
    out['recommendations']=business_actions
    out['limitations']=list(dict.fromkeys(x for x in limits if x))
    return out


def validate_dimensions(value,available):
    findings={f['id']:f for f in value.get('findings') or []}
    dimensions=value.get('analysisDimensions') or []
    if len({d['id'] for d in dimensions})!=len(dimensions):raise ValueError('analysisDimensions的id重复')
    covered=set()
    for d in dimensions:
        if data_limitation(d['title']) or data_limitation(d['description']):raise ValueError('analysisDimensions不能用空值、缺数或无法评估代替经营分析；移入limitations')
        if any(w in d['description'] for w in ('导致','因为','造成','致使','根因','待验证假设')):raise ValueError('analysisDimensions只描述已观察的分布、趋势、差异和流程表现，不把未证实机制当成原因')
        if not set(d['evidenceIds'])<=available:raise ValueError('analysisDimensions引用不存在的证据')
        if not set(d['findingIds'])<=set(findings):raise ValueError('analysisDimensions引用未知风险findingIds')
        for fid in d['findingIds']:
            if not set(d['evidenceIds'])&set(findings[fid]['evidenceIds']):raise ValueError('分析维度缺少对应风险的证据引用')
        covered.update(d['findingIds'])
    if findings and set(findings)-covered:raise ValueError('analysisDimensions未覆盖本卡风险：'+','.join(sorted(set(findings)-covered))+'；按相同证据展开趋势、客户、产品团队或流程分析，不补造根因')
    metric_groups={tuple(sorted(f['metricCodes'])) for f in findings.values()}
    evidence_groups={tuple(sorted(f['evidenceIds'])) for f in findings.values()}
    if len(findings)>=3 and len(metric_groups)>=2 and len(evidence_groups)>=2 and len(dimensions)<2:
        raise ValueError('多组独立风险不能只写一个笼统分析维度；至少分别展开两个有证据的业务维度，同一问题不得机械拆分')
