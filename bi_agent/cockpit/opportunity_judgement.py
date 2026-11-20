"""Rule-first judgement of the 商机获取 risk card.

The ontology chain is applied in three layers, each one rule first:

1. Risks.  Every ontology risk is settled by its program rule (BR-A01~A10).
   Established risks are all shown; there is no output limit.  A risk the
   rule cannot settle (missing inputs) is sent to the model on its own, with
   its judgement rule and data.
2. Causes.  Every cause linked to an established risk is settled by its
   rule (BR-C01~C09) the same way; undecidable causes go to the model one
   at a time.
   An established risk that ends with no established cause gets one more
   model call: the model infers likely causes from this round's data and
   the misses of the ontology causes.  Inferred causes are added to the
   cause list as model hypotheses (never as verified ontology causes).
   When the ontology decides every cause by AI (overrides.causeAnalysis
   mode "ai", BR-L01), none of that runs: one model pass over all
   established risks and their metric results gives each risk its own
   1–2 causes, without matching the ontology cause sheet.
3. Advice.  An ontology advice applies when its cause is established.  This
   is fully decided by the ontology link, so advice never needs the model;
   inferred causes have no ontology advice.

A model call that fails is reported on that item, which is then skipped;
the other items carry on.  Model answers are taken as given: there is no
second validation pass.  Every item, established or not, is listed in the
card's ontology judgement so the page shows what matched and what did not.
"""
from __future__ import annotations

import json
from pathlib import Path
import os
import re
import time

KIND_LABELS = dict(risk="风险", issue="问题", cause="根因", advice="建议", inference="根因推理")
INFERRED_RULE = dict(code="", name="模型推理", levelRule="",
                     condition="关联的本体根因均未命中，由模型依据本轮取数推理")
_LEVEL_RANK = {"极高": 0, "高": 1, "中": 2, "低": 3}

# The system role every model call of the 销售额口径明细（商机获取） card
# starts with.  COCKPIT_OPPORTUNITY_ROLE_PROMPT replaces it when set.
ROLE_PROMPT = (
    "你是储能业务销售运营分析师，请用客观、简洁的经营汇报用语：风险说明影响对象、"
    "实际值与目标或阈值的差距，根因仅在证据充分时表述为已确认、证据不足时标注「待核实」，"
    "建议写清责任角色、具体措施和复检指标。"
)


def role_prompt():
    """The card's system role; an environment override wins when non-empty."""
    override = os.environ.get("COCKPIT_OPPORTUNITY_ROLE_PROMPT", "").strip()
    return override or ROLE_PROMPT


def compose_system_prompt(role, task):
    """Role first, then the call's own task instructions."""
    return f"{role}\n\n本次任务：{task}"


def system_prompt(task):
    return compose_system_prompt(role_prompt(), task)


ONTOLOGY_RULES = (
    "ontology 给出本条在本体中的定义、判定规则原文，以及所涉指标的本体口径（metrics：指标编码、名称、口径定义、业务规则、单位与本轮取值 values）；判断和表述必须沿用这些本体口径与名称。引用数值时写明指标名称，并按 values 中给出的单位原样引用，不得换算或改写单位；不得使用输入以外的数字。"
)

JUDGE_PROMPT = (
    "本体规则判定。程序已按规则计算，但下面这一条{kind}无法只凭结构化数据判定是否成立。"
    "请严格依据 rule 中的判定规则，结合 ontology 与 data 中本轮的取数结果作出判断，不得编造输入以外的数据。"
    + ONTOLOGY_RULES.replace("{", "{{").replace("}", "}}") +
    "判定所需的数据缺失（data.missingInputs 非空）且 ontology.metrics 中没有可替代的数据时，"
    "established 必须返回 null，不得返回 false；并在 reason 中写明缺少什么。"
    '只返回 JSON：{{"established": true 或 false 或 null, "level": "极高/高/中/低 或空字符串", '
    '"reason": "不超过160字的判断依据，引用 data 中的具体数值"}}，不要输出其他内容。'
)


INFER_PROMPT = (
    "商机获取环节根因推理。下面这条风险已经成立，但本体中与它关联的根因规则都没有命中。"
    "请只依据 risk（风险的本体定义、判定规则与判定数据）、ontologyCauses（各本体候选根因的定义、"
    "判定规则、判定结果和原因）和 data.metrics（只含本风险及其候选根因涉及的指标，附本体口径与本轮取值）"
    "推理最可能导致该风险的根因。" + ONTOLOGY_RULES +
    "不要重复已判定未命中的本体根因，也不要把它换一种说法重新提出，除非 data 中有相反证据。"
    "最多给出 3 条，按可能性从高到低排列；"
    "数据不足以推理时 causes 返回空数组，并在 note 中写明缺少什么。"
    "推理出的根因都未经规则确认，description 以「待核实」开头。"
    '只返回 JSON：{"causes": [{"title": "不超过20字的根因名称", '
    '"description": "不超过160字的推理依据，引用 data 中的具体数值", '
    '"dataGaps": "需要补充核实的数据，没有则为空字符串"}], "note": ""}，不要输出其他内容。'
)


# 2026-11-19: the global cause analysis is driven by 根因规则.md (its 系统提示词
# and 规则 sections, sent as written) and every metric result of the round; the
# ontology's 业务规则 page is not read.  The program only adds the output
# contract below and checks the answer before publishing.
CAUSE_RULES_PATH = Path(__file__).parent / "assets/opportunity-v3/根因规则.md"
CAUSES_PER_RISK = (0, 2)
_CAUSE_RULES_CACHE = {}

CAUSE_CONTRACT = (
    "输入：risks 是本卡片本轮已经成立的全部风险（code、name、level、judgement 为风险描述、relatedMetrics 为该风险"
    "的本体关联指标编码）；metrics 是本轮取到的全部指标结果（编码、名称、口径与本轮取值 values），otherFacts 是"
    "卡片补充取数的结果。请按上面的风险分析思维链与规则，依据这些指标结果为每条风险判断根因，根因挂载到对应风险"
    "的 code 下：思维链中“商机储备不足（总盘子）”对应风险“商机预测覆盖不足”，“客户预测覆盖不足”对应风险"
    "“客户预测不足”，“商机推进超期，影响签单”对应同名风险。"
    "每条风险给出 {low}～{high} 条根因，没有数据支撑时不给；每条根因的 description 是一段话。"
    "样例信息只示意写法，其中的数字不得引用；根因中的数字必须来自输入的指标结果；与所属风险描述相同的指标，"
    "数值必须与风险描述一致；不要复述风险描述的原句。"
    '只返回 JSON：{{"risks": [{{"code": "风险编码", "causes": [{{"title": "不超过20字的根因名称", '
    '"description": "一段话，不超过240字，引用输入中的具体数值", '
    '"dataGaps": "需要补充核实的数据，没有则为空字符串"}}]}}], "note": ""}}，不要输出其他内容。'
)


def cause_rules():
    """(系统提示词, 规则) from 根因规则.md, re-read when the file changes."""
    try:
        stamp = CAUSE_RULES_PATH.stat().st_mtime_ns
    except OSError:
        return "", ""
    cached = _CAUSE_RULES_CACHE.get("rules")
    if cached and cached[0] == stamp:
        return cached[1]
    sections, current = {}, None
    for line in CAUSE_RULES_PATH.read_text(encoding="utf-8").splitlines():
        heading = re.match(r"^##\s+(.+?)\s*$", line)
        if heading:
            current = heading.group(1)
            sections[current] = []
        elif current:
            sections[current].append(line)
    value = ("\n".join(sections.get("系统提示词") or []).strip(), "\n".join(sections.get("规则") or []).strip())
    _CAUSE_RULES_CACHE["rules"] = (stamp, value)
    return value


def global_cause_prompt(low, high):
    system, rules = cause_rules()
    return f"{system}\n\n规则：\n{rules}\n\n" + CAUSE_CONTRACT.format(low=low, high=high)


GLOBAL_CAUSE_RULE = dict(code="BR-L01", name="AI 全局根因分析", levelRule="",
                         condition="大模型依据本轮全部指标结果，按根因规则.md 的系统提示词与规则判断，每条风险 0～2 条根因")


SEMANTIC_PROMPT = (
    "风险行语义控制。输入 items 是本卡片已经判定成立的全部风险行（code、title、level、decidedBy、"
    "description），ontology 给出每个风险在本体中的定义与判定规则。请逐行改写 description："
    "统一使用本体中的术语与指标名称，说明影响对象以及实际值与目标或阈值的差距，语言客观、简洁，"
    "同一卡片内各行措辞风格一致、互不重复。只能改写表述，不得新增、删除或改动任何事实与数字："
    "原 description 中的每个数字及其单位都必须原样保留，不得引入原行没有的数字，不得改变风险结论与等级。"
    "每行不超过160字。"
    '只返回 JSON：{"items": [{"code": "风险编码", "description": "改写后的描述"}]}，不要输出其他内容。'
)


def _text(value):
    return "" if value is None else str(value).strip()


def _numbers(text):
    """Every number written in a sentence, as values (12.30 and 12.3 are the same)."""
    values = []
    for token in re.findall(r"-?\d+(?:,\d{3})*(?:\.\d+)?", _text(text)):
        try:
            values.append(round(float(token.replace(",", "")), 6))
        except ValueError:
            continue
    return sorted(values)


def _output_tokens(messages, prompt, fallback):
    """Output token budget of one judgement call.

    With ``COCKPIT_MODEL_CONTEXT_TOKENS`` set (.env), the call may use what the
    input leaves of that input + output budget, so a model that reasons before
    answering is not cut off; ``fallback`` applies only when it is unset.
    """
    from ..llm.context_budget import cockpit_context_limit, estimate_request

    limit = cockpit_context_limit()
    if not limit:
        return fallback
    return max(256, limit - estimate_request(messages, prompt))


def semantic_rewriter(payload):
    """One model call that rewrites the card's established risk rows."""
    from ..llm import provider
    from . import opportunity_v2 as v2

    key = v2._model_candidate_keys()[0]
    messages = [dict(role="user", content=json.dumps(payload, ensure_ascii=False, default=str))]
    try:
        timeout = int(os.environ.get("COCKPIT_OPPORTUNITY_JUDGE_TIMEOUT_SECONDS", "90"))
    except ValueError:
        timeout = 90
    timeout = max(15, min(timeout, 180))
    started = time.monotonic()
    prompt = system_prompt(SEMANTIC_PROMPT)
    max_tokens = _output_tokens(messages, prompt, 2000)
    try:
        text, _, _ = v2._read_model_stream(provider, messages, prompt, key,
                                           max_tokens=max_tokens, timeout=timeout, step="风险行语义控制")
        answer = v2._decode_model_json(text)
    except Exception as exc:  # noqa: BLE001 - annotated, the caller keeps the rule rows
        v2._annotate_model_error(exc, key, messages, started, timeout, max_tokens)
        raise
    return dict(answer, _model=v2._model_route_name(key))


def control_risk_rows(findings, config, rewrite, progress=None):
    """Let the model word every established risk row consistently, numbers untouched.

    A rewritten row is kept only when it carries exactly the numbers of the
    rule-written row; otherwise, or when the call fails, the row stays as the
    rule wrote it.  Returns a report for the card's diagnostics.
    """
    total = len(findings or [])
    findings = [finding for finding in findings or [] if not finding.get("metricDetails")]
    if rewrite is None or not findings:
        return dict(status="skipped", rewritten=0, kept=total, issues=[])
    if progress is not None:
        progress("judging", message=f"模型对 {len(findings)} 条风险行做语义控制")
    specs = config.get("risks") or {}
    rules = config.get("rules") or {}
    payload = dict(items=[dict(code=f["riskCode"], title=f["title"], level=f.get("riskLevel") or "",
                               decidedBy=f.get("decidedBy") or "", description=f.get("description") or "")
                          for f in findings],
                   ontology=[dict(code=f["riskCode"],
                                  definition=_text((specs.get(f["riskCode"]) or {}).get("description")),
                                  rule=_text((rules.get(_text((specs.get(f["riskCode"]) or {}).get("rule"))) or {})
                                             .get("description")))
                             for f in findings])
    try:
        answer = rewrite(payload)
    except Exception as exc:  # noqa: BLE001 - the card keeps its rule-written rows
        for finding in findings:
            finding["semanticControl"] = "kept"
        return dict(status="failed", rewritten=0, kept=total, issues=[_model_error(exc)])
    rows = {(_text(item.get("code"))): _text(item.get("description"))
            for item in (answer.get("items") if isinstance(answer, dict) else None) or []
            if isinstance(item, dict)}
    issues, rewritten = [], 0
    for finding in findings:
        original = finding.get("description") or ""
        candidate = rows.get(finding["riskCode"], "")
        problem = ("未返回该行" if not candidate else
                   "超过 160 字" if len(candidate) > 160 else
                   "数字与原句不一致" if _numbers(candidate) != _numbers(original) else "")
        if problem:
            finding["semanticControl"] = "kept"
            issues.append(f"{finding['riskCode']}：{problem}，保留规则原句")
            continue
        finding["ruleDescription"] = original
        finding["description"] = candidate
        finding["semanticControl"] = "model"
        rewritten += 1
    return dict(status="completed" if not issues else "partial", rewritten=rewritten,
                kept=total - rewritten, issues=issues,
                model=_text(answer.get("_model")) if isinstance(answer, dict) else "")


def _metric_code_of(fact_id, codes):
    """The ontology metric a fact belongs to: "…metric:R01-AMOUNT" → "R01"."""
    suffix = str(fact_id or "").split("metric:", 1)[-1]
    best = ""
    for code in codes:
        if (suffix == code or suffix.startswith(code + "-") or suffix.startswith(code + ":")) and len(code) > len(best):
            best = code
    return best


def _metric_context(config, codes, facts):
    """Ontology definition plus this round's labelled values for each metric code.

    Values come from the card's evidence facts, which carry the Chinese label,
    the unit and the caliber note, so the model reads the same metric the page
    shows instead of a bare code and number.
    """
    specs = config.get("metrics") or {}
    wanted = [code for code in dict.fromkeys(codes) if code in specs]
    values = {code: [] for code in wanted}
    all_codes = list(specs)
    for fact in facts or []:
        code = _metric_code_of(fact.get("id"), all_codes)
        if code in values:
            values[code].append({key: fact.get(key) for key in ("label", "value", "unit", "definition")
                                 if fact.get(key) not in (None, "")})
    context = []
    for code in wanted:
        spec = specs[code] or {}
        if not values[code]:
            # Named so the model knows it exists, but without a value to quote.
            context.append(dict(code=code, name=_text(spec.get("name")), note="本轮未取数，不能引用"))
            continue
        item = dict(code=code, name=_text(spec.get("name")), definition=_text(spec.get("definition"))[:400],
                    rule=_text(spec.get("formula") or spec.get("rule"))[:300], unit=_text(spec.get("unit")),
                    values=values[code])
        context.append({key: value for key, value in item.items() if value not in ("", None)})
    return context


def _established(value):
    """Read the model's verdict leniently; anything unclear is "undecided"."""
    if isinstance(value, bool):
        return value
    text = _text(value).lower()
    if text in {"true", "yes", "1", "成立", "是", "命中"}:
        return True
    if text in {"false", "no", "0", "不成立", "否", "未命中"}:
        return False
    return None


def make_item_judge(role=None, infer_prompt=None):
    """A per-item model judge with the card's own system role.

    ``role`` returns the role text at call time (so an environment override
    applies immediately); ``infer_prompt`` is the cause-inference task.
    """
    def judge(request):
        return _item_judge(request, role or role_prompt, infer_prompt or INFER_PROMPT)
    return judge


def default_item_judge(request):
    """Ask the configured model about one item; raises on any call failure."""
    return _item_judge(request, role_prompt, INFER_PROMPT)


def _item_judge(request, role, infer_prompt):
    from ..llm import provider
    from . import opportunity_v2 as v2

    key = v2._model_candidate_keys()[0]
    messages = [dict(role="user", content=json.dumps(request, ensure_ascii=False, default=str))]
    try:
        timeout = int(os.environ.get("COCKPIT_OPPORTUNITY_JUDGE_TIMEOUT_SECONDS", "90"))
    except ValueError:
        timeout = 90
    timeout = max(15, min(timeout, 180))
    started = time.monotonic()
    label = KIND_LABELS.get(request.get("kind"), "条目")
    inference = request.get("kind") == "inference"
    if request.get("kind") == "global_causes":
        limits = request.get("causesPerRisk") or {}
        task = global_cause_prompt(limits.get("min", 0), limits.get("max", 2))
        prompt = compose_system_prompt(role(), task)
        max_tokens = min(4000, 600 + 450 * len(request.get("risks") or []))
        step = "AI 全局根因分析"
    else:
        prompt = compose_system_prompt(role(), infer_prompt if inference else JUDGE_PROMPT.format(kind=label))
        max_tokens = 1200 if inference else 800
        step = f"{label} {request.get('code')}" if inference else f"判定{label} {request.get('code')}"
    max_tokens = _output_tokens(messages, prompt, max_tokens)
    try:
        text, _, usage = v2._read_model_stream(
            provider, messages, prompt, key,
            max_tokens=max_tokens, timeout=timeout, step=step)
        answer = v2._decode_model_json(text)
    except Exception as exc:  # noqa: BLE001 - annotated for the item's error
        v2._annotate_model_error(exc, key, messages, started, timeout, max_tokens)
        raise
    return dict(answer, _model=v2._model_route_name(key), _usage=usage,
                _elapsed=round(time.monotonic() - started, 1))


def _model_error(exc):
    from .diagnostics import redact
    from .opportunity_v2 import _model_error_context, classify_model_failure

    status = dict(status="failed", error=type(exc).__name__, modelErrorMessage=str(exc)[:800],
                  **_model_error_context(exc))
    category = classify_model_failure(status)[0]
    detail = re.sub(r"\s+", " ", redact(str(exc))).strip()[:240] if str(exc) else ""
    return f"{category}" + (f"：{detail}" if detail else "")


def _ask(judge, request, progress, position):
    """One model call for one item; never raises."""
    label = KIND_LABELS.get(request["kind"], "条目")
    if progress is not None:
        progress("judging", message=f"模型判定{label} {request['code']}（{position}）")
    if judge is None:
        return dict(decidedBy="none", established=None, error="未启用模型判断，已跳过")
    try:
        answer = judge(request)
    except Exception as exc:  # noqa: BLE001 - this item is skipped, the card goes on
        return dict(decidedBy="none", established=None, error=_model_error(exc) + "，已跳过")
    if not isinstance(answer, dict):
        return dict(decidedBy="none", established=None, error="模型返回的不是 JSON 对象，已跳过")
    established = _established(answer.get("established"))
    reason = _text(answer.get("reason"))[:400]
    missing = [item for item in ((request.get("data") or {}).get("missingInputs") or []) if _text(item)]
    if established is False and missing:
        # Missing inputs leave the item undecided: "not established" would
        # claim a fact the data cannot show.
        established = None
        reason = (f"判定所需数据缺失（{'、'.join(map(str, missing))}），按无法判定处理"
                  + (f"；模型说明：{reason}" if reason else "。"))[:400]
    return dict(decidedBy="model", established=established,
                level=_text(answer.get("level"))[:4] if _text(answer.get("level")) in _LEVEL_RANK else "",
                reason=reason, model=_text(answer.get("_model")),
                elapsedSeconds=answer.get("_elapsed"))


def _infer(judge, request, progress, position):
    """One model call inferring causes for one risk; never raises."""
    if progress is not None:
        progress("judging", message=f"模型推理{request.get('subjectLabel') or '风险'} {request['code']} 的根因（{position}）")
    if judge is None:
        return dict(error="未启用模型判断，已跳过")
    try:
        answer = judge(request)
    except Exception as exc:  # noqa: BLE001 - this risk is skipped, the card goes on
        return dict(error=_model_error(exc) + "，已跳过")
    if not isinstance(answer, dict) or not isinstance(answer.get("causes", []), list):
        return dict(error="模型返回的不是约定的 JSON 对象，已跳过")
    causes = []
    for item in answer.get("causes") or []:
        if not isinstance(item, dict) or not _text(item.get("title")):
            continue
        causes.append(dict(title=_text(item.get("title"))[:40],
                           description=_text(item.get("description"))[:400],
                           dataGaps=_text(item.get("dataGaps"))[:200]))
    return dict(causes=causes[:3], note=_text(answer.get("note"))[:300],
                model=_text(answer.get("_model")), elapsedSeconds=answer.get("_elapsed"))


# Month spans, ordinals, years, quarters and ontology codes are labels, not
# business figures (BR-D02 checks every other number, small ones included).
_NUMBER_LABELS = re.compile(
    r"\d{1,2}\s*[—–\-~～至到]\s*\d{1,2}\s*月|\d{1,2}\s*月份?|第\s*\d+|\d{4}\s*年|\d\s*季度"
    r"|[A-Za-z]+\d+(?:-\d+)?")


def _untraceable_numbers(text, allowed):
    """Numbers in ``text`` that the risk's own input does not carry (BR-D02)."""
    from .opportunity_v2 import _model_numbers

    bad = []
    for token in _model_numbers(_NUMBER_LABELS.sub(" ", text)):
        try:
            value = float(token)
        except ValueError:
            continue
        if token not in allowed and f"{value:g}" not in allowed:
            bad.append(token)
    return sorted(bad)


# 根因规则.md 规则 1～7, applied to the published cause text.
_RULE_WORDING = (
    (r"严重超期[（(]超基线[^）)]*[）)]", "严重超期"),
    (r"(?<!严重)超期[（(]超基线[^）)]*[）)]", "超期"),
    (r"P0\s*阶段", "商机获取阶段"), (r"P1\s*阶段", "技术交流阶段"), (r"P2\s*阶段", "方案推动阶段"),
    (r"正缺口", "缺口"),
    (r"已记录|涉及(?=预测|金额|电量)", ""),
    (r"进度\s*[＋+]\s*预测", "已签单＋剩余预测"),
    (r"进度[（(]\s*([0-9—–\-]+月)\s*已签单\s*[）)]", r"\1已签单"),
    (r"(?<!剩余)预测[（(]\s*([0-9—–\-]+月)\s*[）)]", r"\1剩余预测"),
)


def _tidy(value):
    for pattern, replacement in _RULE_WORDING:
        value = re.sub(pattern, replacement, value)
    return re.sub(r"([，。；])\1+", r"\1", value).strip("，； ")


def _repeats_risk(cause, risk):
    """Why a cause restates its own risk instead of explaining it, or ""."""
    text = f"{cause['title']} {cause['description']}"
    name = _text(risk.get("name"))
    if name and (name in cause["title"] or cause["title"] in name):
        return f"根因名称与风险名称「{name}」重复"
    judgement = _text(risk.get("judgement"))
    for clause in re.split(r"[，。；：、（）()]+", judgement):
        clause = clause.strip()
        if len(clause) >= 8 and clause in text:
            return f"复述了风险已有内容「{clause}」"
    # Quoting several of the risk's own figures is restating it, not explaining it.
    figures = {token for token in _numbers(judgement) if abs(token) > 12}
    shared = figures & set(_numbers(text))
    if len(shared) >= 3:
        return "重复引用了风险已写出的数字 " + "、".join(f"{value:g}" for value in sorted(shared))
    return ""


_FIGURE = re.compile(r"(?:^|[，。；：、\s（(])([\u4e00-\u9fa5]{2,6})\s*(-?\d+(?:\.\d+)?)")


def _conflicts_risk(cause, risk):
    """A figure the cause gives for one of the risk's own labelled figures, but different, or \"\"."""
    own = {}
    for label, number in _FIGURE.findall(_text(risk.get("judgement"))):
        own.setdefault(label, set()).add(float(number))
    for label, number in _FIGURE.findall(f"{cause['title']} {cause['description']}"):
        values = own.get(label)
        if values and not any(abs(float(number) - value) < 0.005 for value in values):
            shown = "、".join(f"{value:g}" for value in sorted(values))
            return f"「{label} {number}」与风险中的「{label} {shown}」不一致"
    return ""


def _global_causes(judge, request, progress, *, low, high):
    """One model pass over every established risk; never raises.

    Returns {risk code: [cause, …]} plus a note, a model name, the number of
    calls and, when nothing usable came back, an error.  Before anything is
    published each cause is checked: its numbers must come from the input,
    it must not contradict or restate its risk, nor repeat another risk's
    cause.  Failures are sent back once; what still fails is dropped, and a
    risk may end with no cause (“暂无可验证根因”).
    """
    from .opportunity_v2 import _allowed_model_numbers

    codes = [risk["code"] for risk in request["risks"]]
    risks_by_code = {risk["code"]: risk for risk in request["risks"]}
    if progress is not None:
        progress("judging", message=f"模型全局分析 {len(codes)} 条风险的根因")
    if judge is None:
        return dict(causes={}, calls=0, error="未启用模型判断，已跳过")
    if not all(cause_rules()):
        return dict(causes={}, calls=0, error="根因规则.md 缺失或缺少“系统提示词”“规则”章节，已跳过")
    allowed = _allowed_model_numbers(request)
    feedback = None
    best, calls, note, model, error = {}, 0, "", "", ""
    for _ in range(2):
        ask = dict(request, validationFeedback=feedback) if feedback else request
        calls += 1
        try:
            answer = judge(ask)
        except Exception as exc:  # noqa: BLE001 - the causes are skipped, the card goes on
            error = _model_error(exc) + "，已跳过"
            break
        if not isinstance(answer, dict) or not isinstance(answer.get("risks"), list):
            error = "模型返回的不是约定的 JSON 对象，已跳过"
            feedback = ["只返回约定的 JSON：risks 为数组，每项含 code 与 causes"]
            continue
        error = ""
        model = _text(answer.get("_model")) or model
        note = _text(answer.get("note"))[:300] or note
        problems = []
        found = {}
        answered = {_text(item.get("code")): item for item in answer["risks"]
                    if isinstance(item, dict) and _text(item.get("code")) in codes}
        seen_titles, seen_numbers = {}, []
        for code in codes:  # risk order: an earlier risk keeps a shared cause
            kept = []
            for cause in (answered.get(code) or {}).get("causes") or []:
                if not isinstance(cause, dict) or not _text(cause.get("title")):
                    continue
                cause = dict(title=_tidy(_text(cause.get("title")))[:40],
                             description=_tidy(_text(cause.get("description")))[:500],
                             dataGaps=_text(cause.get("dataGaps"))[:200])
                label = f"{code}「{cause['title']}」"
                bad = _untraceable_numbers(f"{cause['title']} {cause['description']}", allowed)
                if bad:
                    problems.append(f"{label}引用了输入中没有的数字 {'、'.join(bad)}")
                    continue
                conflict = _conflicts_risk(cause, risks_by_code[code])
                if conflict:
                    problems.append(f"{label}{conflict}，根因数据不得与风险冲突")
                    continue
                repeated = _repeats_risk(cause, risks_by_code[code])
                if repeated:
                    problems.append(f"{label}{repeated}，根因不得重复风险已有内容")
                    continue
                numbers = {value for value in _numbers(cause["description"]) if abs(value) > 1}
                duplicate = seen_titles.get(cause["title"]) or next(
                    (other for other, values in seen_numbers if len(numbers & values) >= 3), "")
                if duplicate and duplicate != code:
                    problems.append(f"{label}与{duplicate}下的根因重复，跨风险只保留一处")
                    continue
                kept.append(cause)
                seen_titles.setdefault(cause["title"], code)
                seen_numbers.append((code, numbers))
            if kept:
                found[code] = kept[:high]
        for code, causes in found.items():
            if len(causes) >= len(best.get(code) or []):
                best[code] = causes
        missing = [code for code in codes if len(best.get(code) or []) < low]
        if missing:
            problems.append("以下风险没有给出合格的根因：" + "、".join(missing))
        if not problems:
            break
        feedback = problems
    if not best and not error and low:
        error = "模型没有给出可用的根因"
    return dict(causes=best, calls=calls, note=note, model=model, error=error)


def _status_label(entry):
    if entry.get("error"):
        return "判断失败，已跳过"
    if entry.get("aiAnalysis"):
        return "AI 全局分析" if entry.get("established") is True else "AI 未给出根因"
    if entry.get("inferred"):
        if entry.get("dataGap"):
            return "待补数据，未推理"
        return "模型推理（本体根因未命中）" if entry.get("established") is True else "模型未能推理"
    if entry.get("decidedBy") == "unevaluated":
        return entry.get("reason") or "未评估"
    who = "规则" if entry.get("decidedBy") == "rule" else "模型"
    if entry.get("established") is True:
        return f"命中（{who}判定）"
    if entry.get("established") is False:
        return ("不适用（规则判定）" if entry.get("ruleStatus") == "not_applicable"
                else f"未命中（{who}判定）")
    return "无法判定（模型）"


def judge_card(evaluated, config, *, judge=None, progress=None, primary="risk", id_prefix="opp-v2",
               cause_stage=None, advice_type=None, include_downstream=True):
    """Settle risks (or problems), causes and advice; return the card fields and the trace.

    ``primary`` names the first layer ("risk" for the stage cards, "issue" for
    the problem-driven 销售额／出货量 card); it only changes the wording,
    request kind and ids.  ``cause_stage`` maps a cause code to its business
    stage and ``advice_type`` decides an advice's action type; both default
    to the 商机获取 card's behaviour.  ``include_downstream=False`` stops after
    the risk/problem layer, so a problem-only delivery neither calls the model
    for causes nor publishes causes and advice.
    """
    from .opportunity_v2 import _CAUSE_STAGE, _advice_action_type, _deadline_meta

    label = KIND_LABELS.get(primary, "风险")
    stage_of = cause_stage or (lambda code: _CAUSE_STAGE.get(code, "opportunity"))
    action_type = advice_type or _advice_action_type

    rules = {item.get("code"): item for item in (config.get("rules") or {}).values()} \
        if isinstance(config.get("rules"), dict) else {
            item.get("code"): item for item in config.get("rules") or []}
    risk_specs = config.get("risks") or {}
    cause_specs = config.get("causes") or {}
    advice_specs = config.get("advice") or {}
    links = config.get("links") or {}
    triggered = {risk["code"]: risk for risk in evaluated.get("risks") or []}
    candidates = {item["code"]: item for item in evaluated.get("riskCandidates") or []}
    cause_outcomes = evaluated.get("causeOutcomes") or {}
    period = _text((evaluated.get("result") or {}).get("measurementDate"))

    def rule_of(code, spec):
        rule_code = _text(spec.get("rule"))
        return dict(code=rule_code, name=_text((rules.get(rule_code) or {}).get("name")),
                    condition=_text(spec.get("condition")),
                    levelRule=_text(spec.get("levelRule")))

    facts = (evaluated.get("evidence") or {}).get("facts") or []

    def rule_text(code):
        rule = rules.get(_text(code)) or {}
        return {key: _text(rule.get(key)) for key in ("code", "name", "description", "result")
                if _text(rule.get(key))}

    def element(spec, entry):
        """The ontology element itself: definition, rule text and impact."""
        value = dict(code=entry["code"], name=entry["name"],
                     description=_text(spec.get("description")),
                     condition=_text(spec.get("condition")), levelRule=_text(spec.get("levelRule")),
                     objects=_text(spec.get("impact") or spec.get("objects")),
                     method=_text(spec.get("method")), analysisFocus=_text(spec.get("aiFocus")),
                     ontologyRule=rule_text(spec.get("rule")))
        return {key: item for key, item in value.items() if item}

    def indicator_codes(*specs):
        codes = []
        for spec in specs:
            codes += _indicators(spec or {})
        return codes

    # ---- risks ---------------------------------------------------------
    risk_entries = []
    pending = [code for code in risk_specs
               if not (candidates.get(code) or {}).get("requiresRuleEvidence")
               and (candidates.get(code) or {}).get("ruleStatus", "insufficient") == "insufficient"]
    for code, spec in risk_specs.items():
        candidate = candidates.get(code) or {}
        status = candidate.get("ruleStatus") or "insufficient"
        entry = dict(kind=primary, code=code, name=_text(spec.get("name")) or code,
                     indicators=_indicators(spec),
                     rule=rule_of(code, spec), ruleStatus=status,
                     observed=candidate.get("observed") or [],
                     missingEvidence=candidate.get("missingEvidence") or [],
                     evidenceIds=list(candidate.get("evidenceIds") or [])[:20])
        if status == "triggered":
            risk = triggered.get(code) or {}
            entry.update(decidedBy="rule", established=True, level=risk.get("level") or "",
                         reason=_text(risk.get("description")) or "规则条件成立")
        elif status in {"not_triggered", "not_applicable"}:
            entry.update(decidedBy="rule", established=False,
                         reason="规则条件不成立" if status == "not_triggered" else "本轮没有适用对象")
        elif candidate.get("requiresRuleEvidence"):
            entry.update(decidedBy="unevaluated", established=None,
                         reason=_text(candidate.get("unevaluatedReason")) or "阶段周期分档数据不足，无法判定")
        else:
            request = dict(kind=primary, code=code, name=entry["name"], period=period,
                           rule=entry["rule"], ontologyDescription=_text(spec.get("description")),
                           ontology=dict(element=element(spec, entry),
                                         metrics=_metric_context(config, indicator_codes(spec), facts)),
                           data=dict(observed=entry["observed"], missingInputs=entry["missingEvidence"],
                                     programNote="规则所需输入不完整，程序无法判定"))
            entry.update(_ask(judge, request, progress, f"{pending.index(code) + 1}/{len(pending)}"))
        risk_entries.append(entry)
    established_risks = {entry["code"]: entry for entry in risk_entries if entry.get("established") is True}

    # ---- causes --------------------------------------------------------
    # BR-L01 (2026-11-16): when every ontology cause is decided by AI, the
    # causes come from one global model analysis of the established risks
    # and their metric results; the ontology cause sheet is not matched.
    cause_analysis = (config.get("overrides") or {}).get("causeAnalysis") or {}
    ai_causes = include_downstream and _text(cause_analysis.get("mode")) == "ai"
    matched_specs = {} if ai_causes else cause_specs

    def linked_risks(cause_code):
        codes = []
        for risk_code in established_risks:
            if cause_code in ((links.get(risk_code) or {}).get("causes") or []):
                codes.append(risk_code)
        return codes

    cause_entries = []
    cause_pending = [code for code in matched_specs
                     if linked_risks(code) and (cause_outcomes.get(code) or {}).get("ruleStatus") == "insufficient"]
    for code, spec in matched_specs.items():
        outcome = cause_outcomes.get(code) or dict(ruleStatus="insufficient", reason="缺少该根因的规则实现")
        related = linked_risks(code)
        entry = dict(kind="cause", code=code, name=_text(spec.get("name")) or code,
                     rule=rule_of(code, spec), ruleStatus=outcome.get("ruleStatus"),
                     linkedRisks=related, observed=outcome.get("observed") or [],
                     missingEvidence=outcome.get("missingEvidence") or [],
                     evidenceIds=list(outcome.get("evidenceIds") or [])[:20])
        if not related:
            entry.update(decidedBy="unevaluated", established=None,
                         reason=f"未评估（关联{label}均未成立）")
        elif outcome.get("ruleStatus") == "triggered":
            entry.update(decidedBy="rule", established=True,
                         reason=_text(outcome.get("description")) or _text(outcome.get("reason")))
        elif outcome.get("ruleStatus") in {"not_triggered", "not_applicable"}:
            entry.update(decidedBy="rule", established=False, reason=_text(outcome.get("reason")))
        else:
            request = dict(
                kind="cause", code=code, name=entry["name"], period=period, rule=entry["rule"],
                analysisFocus=_text(spec.get("aiFocus")),
                ontology=dict(element=element(spec, entry), metrics=_metric_context(
                    config, indicator_codes(spec, *(risk_specs.get(r) for r in related)), facts)),
                linkedRisks=[dict(code=risk_code, name=established_risks[risk_code]["name"],
                                  ontologyDescription=_text((risk_specs.get(risk_code) or {}).get("description")),
                                  judgement=established_risks[risk_code].get("reason"))
                             for risk_code in related],
                data=dict(observed=entry["observed"], missingInputs=entry["missingEvidence"],
                          programNote=_text(outcome.get("reason"))))
            entry.update(_ask(judge, request, progress, f"{cause_pending.index(code) + 1}/{len(cause_pending)}"))
        cause_entries.append(entry)
    # ---- inferred causes for risks no ontology cause explains -----------
    explained = {risk_code for entry in cause_entries if entry.get("established") is True
                 for risk_code in entry["linkedRisks"]}
    risk_order = sorted(established_risks.values(),
                        key=lambda item: (_LEVEL_RANK.get(item.get("level") or "", 4), item["code"]))
    orphans = ([] if not include_downstream or ai_causes
               else [entry for entry in risk_order if entry["code"] not in explained])
    inference_calls = 0
    for position, risk in enumerate(orphans, 1):
        linked = (links.get(risk["code"]) or {}).get("causes") or []
        base = dict(kind="cause", rule=dict(INFERRED_RULE), ruleStatus="inferred", inferred=True,
                    linkedRisks=[risk["code"]], observed=[], evidenceIds=list(risk["evidenceIds"])[:3])
        # An ontology cause that could not be judged for lack of data is not
        # "unmatched": inferring a cause then just renames it with unrelated
        # numbers.  Report the missing data instead of calling the model.
        gaps = [entry for entry in cause_entries
                if entry["code"] in linked and entry.get("ruleStatus") == "insufficient"
                and entry.get("missingEvidence") and entry.get("established") is not True]
        if gaps:
            missing = list(dict.fromkeys(item for entry in gaps for item in entry["missingEvidence"]))
            cause_entries.append(dict(
                base, code=f"{risk['code']}-AI", name=f"{risk['name']}·根因推理", decidedBy="rule",
                established=None, dataGap=True, missingEvidence=missing,
                reason="本体根因 " + "、".join(f"{entry['code']} {entry['name']}" for entry in gaps)
                       + " 缺少判定数据（" + "、".join(missing) + "），未进行模型推理；补齐数据后由规则判定。"))
            continue
        cause_specs_linked = [cause_specs.get(code) for code in linked]
        request = dict(
            kind="inference", subjectLabel=label, code=risk["code"], name=risk["name"], period=period,
            risk=dict(code=risk["code"], name=risk["name"], level=risk.get("level") or "",
                      judgement=risk.get("reason") or "", rule=risk["rule"],
                      ontologyDescription=_text((risk_specs.get(risk["code"]) or {}).get("description")),
                      ontology=element(risk_specs.get(risk["code"]) or {}, risk),
                      observed=risk["observed"]),
            ontologyCauses=[dict(code=entry["code"], name=entry["name"], rule=entry["rule"],
                                 ontology=element(cause_specs.get(entry["code"]) or {}, entry),
                                 status=_status_label(entry),
                                 reason=entry.get("reason") or entry.get("error") or "",
                                 observed=entry["observed"], missingInputs=entry["missingEvidence"])
                            for entry in cause_entries if entry["code"] in linked],
            data=dict(metrics=_metric_context(
                config, indicator_codes(risk_specs.get(risk["code"]), *cause_specs_linked), facts)))
        answer = _infer(judge, request, progress, f"{position}/{len(orphans)}")
        if judge is not None:
            inference_calls += 1
        if answer.get("error"):
            cause_entries.append(dict(base, code=f"{risk['code']}-AI", name=f"{risk['name']}·根因推理",
                                      decidedBy="none", established=None, missingEvidence=[],
                                      error=answer["error"]))
        elif not answer["causes"]:
            cause_entries.append(dict(base, code=f"{risk['code']}-AI", name=f"{risk['name']}·根因推理",
                                      decidedBy="model", established=None, missingEvidence=[],
                                      reason=answer.get("note") or "模型认为本轮数据不足以推理根因",
                                      model=answer.get("model")))
        for index, item in enumerate(answer.get("causes") or [], 1):
            cause_entries.append(dict(base, code=f"{risk['code']}-AI{index}", name=item["title"],
                                      decidedBy="model", established=True,
                                      reason=item["description"] or item["title"],
                                      missingEvidence=[item["dataGaps"]] if item["dataGaps"] else [],
                                      model=answer.get("model")))
    if ai_causes and risk_order:
        # 根因规则.md (2026-11-19): every metric result of the round goes in;
        # the ontology's rule page and cause page do not.
        low, high = CAUSES_PER_RISK
        all_codes = list(config.get("metrics") or {})
        measured_codes = list(dict.fromkeys(
            code for code in (_metric_code_of(fact.get("id"), all_codes) for fact in facts) if code))
        other_facts = [{key: fact.get(key) for key in ("label", "value", "unit", "definition")
                        if fact.get(key) not in (None, "")}
                       for fact in facts
                       if not _metric_code_of(fact.get("id"), all_codes) and fact.get("value") is not None]
        request = dict(
            kind="global_causes", code="BR-L01", period=period,
            causesPerRisk=dict(min=low, max=high),
            risks=[dict(code=risk["code"], name=risk["name"], level=risk.get("level") or "",
                        judgement=risk.get("reason") or "",
                        relatedMetrics=indicator_codes(risk_specs.get(risk["code"])))
                   for risk in risk_order],
            metrics=_metric_context(config, measured_codes, facts),
            otherFacts=other_facts)
        answer = _global_causes(judge, request, progress, low=low, high=high)
        inference_calls += answer["calls"]
        base = dict(kind="cause", rule=dict(GLOBAL_CAUSE_RULE), ruleStatus="inferred", inferred=True,
                    aiAnalysis=True, observed=[])
        for risk in risk_order:
            found = answer["causes"].get(risk["code"]) or []
            if not found:
                cause_entries.append(dict(
                    base, code=f"{risk['code']}-AI", name=f"{risk['name']}·AI 根因分析",
                    linkedRisks=[risk["code"]], evidenceIds=list(risk["evidenceIds"])[:3],
                    decidedBy="model" if not answer.get("error") else "none", established=None,
                    missingEvidence=[], model=answer.get("model"),
                    **({"error": answer["error"]} if answer.get("error")
                       else {"reason": answer.get("note") or "模型没有给出该风险的根因"})))
                continue
            for index, item in enumerate(found, 1):
                cause_entries.append(dict(
                    base, code=f"{risk['code']}-AI{index}", name=item["title"],
                    linkedRisks=[risk["code"]], evidenceIds=list(risk["evidenceIds"])[:3],
                    decidedBy="model", established=True,
                    reason=item["description"] or item["title"],
                    missingEvidence=[item["dataGaps"]] if item["dataGaps"] else [],
                    model=answer.get("model")))
    established_causes = {entry["code"]: entry for entry in cause_entries if entry.get("established") is True}

    # ---- advice --------------------------------------------------------
    advice_entries = []
    for code, spec in advice_specs.items():
        causes = [cause for cause in spec.get("causes") or [] if cause in cause_specs]
        hit = [cause for cause in causes if cause in established_causes]
        skipped = [cause for cause in causes
                   if any(entry["code"] == cause and entry.get("error") for entry in cause_entries)]
        entry = dict(kind="advice", code=code, name=_text(spec.get("name") or spec.get("action")) or code,
                     rule=dict(code="", name="行动建议对应根因", condition="对应根因成立即采用",
                               levelRule=""),
                     linkedCauses=hit or causes, decidedBy="rule")
        if ai_causes:
            # AI causes carry no ontology cause code, so no ontology advice
            # can be linked to them.
            entry.update(decidedBy="unevaluated", established=None,
                         reason="根因由 AI 全局分析给出，未关联本体行动建议")
        elif hit:
            entry.update(established=True, reason="对应根因 " + "、".join(hit) + " 已成立")
        elif skipped:
            entry.update(established=None, error="对应根因判断失败，已跳过")
        else:
            entry.update(established=False, reason="对应根因未成立")
        advice_entries.append(entry)

    # ---- card fields ---------------------------------------------------
    order = sorted(established_risks.values(),
                   key=lambda item: (_LEVEL_RANK.get(item.get("level") or "", 4), item["code"]))
    findings = [dict(
        id=f"{id_prefix}:{primary}:{entry['code']}", kind="risk_fact", title=entry["name"],
        description=entry.get("reason") or "", riskCode=entry["code"],
        riskLevel=entry.get("level") or "", decidedBy=entry["decidedBy"],
        metricCodes=[entry["code"]] + [item.get("id", "").split(":")[-1]
                                       for item in entry["observed"] if item.get("id")][:11],
        evidenceIds=entry["evidenceIds"], riskDomain="sales", riskTotalCount=len(order),
    ) for entry in order]
    for finding in findings:
        code = finding["riskCode"]
        category = (risk_specs.get(code) or {}).get("category")
        if category:
            finding["riskCategory"] = category
        risk = triggered.get(code) or {}
        if risk.get("metricDetails"):
            finding.update(metricDetails=risk["metricDetails"], metricCodes=risk["metricCodes"])
    finding_id = {item["riskCode"]: item["id"] for item in findings}
    causes = []
    for entry in cause_entries:
        if entry.get("established") is not True:
            continue
        evidence = entry["evidenceIds"] or [e for risk_code in entry["linkedRisks"]
                                            for e in established_risks[risk_code]["evidenceIds"][:3]]
        causes.append(dict(
            id=f"{id_prefix}:cause:{entry['code']}", causeCode=entry["code"],
            stage=stage_of(entry["code"]), title=entry["name"],
            description=entry.get("reason") or "", decidedBy=entry["decidedBy"],
            kind="verified" if entry["decidedBy"] == "rule" else "hypothesis",
            status="supported" if entry["decidedBy"] == "rule" else "hypothesis",
            inferred=bool(entry.get("inferred")),
            findingIds=[finding_id[code] for code in entry["linkedRisks"] if code in finding_id],
            riskCodes=list(entry["linkedRisks"]), evidenceIds=evidence[:20],
            missingEvidence=list(entry["missingEvidence"]) if entry.get("inferred") else [],
            **({"analysis": "ai"} if entry.get("aiAnalysis") else {}),
        ))
    if include_downstream:
        # A risk without any established cause says why under it, instead of
        # the cause list silently disappearing.
        explained_ids = {fid for item in causes for fid in item["findingIds"]}
        for finding in findings:
            if finding["id"] in explained_ids:
                continue
            # 1117 1119 BR-L01: no qualified cause → “暂无可验证根因”; a model
            # failure keeps its reason in brackets.
            errors = [entry.get("error") for entry in cause_entries
                      if finding["riskCode"] in (entry.get("linkedRisks") or []) and entry.get("error")]
            finding["causeNote"] = ("暂无可验证根因" + (f"（{_text(errors[0])}）" if errors else ""))[:200]
    cause_by_code = {item["causeCode"]: item for item in causes}
    recommendations = []
    for entry in advice_entries:
        if entry.get("established") is not True:
            continue
        spec = advice_specs[entry["code"]]
        linked = [cause_by_code[code] for code in entry["linkedCauses"] if code in cause_by_code]
        days, deadline_type, deadline_text = _deadline_meta(spec.get("deadline"))
        recommendations.append(dict(
            id=f"{id_prefix}:advice:{entry['code']}", adviceCode=entry["code"],
            actionType=action_type(entry["code"], spec, linked),
            action=_text(spec.get("action") or spec.get("name"))[:120],
            detail=_text(spec.get("measure"))[:600], object=_text(spec.get("object"))[:200],
            ownerRole=_text(spec.get("owner")) or "待确认", deadline=deadline_text,
            deadlineType=deadline_type, deadlineDays=days,
            targetValue=_text(spec.get("target")), acceptance=_text(spec.get("acceptance")),
            tracking=_text(spec.get("tracking")), priority=_text(spec.get("priority")),
            causeIds=[cause["id"] for cause in linked],
            riskCodes=sorted({code for cause in linked for code in cause["riskCodes"]}),
            evidenceIds=list(dict.fromkeys(e for cause in linked for e in cause["evidenceIds"]))[:20],
            decidedBy="rule", ownerConfirmed=False, deadlineConfirmed=False,
        ))
    entries = risk_entries + cause_entries + advice_entries
    for entry in entries:
        entry["statusLabel"] = _status_label(entry)
    model_calls = [entry for entry in entries if not entry.get("inferred")
                   and (entry.get("decidedBy") == "model" or entry.get("error"))]
    inferred_count = sum(1 for item in causes if item["inferred"])
    failures = [entry for entry in entries if entry.get("error") and entry["kind"] != "advice"]
    by_rule = sum(1 for entry in order if entry["decidedBy"] == "rule")
    summary = (f"本轮 {len(risk_entries)} 项本体{label}中 {len(order)} 项成立"
               f"（规则判定 {by_rule} 项，模型判定 {len(order) - by_rule} 项）"
               + (f"，成立{label}涉及 {len(causes)} 项根因、{len(recommendations)} 条建议"
                  if order and include_downstream else "")
               + ("（根因由 AI 依据成立风险及其指标结果全局分析给出，待核实）"
                  if ai_causes and causes else
                  f"（其中 {inferred_count} 项根因由模型在本体根因未命中时推理）"
                  if include_downstream and inferred_count else "")
               + (f"；{len(failures)} 项模型判断失败已跳过" if failures else "") + "。")
    assessments = [dict(
        code=entry["code"], name=entry["name"], rule=entry["rule"]["code"],
        condition=entry["rule"]["condition"], ruleStatus=entry["ruleStatus"],
        include=entry.get("established") is True, assessmentSource=entry.get("decidedBy"),
        classification=("confirmed" if entry.get("established") is True else
                        "not_applicable" if entry["ruleStatus"] == "not_applicable" else "insufficient"),
        description=entry.get("reason") or entry.get("error") or "",
        metricCodes=entry["indicators"] or [entry["code"]], evidenceIds=entry["evidenceIds"],
        observed=entry["observed"], missingEvidence=entry["missingEvidence"],
    ) for entry in risk_entries]
    judgement = dict(
        risks=[_public(entry) for entry in risk_entries],
        causes=[_public(entry) for entry in cause_entries],
        advice=[_public(entry) for entry in advice_entries],
        modelCalls=len([entry for entry in model_calls if entry.get("decidedBy") != "unevaluated"]) + inference_calls,
        inferenceCalls=inference_calls,
        failures=[f"{KIND_LABELS[entry['kind']]} {entry['code']}：{entry['error']}" for entry in failures],
    )
    return dict(summary=summary, findings=findings, causes=causes, analysisDimensions=[
        dict(item, id=item["id"]) for item in causes], recommendations=recommendations,
        riskAssessments=assessments, ontologyJudgement=judgement,
        riskCodes=[item["riskCode"] for item in findings],
        riskLevels={item["riskCode"]: item["riskLevel"] for item in findings},
        riskTotalCount=len(findings), includedRiskCount=len(findings))


def link_queries(result, config):
    """Attach to each risk and cause the queries its own evidence was read from.

    An item's metrics are those of its evidence facts; a query supports it
    when the query feeds one of those metrics.  An item no query supports
    (e.g. a model-inferred cause) gets an empty list and shows no SQL.
    """
    catalog = result.get("queryCatalog") or []
    codes = list((config.get("metrics") or {}))

    def item_metrics(item):
        found = set()
        for value in list(item.get("evidenceIds") or []) + list(item.get("metricCodes") or []):
            code = _metric_code_of(value if "metric:" in str(value) else f"metric:{value}", codes)
            if code:
                found.add(code)
        return found

    def ids_for(item):
        if item.get("inferred"):
            return []
        metrics = item_metrics(item)
        return [query["executionId"] for query in catalog
                if query.get("executionId") and set(query.get("metricCodes") or []) & metrics]

    for key in ("findings", "causes", "analysisDimensions"):
        for item in result.get(key) or []:
            if isinstance(item, dict):
                item["queryIds"] = ids_for(item)
    return result


def _indicators(spec):
    """Trigger metrics an ontology risk names, e.g. "R01、B01、B02".

    The cell may add prose ("R03、B01、B02；R02作为待签规模证据"); only the
    metric codes are taken from it.
    """
    # “P0-09”“B01” are codes; a bare stage name such as “P0原因” is not.
    return list(dict.fromkeys(re.findall(r"[A-Z]\d-\d{2}|[A-Z]+\d{2}", _text(spec.get("indicators")))))


def _public(entry):
    keep = ("kind", "code", "name", "rule", "ruleStatus", "decidedBy", "established", "level",
            "reason", "error", "statusLabel", "linkedRisks", "linkedCauses", "missingEvidence", "model",
            "inferred", "aiAnalysis")
    value = {key: entry[key] for key in keep if key in entry and entry[key] not in (None, "", [])}
    value["established"] = entry.get("established")
    return value
