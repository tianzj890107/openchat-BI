# -*- coding: utf-8 -*-
"""
补全 T_CFO_OrderToRevenue:把 2026-05「已签收未开票」(1060/61/11.0%/300) 拆为
页面发-收下钻所需的细粒度环节,使 salesGapDeliver 完全由数据库支撑。
勾稽守恒:三细行求和 = 原粗行,全月总额仍 9676,OrderQuality 合计不变。
幂等:按 FMonth 重建 2026-05 全部环节行;并统一 FStageOrder 顺序。
"""
import sqlite3

DB = "Kingdee.db"

# (FMonth, FStage, FStageOrder, FOrderAmtWan, FOrderCount, FRatioPct,
#  FMainProductLine, FMainRegion, FRootCause, FRevenueImpactWan)
ROWS_202605 = [
    ("2026-05", "未发货",        1, 3580.0, 142, 37.0, "A产品线", "华东",
     "库存不足 + 排产延迟,占比最高", 1180.0),
    ("2026-05", "已发货未签收",  2, 1910.0,  88, 19.7, "A产品线", "华东",
     "客户延迟收货 / 在途时间长", 520.0),
    ("2026-05", "已签收未安装",  3,  470.0,  27,  4.9, "A产品线", "华东",
     "设备到货待排期安装,现场安装资源不足", 130.0),
    ("2026-05", "已安装未验收",  4,  380.0,  21,  3.9, "A产品线", "华东",
     "客户验收周期长,验收标准与流程待确认", 110.0),
    ("2026-05", "已验收未开票",  5,  210.0,  13,  2.2, "B产品线", "华南",
     "开票流程滞后,验收后未及时开票", 60.0),
    ("2026-05", "已开票确认收入", 6, 3126.0, 153, 32.3, "全产品线", "全区域",
     "已正常转收入", 0.0),
]

with sqlite3.connect(DB) as c:
    cur = c.cursor()

    before = list(cur.execute(
        "SELECT FStage, FOrderAmtWan, FOrderCount, FRatioPct, FRevenueImpactWan "
        "FROM T_CFO_OrderToRevenue WHERE FMonth='2026-05' ORDER BY FStageOrder"))
    print("BEFORE 2026-05:")
    for r in before:
        print("  ", r)

    cur.execute("DELETE FROM T_CFO_OrderToRevenue WHERE FMonth='2026-05'")
    cur.executemany(
        "INSERT INTO T_CFO_OrderToRevenue "
        "(FMonth,FStage,FStageOrder,FOrderAmtWan,FOrderCount,FRatioPct,"
        " FMainProductLine,FMainRegion,FRootCause,FRevenueImpactWan) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)", ROWS_202605)

    # 跨月一致:上月「已开票确认收入」也排到链路末位(6),未发货保持 1
    cur.execute("UPDATE T_CFO_OrderToRevenue SET FStageOrder=6 "
                "WHERE FMonth='2026-04' AND FStage='已开票确认收入'")
    c.commit()

    after = list(cur.execute(
        "SELECT FStage, FOrderAmtWan, FOrderCount, FRatioPct, FRevenueImpactWan "
        "FROM T_CFO_OrderToRevenue WHERE FMonth='2026-05' ORDER BY FStageOrder"))
    tot_amt = sum(r[1] for r in after)
    tot_cnt = sum(r[2] for r in after)
    tot_imp = sum(r[4] for r in after)
    print("\nAFTER 2026-05:")
    for r in after:
        print("  ", r)
    print(f"\n勾稽校验:总额={tot_amt:.0f}万 (应=9676), "
          f"订单数={tot_cnt} (应=444), 收入确认影响={tot_imp:.0f}万 (应=2000)")
    sub = [r for r in after if r[0] in ("已签收未安装", "已安装未验收")]
    print("发-收页用两环节:", [(r[0], r[1], r[2], r[3], r[4]) for r in sub],
          "→ 合计", sum(r[1] for r in sub), "万")
    print("OK" if (tot_amt == 9676 and tot_cnt == 444 and tot_imp == 2000)
          else "FAIL: 勾稽不平")
