"""Deterministic, reconciled POC dataset and a source adapter boundary.

Amounts are CNY 100 million; volume is GWh. Source dates are explicit.
No production connection or user dataset is modified by this module.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Protocol

PERIODS = ("2025-10", "2025-09")
DEPARTMENTS = ("全部产品部", "AIDC产品部", "国内电力产品部", "国际电力产品部")
STAGES = (
    ("opportunity", "商机获取", 280., 319., 12, 10),
    ("guidance", "方案引导", 82., 105., 14, 10),
    ("quotation", "报价", 1056., 1200., 16, 9),
    ("technical", "技术方案", 30.3, 37.6, 7, 5),
    ("bid", "投标", 24., 49., 22, 18),
    ("order", "订单接收", 236., 319., 27, 15),
    ("shipment", "发货", 191.4, 236., 34, 20),
)
CAUSES = (
    ("排产问题", "运营管理部／PMC", "确认锁定产能及承诺发货日", [3.4, 2.8, 1.7]),
    ("厂线生产与质量", "制造中心／质量管理部", "核实补料、返工与质检放行日期", [4.8, 1.6, 1.1]),
    ("物流及单证", "物流中心", "补齐认证单证并确认舱位", [2., 1.4, 1.1]),
    ("客户提货", "产品部销售负责人", "取得客户确认的分批提货计划", [2.1, 1.3, 1.]),
)
NAMES = {s[0]: s[1] for s in STAGES}


def _rows():
    rows = []
    i = 0
    for cause, owner, action, amounts in CAUSES:
        for amount in amounts:
            i += 1
            dept = DEPARTMENTS[1 + (i - 1) % 3]
            quality = cause == "厂线生产与质量" and amount == 4.8
            rows.append(dict(id=f"SO-2025-{i:04}", customer="S1 战略客户" if quality else f"{'S' if i < 8 else 'K'}{i} 客户",
                tier="战略客户" if i < 8 else "重点客户", department=dept, amount=amount,
                overdueDays=82-i*4, cause=cause, owner=owner, action=action,
                evidence=f"订单交期与{cause}处理记录（演示）", status="超期未发",
                commitment=f"2025-11-{5+i:02}", product="LF280K" if i % 2 else "MB31"))
    return rows


def stage_records(stage, period, department):
    """Separate business records per stage; never infer causes from totals."""
    rows=[]
    if stage == "quotation":
        count=120 if period=="2025-10" else 108
        for i in range(count):
            product="LF280K" if i<56 else "MB31" if i<96 else "其他型号"
            cause=["审批记录：一般客户低毛利申请已特批，需复核定价依据", "报价备注：竞品比价依据待补充", "审批附件：产能与库存理由尚未核验"][i%3]
            rows.append(dict(id=f"QUOTE-{period}-{i+1:03}",customer=f"客户 {i+1:03}",department=DEPARTMENTS[1 if i<48 else 2 if i<90 else 3],
                product=product, tier="一般客户" if i<55 else "重点客户" if i<107 else "战略客户",region="华北" if i<62 else "其他区域",
                amount=None,overdueDays=0,status="红区申请已获批",cause=cause,evidence="报价申请与审批记录（演示）；毛利率低于12%"))
    elif stage == "opportunity":
        for i in range(20):
            rows.append(dict(id=f"OPP-{period}-{i+1:03}",customer=f"S{i+1} 战略客户",department=DEPARTMENTS[1+i%3],
                product="PACK" if i%2 else "电芯",amount=None,overdueDays=i+2,status="尚无商机" if i<7 else "已有商机未进投标",
                cause="战略客户清单与商机台账无匹配记录" if i<7 else "客户商机已登记，投标推进条件尚未完成",
                evidence="战略客户名单、商机台账与阶段记录（演示样本，不代表全部商机）"))
    elif stage == "bid":
        for i in range(49):
            status="中标" if i<24 else "丢标" if i<44 else "弃标"
            rows.append(dict(id=f"BID-{period}-{i+1:03}",customer=f"投标客户 {i+1:02}",department=DEPARTMENTS[1+i%3],amount=None,
                overdueDays=0,status=status,cause="结果记录已登记" if status=="中标" else "复盘记录：技术响应、价格或材料条件需核实",
                evidence="独立投标项目结果台账（演示）"))
    elif stage == "order":
        for i in range(8):
            rows.append(dict(id=f"ORDER-{period}-{i+1:03}",customer=f"订单客户 {i+1:02}",department=DEPARTMENTS[1+i%3],
                amount=round((1 if i<4 else .75)*(1 if period=="2025-10" else .9),3),overdueDays=i*2,
                status="订单取消" if i<4 else "变更减少",cause="客户需求调整记录，需核实替代需求与交付计划",
                evidence="取消／减量变更台账（演示）；不计入超期未发"))
    else:
        for i in range(9):
            rows.append(dict(id=f"{stage.upper()}-{period}-{i+1:03}",customer=f"技术项目客户 {i+1}",department=DEPARTMENTS[1+i%3],
                amount=None,overdueDays=3+i*2,status=["待接口会审","待客户技术反馈","待测试报告"][i%3],
                cause=["接口会审纪要尚未签署","客户反馈节点记录尚未关闭","测试报告清单存在缺项"][i%3],
                evidence="方案／技术环节处理记录（演示）"))
    return [r for r in rows if department==DEPARTMENTS[0] or r["department"]==department]


class CockpitSource(Protocol):
    """Future ontology/database adapter must return this same evidence contract."""
    def snapshot(self, period: str, department: str) -> dict: ...


class DemoSource:
    version = "cockpit-v3-demo-2"

    def snapshot(self, period="2025-10", department="全部产品部"):
        if period not in PERIODS or department not in DEPARTMENTS:
            raise ValueError("不支持的期间或产品部")
        # September is an independent as-of snapshot, not mixed with October.
        factor = 1. if period == "2025-10" else .9
        all_rows = _rows()
        for row in all_rows:
            row["amount"] = round(row["amount"] * factor, 3)
            row["id"] = row["id"] + ("-09" if period == "2025-09" else "")
            row["overdueDays"] = max(1, row["overdueDays"] - (8 if period == "2025-09" else 0))
        rows = [r for r in all_rows if department == DEPARTMENTS[0] or r["department"] == department]
        # Fixed disjoint department weights, shared by all page aggregates.
        weight = {DEPARTMENTS[0]: 1., DEPARTMENTS[1]: .4, DEPARTMENTS[2]: .35, DEPARTMENTS[3]: .25}[department]
        target = round(319 * weight, 3)
        actual = round(191.4 * weight * factor, 3)
        orders = round(236 * weight * factor, 3)
        overdue = round(sum(r["amount"] for r in rows), 3)
        backlog = round(orders - actual, 3)
        normal = round(backlog - overdue, 3)
        # Volume comes from the explicitly declared demo conversion, not a real measurement.
        volume = round(actual * 91 / 319, 3)
        forecast = round(280 * weight * factor, 3)
        stages = []
        for sid, name, done, total, cycle, baseline in STAGES:
            d, t = round(done * weight * factor, 3), round(total * weight, 3)
            if sid == "shipment": d, t = actual, orders
            stages.append(dict(id=sid, name=name, done=d, total=t,
                rate=round(d/t*100, 1) if t else 0, cycle=cycle, baseline=baseline,
                unit="单" if sid == "quotation" else "项" if sid == "bid" else "亿元",
                note="各环节为独立统计口径，不可相加；不表示同一批项目的漏斗转化"))
        monthly = []
        end = 10 if period == "2025-10" else 9
        shares = [0.07, .065, .085, .09, .095, .105, .105, .12, .125, .14][:end]
        total_share = sum(shares)
        values = [round(actual * x / total_share, 3) for x in shares]
        values[-1] = round(actual - sum(values[:-1]), 3)
        targets = [round(target/12, 3)] * 12
        targets[-1] = round(target-sum(targets[:-1]), 3)
        future = [round((forecast-actual)/(12-end), 3)] * (12-end)
        future[-1] = round(forecast-actual-sum(future[:-1]), 3)
        for m in range(1, 13):
            monthly.append(dict(month=f"{m:02}月", actual=values[m-1] if m <= end else None,
                target=targets[m-1], forecast=future[m-end-1] if m > end else None))
        causes = [dict(name=cause, amount=round(sum(r["amount"] for r in rows if r["cause"] == cause), 3), owner=owner, action=action)
            for cause, owner, action, _ in CAUSES]
        by_dept = [dict(name=d, target=round(319*w,3), actual=round(191.4*w*factor,3))
            for d,w in zip(DEPARTMENTS[1:], [.4,.35,.25]) if department == DEPARTMENTS[0] or department == d]
        risks = [dict(id="shipment", title="超期未发影响交付", level="极高", metric=overdue, unit="亿元", summary="优先核实战略与重点客户的交付卡点"),
            dict(id="quotation", title="红区报价集中", level="高", metric=len(stage_records("quotation",period,department)), unit="单", summary="按已获批申请单数统计；金额不作为红区申请口径"),
            dict(id="opportunity", title="商机覆盖存在缺口", level="高", metric=round(target-forecast,3), unit="亿元", summary="已有业务预测与年度目标之差，非现场统计预测"),
            dict(id="bid", title="投标推进与弃标风险", level="高", metric=round(1.1*weight*factor,3), unit="GWh", summary="核实会签、产能承诺及保函材料"),
            dict(id="order", title="订单取消与减量", level="高", metric=round(sum(r["amount"] for r in stage_records("order",period,department)),3), unit="亿元", summary="取消与减量单列，不重复计入超期未发")]
        result = dict(sourceMode="demo", sourceLabel="演示数据 · 非生产实绩", version=self.version,
            period=period, department=department, asOf=period+("-31" if period.endswith("10") else "-30"),
            metrics=dict(target=target, actual=actual, orders=orders, overdue=overdue, normal=normal, backlog=backlog,
                attainment=round(actual/target*100,1), forecast=forecast, gap=round(target-actual,3),
                volume=volume, volumeTarget=round(91*weight,3), forecastVolume=round(forecast*91/319,3)),
            stages=stages, rows=rows, causes=causes, risks=risks, monthly=monthly, departments=by_dept,
            definitions=["销售额采用演示发货额口径，不等同财务确认收入", "订未发＝订单接收－已发货＝正常待发＋超期未发",
                "电量按演示比例 319 亿元／91 GWh 折算，不代表真实量价关系", "年度预测来自演示业务预测，不是现场统计预测",
                "原因金额按订单单一主因互斥汇总；各环节的独立统计量不可直接相加"])
        result["snapshotId"] = hashlib.sha256(json.dumps(result,ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:20]
        return result

    def evidence(self, snapshot: dict, stage: str):
        if stage not in NAMES:
            raise ValueError("未知环节")
        s = deepcopy(snapshot)
        rows = s["rows"]
        if stage != "shipment":
            # Explicit per-stage source records; no shipping causes reused as bid/quotation facts.
            selected = next(r for r in s["risks"] if r["id"] == stage) if stage in {r["id"] for r in s["risks"]} else None
            rows = stage_records(stage,s["period"],s["department"])
            stage_meta = next(x for x in s["stages"] if x["id"] == stage)
            facts = [dict(id=f"{stage}:stage", label=f"{NAMES[stage]}完成情况", value=stage_meta["done"], unit=stage_meta["unit"], definition=stage_meta["note"])]
            if selected: facts.append(dict(id=f"{stage}:risk",label=selected["title"],value=selected["metric"],unit=selected["unit"],definition=selected["summary"]))
        else:
            facts = [dict(id=f"shipment:{k}",label=l,value=s["metrics"][k],unit="亿元",definition=d)
                for k,l,d in [("overdue","超期未发","订单逐单汇总"),("backlog","订未发","订单接收减已发货"),("normal","正常待发","订未发减超期未发")]]
        if stage == "quotation":
            for label in ["LF280K","MB31","其他型号"]:
                facts.append(dict(id="quotation:product:"+label,label=label+"红区获批",value=sum(r["product"]==label for r in rows),unit="单",definition="按当前范围已获批红区申请逐单计数"))
        elif stage == "opportunity":
            for label in ["尚无商机","已有商机未进投标"]:
                facts.append(dict(id="opportunity:"+label,label=label,value=sum(r["status"]==label for r in rows),unit="家",definition="当前范围战略客户演示样本，不代表全部客户"))
        elif stage == "bid":
            for label in ["中标","丢标","弃标"]:
                facts.append(dict(id="bid:"+label,label=label,value=sum(r["status"]==label for r in rows),unit="项",definition="当前范围独立投标结果样本"))
        evidence = facts + [dict(id=r["id"],label=r["customer"],value=r.get("amount"),unit="亿元" if r.get("amount") is not None else "",definition=r["cause"],record=r) for r in rows]
        return dict(snapshotId=s["snapshotId"],sourceMode="demo",stage=stage,stageName=NAMES[stage],period=s["period"],department=s["department"],
            facts=facts, records=rows, evidence=evidence, causes=s["causes"] if stage=="shipment" else [],
            limitations=["全部证据为 POC 演示记录", "仅对当前快照和筛选范围有效", "建议目标需人工确认，不是收益承诺"])
