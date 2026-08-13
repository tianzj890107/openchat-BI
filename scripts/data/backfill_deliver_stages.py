# -*- coding: utf-8 -*-
"""
补全 T_CFO_OrderToRevenue:把 2026-05「已签收未开票」(1060/61/11.0%/300) 拆为
页面发-收下钻所需的细粒度环节,使 salesGapDeliver 完全由数据库支撑。
勾稽守恒:三细行求和 = 原粗行,全月总额仍 9676,OrderQuality 合计不变。
幂等:按 FMonth 重建 2026-05 全部环节行;并统一 FStageOrder 顺序。
"""
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bi_agent.paths import DATABASES_DIR

DB = PROJECT_ROOT / DATABASES_DIR / "Kingdee.db"

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

def main() -> None:
    with sqlite3.connect(DB) as connection:
        cur = connection.cursor()

        before = list(cur.execute(
            "SELECT FStage, FOrderAmtWan, FOrderCount, FRatioPct, FRevenueImpactWan "
            "FROM T_CFO_OrderToRevenue WHERE FMonth='2026-05' ORDER BY FStageOrder"))
        print("BEFORE 2026-05:")
        for row in before:
            print("  ", row)

        cur.execute("DELETE FROM T_CFO_OrderToRevenue WHERE FMonth='2026-05'")
        cur.executemany(
            "INSERT INTO T_CFO_OrderToRevenue "
            "(FMonth,FStage,FStageOrder,FOrderAmtWan,FOrderCount,FRatioPct,"
            " FMainProductLine,FMainRegion,FRootCause,FRevenueImpactWan) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)", ROWS_202605)

        # 跨月一致:上月「已开票确认收入」也排到链路末位(6),未发货保持 1
        cur.execute("UPDATE T_CFO_OrderToRevenue SET FStageOrder=6 "
                    "WHERE FMonth='2026-04' AND FStage='已开票确认收入'")
        connection.commit()

        after = list(cur.execute(
            "SELECT FStage, FOrderAmtWan, FOrderCount, FRatioPct, FRevenueImpactWan "
            "FROM T_CFO_OrderToRevenue WHERE FMonth='2026-05' ORDER BY FStageOrder"))
        total_amount = sum(row[1] for row in after)
        total_count = sum(row[2] for row in after)
        total_impact = sum(row[4] for row in after)
        print("\nAFTER 2026-05:")
        for row in after:
            print("  ", row)
        print(f"\n勾稽校验:总额={total_amount:.0f}万 (应=9676), "
              f"订单数={total_count} (应=444), "
              f"收入确认影响={total_impact:.0f}万 (应=2000)")
        sub = [row for row in after if row[0] in ("已签收未安装", "已安装未验收")]
        print("发-收页用两环节:", [(row[0], row[1], row[2], row[3], row[4]) for row in sub],
              "→ 合计", sum(row[1] for row in sub), "万")
        print("OK" if (
            total_amount == 9676 and total_count == 444 and total_impact == 2000
        ) else "FAIL: 勾稽不平")


if __name__ == "__main__":
    main()
