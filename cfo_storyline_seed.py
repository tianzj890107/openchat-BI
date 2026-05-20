# -*- coding: utf-8 -*-
"""
CFO「订-发-收-回」故事线种子数据
================================
为以下 4 条 CFO 关心的故事线在 Kingdee.db 中补充一套**自洽**的可查询数据,
足以回答各故事线的提问/追问/后续动作:

  1. 订货方向:订单增长是否真实有效?(订单质量 + 高风险订单清单)
  2. 增收方向:订单为什么没有转成收入?(订单→收入转化卡点)
  3. 现金方向:收入有没有真正变成现金?(收入→现金 + 重点客户回款)
  4. 盈利方向:增长有没有带来利润?(利润桥/驱动分解 + 低毛利清单)

设计原则:
  - 全部用 T_CFO_ 前缀的独立表,**不改动** T_SAL_/T_AR_/T_FM_ 等既有表,
    避免破坏驾驶舱已接入的四段实物流、应收账龄、管报损益等数据点。
  - 金额统一单位「万元」(列名带 Wan 后缀),口径在 T_CFO_StoryIndex 标注。
  - 本月 = 2026-05,上月 = 2026-04(与系统当前期间一致)。
  - 跨故事线数字相互勾稽:
      上月: 订单 8200 / 收入 7650 / 回款 7120 / 毛利率 26.5% / 费用 1520 / 净利 410
      本月: 订单 9676(+18.0%) / 收入 8180(+6.9%) / 回款 7360(+3.4%)
             / 毛利率 23.8% / 费用 1690 / 净利 318(-22.4%)
      现金转化率 = 回款/收入: 上月 93.1% → 本月 90.0%(下降)
      ΔAR ≈ 收入-回款 = 8180-7360 = 820;重点客户 top3 贡献 504(≈61%)
      利润桥: 410 →(规模 +260)(价格 -158)(成本 -64)(费用 -130)→ 318
"""

import sqlite3

DB_PATH = "Kingdee.db"

CUR, PRE = "2026-05", "2026-04"


def rebuild(con):
    cur = con.cursor()

    # ---- 故事线索引(让 BI/报表 Agent 知道去哪张表取数) ----------------
    cur.executescript("""
    DROP TABLE IF EXISTS T_CFO_StoryIndex;
    CREATE TABLE T_CFO_StoryIndex(
      FStoryNo     INTEGER,
      FDirection   TEXT,   -- 订货/增收/现金/盈利
      FQuestion    TEXT,
      FTable       TEXT,   -- 回答该故事线的主表(可能多张,逗号分隔)
      FUnit        TEXT,   -- 金额单位
      FCurMonth    TEXT,
      FPreMonth    TEXT
    );
    """)
    cur.executemany(
        "INSERT INTO T_CFO_StoryIndex VALUES(?,?,?,?,?,?,?)",
        [
            (1, "订货", "订单增长是否高质量?后续能否转收入?哪些订单要重点关注?",
             "T_CFO_OrderQuality, T_CFO_HighRiskOrder", "万元", CUR, PRE),
            (2, "增收", "订单增长了为什么收入没同步?卡在哪个环节?影响多少收入确认?",
             "T_CFO_OrderToRevenue", "万元", CUR, PRE),
            (3, "现金", "收入增长回款是否跟上?差距来自哪些客户?是否影响现金安全?",
             "T_CFO_RevenueToCash, T_CFO_KeyCustomerAR", "万元", CUR, PRE),
            (4, "盈利", "收入增长为何利润没同步?价格还是成本问题?哪些业务最拉低利润?",
             "T_CFO_ProfitBridge, T_CFO_LowMarginList", "万元", CUR, PRE),
        ],
    )

    # ---- 故事1:订货质量(按月×维度) ----------------------------------
    cur.executescript("""
    DROP TABLE IF EXISTS T_CFO_OrderQuality;
    CREATE TABLE T_CFO_OrderQuality(
      FMonth            TEXT,
      FDimType          TEXT,   -- 合计/区域/渠道
      FDimValue         TEXT,
      FOrderAmtWan      REAL,   -- 本月订单额
      FPreOrderAmtWan   REAL,   -- 上月订单额
      FMoMRatePct       REAL,   -- 环比增长%
      FLowMarginRatioPct  REAL, -- 低毛利订单占比%
      FHighDiscRatioPct   REAL, -- 高折扣订单(折扣≥15%)占比%
      FAvgGrossMarginPct  REAL, -- 平均毛利率%
      FAvgDiscountPct     REAL, -- 平均折扣率%
      FConvertibleRatioPct REAL,-- 预计可转收入比例%
      FNote             TEXT
    );
    """)
    oq = [
        (CUR, "合计", "全公司",   9676, 8200, 18.0, 36.0, 27.0, 23.8, 12.8, 78.0,
         "环比+18%,但低毛利/高折扣占比同步抬升,属带质量风险的增长"),
        # 区域:华东为主要增量来源
        (CUR, "区域", "华东", 4250, 3180, 33.6, 41.0, 31.0, 22.1, 14.5, 75.0,
         "本月增量主要来源;低毛利与高折扣集中,质量风险最高"),
        (CUR, "区域", "华南", 2160, 1980,  9.1, 33.0, 24.0, 24.6, 11.8, 80.0, ""),
        (CUR, "区域", "华北", 1820, 1720,  5.8, 31.0, 22.0, 25.3, 10.9, 82.0, ""),
        (CUR, "区域", "西部", 1446, 1320,  9.5, 30.0, 21.0, 25.0, 10.5, 80.0, ""),
        # 渠道:大客户(KA)为主要增量来源
        (CUR, "渠道", "大客户KA", 4820, 3520, 36.9, 42.0, 33.0, 21.6, 15.2, 76.0,
         "增量主要来自大客户,但伴随高折扣与低毛利"),
        (CUR, "渠道", "经销商", 2760, 2560,  7.8, 32.0, 22.0, 25.1, 11.0, 79.0, ""),
        (CUR, "渠道", "直销/项目", 2096, 2120, -1.1, 28.0, 18.0, 26.4, 9.0, 81.0, ""),
        # 上月对照(合计)
        (PRE, "合计", "全公司",   8200, 7050, 16.3, 28.0, 19.0, 26.5,  9.4, 80.0,
         "上月低毛利占比28%、高折扣占比19%,均低于本月,质量优于本月"),
    ]
    cur.executemany(
        "INSERT INTO T_CFO_OrderQuality VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", oq)

    # ---- 故事1后续动作:高风险订单清单(三类) -------------------------
    cur.executescript("""
    DROP TABLE IF EXISTS T_CFO_HighRiskOrder;
    CREATE TABLE T_CFO_HighRiskOrder(
      FOrderNo      TEXT,
      FCustomer     TEXT,
      FRegion       TEXT,
      FProductLine  TEXT,
      FOrderAmtWan  REAL,
      FGrossMarginPct REAL,
      FDiscountPct  REAL,
      FStatus       TEXT,    -- 未发货/已发货未签收/已签收未开票
      FRiskType     TEXT,    -- 高金额未发货/低毛利高折扣/交期临近库存不足
      FStockGapQty  REAL,    -- 库存缺口数量(交期类)
      FDueDate      TEXT,
      FOwnerDept    TEXT,    -- 联合跟进:销售/供应链/财务
      FNote         TEXT
    );
    """)
    hr = [
        ("SO-2026-1187", "华东精密制造", "华东", "A产品线", 268, 12.5, 18.0,
         "未发货", "高金额未发货", 0, "2026-05-26", "销售+供应链+财务", "金额最高的未发货订单"),
        ("SO-2026-1203", "远东能源集团", "华东", "A产品线", 212, 10.8, 16.5,
         "未发货", "高金额未发货", 0, "2026-05-29", "销售+供应链+财务", ""),
        ("SO-2026-1241", "江南装备", "华东", "C产品线", 156, 9.2, 21.0,
         "未发货", "低毛利高折扣", 0, "2026-06-02", "销售+财务", "折扣21%,毛利仅9.2%"),
        ("SO-2026-1258", "南方电气", "华南", "C产品线", 134, 8.6, 22.5,
         "已发货未签收", "低毛利高折扣", 0, "2026-05-24", "销售+财务", ""),
        ("SO-2026-1276", "中部重工", "华北", "B产品线", 121, 11.0, 19.5,
         "已签收未开票", "低毛利高折扣", 0, "2026-05-22", "财务", "已签收待开票,加速确认收入"),
        ("SO-2026-1290", "华东精密制造", "华东", "A产品线", 188, 14.0, 13.0,
         "未发货", "交期临近库存不足", 320, "2026-05-21", "供应链+销售",
         "交期临近,关键物料缺口320,需紧急排产"),
        ("SO-2026-1305", "远东能源集团", "华东", "A产品线", 142, 13.5, 14.0,
         "未发货", "交期临近库存不足", 210, "2026-05-23", "供应链+销售", ""),
        ("SO-2026-1322", "西部矿业", "西部", "B产品线", 98, 12.0, 12.5,
         "未发货", "交期临近库存不足", 150, "2026-05-25", "供应链", ""),
    ]
    cur.executemany(
        "INSERT INTO T_CFO_HighRiskOrder VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", hr)

    # ---- 故事2:订单→收入转化卡点(按环节) ---------------------------
    cur.executescript("""
    DROP TABLE IF EXISTS T_CFO_OrderToRevenue;
    CREATE TABLE T_CFO_OrderToRevenue(
      FMonth          TEXT,
      FStage          TEXT,   -- 未发货/已发货未签收/已签收未开票/已开票确认收入
      FStageOrder     INTEGER,
      FOrderAmtWan    REAL,
      FOrderCount     INTEGER,
      FRatioPct       REAL,   -- 占本月新增订单比例%
      FMainProductLine TEXT,
      FMainRegion     TEXT,
      FRootCause      TEXT,
      FRevenueImpactWan REAL  -- 该环节滞留导致的本月收入确认影响
    );
    """)
    o2r = [
        (CUR, "未发货",          1, 3580, 142, 37.0, "A产品线", "华东",
         "库存不足 + 排产延迟,占比最高", 1180),
        (CUR, "已发货未签收",    2, 1910,  88, 19.7, "A产品线", "华东",
         "客户延迟收货 / 在途时间长", 520),
        (CUR, "已签收未开票",    3, 1060,  61, 11.0, "B产品线", "华南",
         "开票流程滞后,签收后未及时开票", 300),
        (CUR, "已开票确认收入",  4, 3126, 153, 32.3, "全产品线", "全区域",
         "已正常转收入", 0),
        (PRE, "未发货",          1, 2460, 110, 30.0, "A产品线", "华东",
         "上月未发货占比30%,低于本月37%", 760),
        (PRE, "已开票确认收入",  4, 3690, 175, 45.0, "全产品线", "全区域",
         "上月确认收入占比45%,高于本月32.3%,转化效率下降", 0),
    ]
    cur.executemany(
        "INSERT INTO T_CFO_OrderToRevenue VALUES(?,?,?,?,?,?,?,?,?,?)", o2r)

    # ---- 故事3:收入→现金(月度汇总) ---------------------------------
    cur.executescript("""
    DROP TABLE IF EXISTS T_CFO_RevenueToCash;
    CREATE TABLE T_CFO_RevenueToCash(
      FMonth            TEXT,
      FRevenueWan       REAL,
      FPreRevenueWan    REAL,
      FRevenueMoMPct    REAL,
      FCollectionWan    REAL,   -- 回款
      FPreCollectionWan REAL,
      FCollectionMoMPct REAL,
      FCashConvRatePct  REAL,   -- 经营现金转化率 = 回款/收入
      FPreCashConvRatePct REAL,
      FAROpenWan        REAL,   -- 应收账款余额(期末)
      FARDeltaWan       REAL,   -- 应收净增加
      FOverdueAmtWan    REAL,   -- 逾期应收
      FCashSafety       TEXT,   -- 现金安全评估
      FNote             TEXT
    );
    """)
    r2c = [
        (CUR, 8180, 7650, 6.9, 7360, 7120, 3.4, 90.0, 93.1, 2360, 820, 386,
         "短期可控",
         "收入增速(6.9%)快于回款增速(3.4%),现金转化率93.1%→90.0%,部分收入滞留应收"),
        (PRE, 7650, 7150, 7.0, 7120, 6760, 5.3, 93.1, 94.5, 1540, 530, 274,
         "安全", "上月转化率94.5%→93.1%,差距已现端倪"),
    ]
    cur.executemany(
        "INSERT INTO T_CFO_RevenueToCash VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", r2c)

    # ---- 故事3:重点客户回款跟踪表 -----------------------------------
    cur.executescript("""
    DROP TABLE IF EXISTS T_CFO_KeyCustomerAR;
    CREATE TABLE T_CFO_KeyCustomerAR(
      FCustomer       TEXT,
      FCustomerTier   TEXT,   -- 大客户KA/重点/一般
      FRegion         TEXT,
      FAROpenWan      REAL,   -- 应收余额
      FARDeltaWan     REAL,   -- 本月应收增加
      FAvgTermDays    INTEGER,-- 当前平均账期(天)
      FPreTermDays    INTEGER,-- 上月平均账期(天)
      FOverdueAmtWan  REAL,   -- 逾期金额
      FMaxOverdueDays INTEGER,
      FContribRatioPct REAL,  -- 占应收净增加比例%
      FAction         TEXT    -- 高风险应收督办动作
    );
    """)
    kc = [
        ("华东精密制造", "大客户KA", "华东", 612, 212, 78, 60, 96, 41, 25.9,
         "发起高风险应收督办,冻结新增高折扣订单直至回款"),
        ("远东能源集团", "大客户KA", "华东", 498, 168, 66, 45, 74, 33, 20.5,
         "重点客户回款跟踪,商务约谈缩短账期"),
        ("江南装备",     "大客户KA", "华东", 356, 124, 52, 30, 41, 22, 15.1,
         "纳入回款跟踪表,逐单催收"),
        ("南方电气",     "重点",     "华南", 214,  78, 48, 38, 22, 15,  9.5,
         "常规跟踪"),
        ("中部重工",     "重点",     "华北", 188,  62, 45, 40, 16, 12,  7.6,
         "常规跟踪"),
        ("其他客户合计", "一般",     "多区域", 492, 176, 0, 0, 137, 0, 21.5,
         "分散监控"),
    ]
    cur.executemany(
        "INSERT INTO T_CFO_KeyCustomerAR VALUES(?,?,?,?,?,?,?,?,?,?,?)", kc)

    # ---- 故事4:利润桥 / 驱动分解(本月 vs 上月) ----------------------
    cur.executescript("""
    DROP TABLE IF EXISTS T_CFO_ProfitBridge;
    CREATE TABLE T_CFO_ProfitBridge(
      FMonth            TEXT,
      FRevenueWan       REAL,
      FPreRevenueWan    REAL,
      FGrossMarginPct   REAL,
      FPreGrossMarginPct REAL,
      FExpenseWan       REAL,
      FPreExpenseWan    REAL,
      FNetProfitWan     REAL,
      FPreNetProfitWan  REAL,
      FNetProfitMoMPct  REAL,
      FVolumeEffectWan  REAL,  -- 规模/销量贡献(+)
      FPriceEffectWan   REAL,  -- 价格端(折扣↑/低毛利客户↑)影响(-)
      FCostEffectWan    REAL,  -- 成本端(原料/制造↑)影响(-)
      FExpenseEffectWan REAL,  -- 费用端(费用投入↑)影响(-)
      FMainDriver       TEXT,
      FNote             TEXT
    );
    """)
    pb = [
        (CUR, 8180, 7650, 23.8, 26.5, 1690, 1520, 318, 410, -22.4,
         260, -158, -64, -130, "价格端",
         "净利 410→318(-92):规模+260,价格端-158(最大),成本-64,费用-130;"
         "价格端(高折扣/低毛利客户)是利润被侵蚀的主因,成本上涨为次要因素"),
    ]
    cur.executemany(
        "INSERT INTO T_CFO_ProfitBridge VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", pb)

    # ---- 故事4:低毛利订单 / 高折扣客户清单 ---------------------------
    cur.executescript("""
    DROP TABLE IF EXISTS T_CFO_LowMarginList;
    CREATE TABLE T_CFO_LowMarginList(
      FDimType        TEXT,   -- 产品线/客户/区域
      FDimValue       TEXT,
      FRevenueWan     REAL,
      FGrossMarginPct REAL,
      FAvgDiscountPct REAL,
      FProfitDragWan  REAL,   -- 对利润的拖累(负向贡献)
      FAction         TEXT    -- 价格复核与利润改善督办
    );
    """)
    lm = [
        ("产品线", "C产品线",       1320,  9.4, 20.5, -86, "价格复核,设置最低毛利红线"),
        ("产品线", "A产品线(低配)", 1180, 12.2, 17.0, -58, "复核折扣审批权限"),
        ("客户",   "华东精密制造",   980, 10.1, 18.5, -64, "纳入高折扣客户价格复核"),
        ("客户",   "远东能源集团",   860, 11.0, 16.5, -47, "利润改善督办,重谈商务条款"),
        ("客户",   "江南装备",       640,  9.8, 21.0, -39, "限制高折扣下单"),
        ("区域",   "华东",          4250, 22.1, 14.5, -132, "区域级折扣管控 + 利润改善督办"),
        ("区域",   "华南",          2160, 24.6, 11.8, -41, "常规监控"),
    ]
    cur.executemany(
        "INSERT INTO T_CFO_LowMarginList VALUES(?,?,?,?,?,?,?)", lm)

    con.commit()


def main():
    con = sqlite3.connect(DB_PATH)
    try:
        rebuild(con)
        cur = con.cursor()
        tabs = [
            "T_CFO_StoryIndex", "T_CFO_OrderQuality", "T_CFO_HighRiskOrder",
            "T_CFO_OrderToRevenue", "T_CFO_RevenueToCash", "T_CFO_KeyCustomerAR",
            "T_CFO_ProfitBridge", "T_CFO_LowMarginList",
        ]
        print("CFO 故事线种子数据写入完成 (Kingdee.db):")
        for t in tabs:
            n = cur.execute('SELECT COUNT(*) FROM "%s"' % t).fetchone()[0]
            print("  %-26s %3d 行" % (t, n))
    finally:
        con.close()


if __name__ == "__main__":
    main()
