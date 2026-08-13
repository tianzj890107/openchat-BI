import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bi_agent.paths import DATABASES_DIR


DB_PATH = PROJECT_ROOT / DATABASES_DIR / "Kingdee.db"


def table_columns(cur, table_name):
    return {row[1] for row in cur.execute(f"pragma table_info({table_name})")}


def add_column_if_missing(cur, table_name, column_name, column_type):
    if column_name not in table_columns(cur, table_name):
        cur.execute(f"alter table {table_name} add column {column_name} {column_type}")


def main():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    cur.execute(
        """
        create table if not exists T_MFG_WorkOrder (
          FWorkOrderNo TEXT NOT NULL PRIMARY KEY,
          FStatus TEXT NOT NULL,
          FCreateDate TEXT NOT NULL,
          FApproveDate TEXT,
          FOwner TEXT NOT NULL
        )
        """
    )

    for column_name, column_type in [
        ("FPurchaseOrderNo", "TEXT"),
        ("FDemandWorkOrderNo", "TEXT"),
        ("FPlanIssueDate", "TEXT"),
        ("FPlanIssueOwner", "TEXT"),
    ]:
        add_column_if_missing(cur, "T_STK_Inventory", column_name, column_type)

    add_column_if_missing(cur, "T_PUR_POOrder", "FPOType", "TEXT")

    for column_name, column_type in [
        ("FPlanReceiptShipDate", "TEXT"),
        ("FReceivedQty", "REAL"),
        ("FInspectQty", "REAL"),
        ("FStockInQty", "REAL"),
    ]:
        add_column_if_missing(cur, "T_PUR_POOrderEntry", column_name, column_type)

    cur.execute(
        """
        update T_PUR_POOrder
           set FPOType = '标准采购订单'
         where FPOType is null or FPOType = ''
        """
    )
    cur.execute(
        """
        update T_PUR_POOrderEntry
           set FPlanReceiptShipDate = coalesce(FPlanReceiptShipDate, FReturnDeadline)
        """
    )
    cur.execute(
        """
        update T_PUR_POOrderEntry
           set FReceivedQty = coalesce(FReceivedQty, FQty),
               FInspectQty = coalesce(FInspectQty, FQty),
               FStockInQty = coalesce(FStockInQty, FQty)
         where FReceivedQty is null
            or FInspectQty is null
            or FStockInQty is null
        """
    )

    work_orders = [
        ("MO-OVERDUE-CLOSED-001", "已关闭", "2026-02-18", "2026-02-20", "张强"),
        ("MO-OVERDUE-CLOSED-002", "已关闭", "2026-03-01", "2026-03-03", "李敏"),
        ("MO-NORMAL-OPEN-001", "已审批", "2026-04-01", "2026-04-02", "王磊"),
    ]
    cur.executemany(
        """
        insert into T_MFG_WorkOrder
          (FWorkOrderNo, FStatus, FCreateDate, FApproveDate, FOwner)
        values (?, ?, ?, ?, ?)
        on conflict(FWorkOrderNo) do update set
          FStatus = excluded.FStatus,
          FCreateDate = excluded.FCreateDate,
          FApproveDate = excluded.FApproveDate,
          FOwner = excluded.FOwner
        """,
        work_orders,
    )

    po_orders = [
        (
            "PO-RET-OVERDUE-001",
            "PO-RET-NO-00001",
            "2026-03-05",
            "2026-03-12",
            "SUP003",
            "Approved",
            "退货采购订单",
        ),
        (
            "PO-STD-SAMPLE-001",
            "PO-STD-NO-00001",
            "2026-04-15",
            "2026-04-22",
            "SUP005",
            "Approved",
            "标准采购订单",
        ),
    ]
    cur.executemany(
        """
        insert into T_PUR_POOrder
          (FBillId, FBillNo, FDate, FReceiptDate, FSupplierId, FStatus, FPOType)
        values (?, ?, ?, ?, ?, ?, ?)
        on conflict(FBillId) do update set
          FBillNo = excluded.FBillNo,
          FDate = excluded.FDate,
          FReceiptDate = excluded.FReceiptDate,
          FSupplierId = excluded.FSupplierId,
          FStatus = excluded.FStatus,
          FPOType = excluded.FPOType
        """,
        po_orders,
    )

    po_entries = [
        (
            "POE-RET-OVERDUE-001",
            "PO-RET-OVERDUE-001",
            "MAT006",
            120,
            7200,
            "2026-03-20",
            "2026-03-20",
            0,
            0,
            0,
        ),
        (
            "POE-STD-SAMPLE-001",
            "PO-STD-SAMPLE-001",
            "MAT011",
            80,
            4800,
            "2026-04-22",
            "2026-04-22",
            80,
            80,
            80,
        ),
    ]
    cur.executemany(
        """
        insert into T_PUR_POOrderEntry
          (
            FEntryId, FBillId, FMaterialId, FQty, FAmount, FReturnDeadline,
            FPlanReceiptShipDate, FReceivedQty, FInspectQty, FStockInQty
          )
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        on conflict(FEntryId) do update set
          FBillId = excluded.FBillId,
          FMaterialId = excluded.FMaterialId,
          FQty = excluded.FQty,
          FAmount = excluded.FAmount,
          FReturnDeadline = excluded.FReturnDeadline,
          FPlanReceiptShipDate = excluded.FPlanReceiptShipDate,
          FReceivedQty = excluded.FReceivedQty,
          FInspectQty = excluded.FInspectQty,
          FStockInQty = excluded.FStockInQty
        """,
        po_entries,
    )

    inventory_rows = [
        (
            "INV-OVERDUE-WO-CLOSED-001",
            "MAT006",
            "PER202604",
            "STK-09",
            120,
            7200,
            "2026-02-21",
            "B-MO-CLOSED-001",
            "ORG006",
            "电子件",
            200,
            "硕磐智造中心",
            "原材料",
            "PO-STD-NO-00001",
            "MO-OVERDUE-CLOSED-001",
            "2026-03-01",
            "张强",
        ),
        (
            "INV-OVERDUE-WO-CLOSED-002",
            "MAT011",
            "PER202604",
            "STK-10",
            80,
            4800,
            "2026-03-04",
            "B-MO-CLOSED-002",
            "ORG011",
            "结构件",
            200,
            "硕磐产业基地",
            "半成品",
            None,
            "MO-OVERDUE-CLOSED-002",
            "2026-03-08",
            "李敏",
        ),
        (
            "INV-OVERDUE-NO-WO-001",
            "MAT016",
            "PER202604",
            "STK-11",
            150,
            9000,
            "2026-03-06",
            "B-NO-WO-001",
            "ORG016",
            "包材",
            200,
            "硕磐研发中心",
            "原材料",
            None,
            None,
            "2026-03-10",
            "赵倩",
        ),
        (
            "INV-OVERDUE-RETURN-001",
            "MAT006",
            "PER202604",
            "STK-12",
            120,
            7200,
            "2026-03-05",
            "B-RET-001",
            "ORG006",
            "电子件",
            200,
            "硕磐智造中心",
            "原材料",
            "PO-RET-NO-00001",
            None,
            "2026-03-20",
            "采购退货负责人-王五",
        ),
    ]
    cur.executemany(
        """
        insert into T_STK_Inventory
          (
            FInvId, FMaterialId, FPeriodId, FStockId, FOnHandQty, FOnHandAmt,
            FInDate, FBatchNo, FStockOrg, FItemCategory, FSafeStockQty,
            FStockOrgDesc, FStockCategory, FPurchaseOrderNo, FDemandWorkOrderNo,
            FPlanIssueDate, FPlanIssueOwner
          )
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        on conflict(FInvId) do update set
          FMaterialId = excluded.FMaterialId,
          FPeriodId = excluded.FPeriodId,
          FStockId = excluded.FStockId,
          FOnHandQty = excluded.FOnHandQty,
          FOnHandAmt = excluded.FOnHandAmt,
          FInDate = excluded.FInDate,
          FBatchNo = excluded.FBatchNo,
          FStockOrg = excluded.FStockOrg,
          FItemCategory = excluded.FItemCategory,
          FSafeStockQty = excluded.FSafeStockQty,
          FStockOrgDesc = excluded.FStockOrgDesc,
          FStockCategory = excluded.FStockCategory,
          FPurchaseOrderNo = excluded.FPurchaseOrderNo,
          FDemandWorkOrderNo = excluded.FDemandWorkOrderNo,
          FPlanIssueDate = excluded.FPlanIssueDate,
          FPlanIssueOwner = excluded.FPlanIssueOwner
        """,
        inventory_rows,
    )

    cur.execute("drop view if exists V_STK_OverdueReason")
    cur.execute(
        """
        create view V_STK_OverdueReason as
        select
          inv.FInvId,
          inv.FMaterialId,
          mat.FNumber as FMaterialNumber,
          mat.FName as FMaterialName,
          inv.FStockOrg,
          inv.FStockOrgDesc,
          inv.FStockId,
          inv.FOnHandQty,
          inv.FOnHandAmt,
          inv.FInDate,
          inv.FPurchaseOrderNo,
          po.FBillNo as FPOBillNo,
          po.FPOType,
          po.FStatus as FPOStatus,
          inv.FDemandWorkOrderNo,
          wo.FStatus as FWorkOrderStatus,
          wo.FOwner as FWorkOrderOwner,
          inv.FPlanIssueDate,
          inv.FPlanIssueOwner,
          poe.FPlanReceiptShipDate,
          poe.FReceivedQty,
          poe.FInspectQty,
          poe.FStockInQty,
          cast(julianday(date('now','localtime')) - julianday(inv.FPlanIssueDate) as integer) as FPlanIssueOverdueDays,
          cast(julianday(date('now','localtime')) - julianday(poe.FPlanReceiptShipDate) as integer) as FReturnOrderOverdueDays,
          case
            when inv.FDemandWorkOrderNo is not null
             and wo.FStatus in ('已关闭','关闭','Closed','closed')
              then '生产工单关闭'
            when po.FPOType = '退货采购订单'
             and poe.FPlanReceiptShipDate is not null
             and date(poe.FPlanReceiptShipDate) < date('now','localtime')
             and coalesce(poe.FReceivedQty,0) = 0
             and coalesce(poe.FInspectQty,0) = 0
             and coalesce(poe.FStockInQty,0) = 0
              then '退货订单未执行'
            when inv.FPlanIssueDate is not null
             and date(inv.FPlanIssueDate) < date('now','localtime')
             and inv.FDemandWorkOrderNo is null
              then '未按计划时间领用'
            when inv.FPlanIssueDate is not null
             and date(inv.FPlanIssueDate) < date('now','localtime')
              then '未按计划时间领用'
            else '未超期或原因待识别'
          end as FOverdueReason,
          case
            when inv.FDemandWorkOrderNo is not null
             and wo.FStatus in ('已关闭','关闭','Closed','closed')
              then wo.FOwner
            when po.FPOType = '退货采购订单'
              then coalesce(inv.FPlanIssueOwner,'采购执行负责人待分配')
            when inv.FPlanIssueDate is not null
             and date(inv.FPlanIssueDate) < date('now','localtime')
              then inv.FPlanIssueOwner
            else coalesce(inv.FPlanIssueOwner, wo.FOwner, '责任人待分配')
          end as FResponsiblePerson
        from T_STK_Inventory inv
        left join T_BD_Material mat
          on mat.FMaterialId = inv.FMaterialId
        left join T_MFG_WorkOrder wo
          on wo.FWorkOrderNo = inv.FDemandWorkOrderNo
        left join T_PUR_POOrder po
          on po.FBillNo = inv.FPurchaseOrderNo
          or po.FBillId = inv.FPurchaseOrderNo
        left join T_PUR_POOrderEntry poe
          on poe.FBillId = po.FBillId
         and poe.FMaterialId = inv.FMaterialId
        where inv.FPlanIssueDate is not null
           or inv.FDemandWorkOrderNo is not null
           or inv.FPurchaseOrderNo is not null
        """
    )

    cur.execute(
        """
        create table if not exists T_HR_Department (
          FDeptId TEXT NOT NULL PRIMARY KEY,
          FDeptNo TEXT NOT NULL,
          FDeptName TEXT NOT NULL,
          FOrgId TEXT NOT NULL,
          FDeptType TEXT,
          FManagerPersonId TEXT,
          FIsActive TEXT NOT NULL,
          foreign key (FOrgId) references T_ORG_Organizations(FOrgId)
        )
        """
    )
    cur.execute(
        """
        create table if not exists T_HR_Person (
          FPersonId TEXT NOT NULL PRIMARY KEY,
          FPersonNo TEXT NOT NULL,
          FPersonName TEXT NOT NULL,
          FOrgId TEXT NOT NULL,
          FDeptId TEXT NOT NULL,
          FPosition TEXT NOT NULL,
          FRoleDomain TEXT,
          FMobile TEXT,
          FEmail TEXT,
          FIsActive TEXT NOT NULL,
          foreign key (FOrgId) references T_ORG_Organizations(FOrgId),
          foreign key (FDeptId) references T_HR_Department(FDeptId)
        )
        """
    )
    cur.execute(
        """
        create table if not exists T_RSP_MaterialIssueOwner (
          FRespId TEXT NOT NULL PRIMARY KEY,
          FMaterialId TEXT,
          FOrgId TEXT NOT NULL,
          FScopeName TEXT,
          FIssueType TEXT NOT NULL,
          FUrgency TEXT NOT NULL,
          FPrimaryPersonId TEXT NOT NULL,
          FActionPlan TEXT,
          FAnalysisBasis TEXT,
          FEffectiveFrom TEXT NOT NULL,
          FEffectiveTo TEXT,
          FIsActive TEXT NOT NULL,
          foreign key (FMaterialId) references T_BD_Material(FMaterialId),
          foreign key (FOrgId) references T_ORG_Organizations(FOrgId),
          foreign key (FPrimaryPersonId) references T_HR_Person(FPersonId)
        )
        """
    )
    cur.execute(
        """
        create table if not exists T_RSP_IssueCollaborator (
          FSupportId TEXT NOT NULL PRIMARY KEY,
          FRespId TEXT NOT NULL,
          FSupportPersonId TEXT NOT NULL,
          FSupportRole TEXT NOT NULL,
          FSupportAction TEXT,
          foreign key (FRespId) references T_RSP_MaterialIssueOwner(FRespId),
          foreign key (FSupportPersonId) references T_HR_Person(FPersonId)
        )
        """
    )

    departments = [
        ("DEPT-ORG011-WH", "D-ORG011-WH", "硕磐产业基地仓库", "ORG011", "仓储", "P-HR-001", "Y"),
        ("DEPT-ORG011-QA", "D-ORG011-QA", "硕磐产业基地品质部", "ORG011", "质量", "P-HR-004", "Y"),
        ("DEPT-ORG001-PMC", "D-ORG001-PMC", "杭州硕磐智能PMC部门", "ORG001", "生产计划", "P-HR-007", "Y"),
        ("DEPT-ORG001-SCM", "D-ORG001-SCM", "杭州硕磐智能供应链中心", "ORG001", "供应链", "P-HR-010", "Y"),
        ("DEPT-ORG001-FINBI", "D-ORG001-FINBI", "杭州硕磐智能管理会计/BI团队", "ORG001", "财务/IT", "P-HR-013", "Y"),
        ("DEPT-ORG001-FIN", "D-ORG001-FIN", "杭州硕磐智能财务部", "ORG001", "财务", "P-HR-002", "Y"),
        ("DEPT-ORG001-IT", "D-ORG001-IT", "杭州硕磐智能IT系统部", "ORG001", "IT", "P-HR-013", "Y"),
    ]
    cur.executemany(
        """
        insert into T_HR_Department
          (FDeptId, FDeptNo, FDeptName, FOrgId, FDeptType, FManagerPersonId, FIsActive)
        values (?, ?, ?, ?, ?, ?, ?)
        on conflict(FDeptId) do update set
          FDeptNo = excluded.FDeptNo,
          FDeptName = excluded.FDeptName,
          FOrgId = excluded.FOrgId,
          FDeptType = excluded.FDeptType,
          FManagerPersonId = excluded.FManagerPersonId,
          FIsActive = excluded.FIsActive
        """,
        departments,
    )

    people = [
        ("P-HR-001", "EMP-001", "刘建国", "ORG011", "DEPT-ORG011-WH", "仓储主管", "仓储", "13800010001", "liujg@shuopan.example", "Y"),
        ("P-HR-002", "EMP-002", "陈思敏", "ORG001", "DEPT-ORG001-FIN", "跌价核算会计", "财务", "13800010002", "chensm@shuopan.example", "Y"),
        ("P-HR-003", "EMP-003", "周晨", "ORG011", "DEPT-ORG011-QA", "报废鉴定工程师", "质量", "13800010003", "zhouc@shuopan.example", "Y"),
        ("P-HR-004", "EMP-004", "王丽娜", "ORG011", "DEPT-ORG011-QA", "质量检验负责人", "质量", "13800010004", "wangln@shuopan.example", "Y"),
        ("P-HR-005", "EMP-005", "孙浩", "ORG011", "DEPT-ORG011-WH", "仓储隔离专员", "仓储", "13800010005", "sunh@shuopan.example", "Y"),
        ("P-HR-006", "EMP-006", "郭峰", "ORG001", "DEPT-ORG001-SCM", "返修渠道负责人", "供应链", "13800010006", "guof@shuopan.example", "Y"),
        ("P-HR-007", "EMP-007", "何佳宁", "ORG001", "DEPT-ORG001-PMC", "生产计划主管", "生产计划", "13800010007", "hejn@shuopan.example", "Y"),
        ("P-HR-008", "EMP-008", "赵鹏", "ORG001", "DEPT-ORG001-SCM", "供应商沟通负责人", "采购", "13800010008", "zhaop@shuopan.example", "Y"),
        ("P-HR-009", "EMP-009", "沈悦", "ORG011", "DEPT-ORG011-WH", "出库协调员", "仓储", "13800010009", "sheny@shuopan.example", "Y"),
        ("P-HR-010", "EMP-010", "叶明", "ORG001", "DEPT-ORG001-SCM", "库存管理负责人", "库存管理", "13800010010", "yem@shuopan.example", "Y"),
        ("P-HR-011", "EMP-011", "林洁", "ORG011", "DEPT-ORG011-QA", "质量状态确认负责人", "质量", "13800010011", "linj@shuopan.example", "Y"),
        ("P-HR-012", "EMP-012", "钱森", "ORG011", "DEPT-ORG011-WH", "实物盘点负责人", "仓储", "13800010012", "qians@shuopan.example", "Y"),
        ("P-HR-013", "EMP-013", "唐宇", "ORG001", "DEPT-ORG001-FINBI", "BI系统负责人", "IT系统", "13800010013", "tangy@shuopan.example", "Y"),
        ("P-HR-014", "EMP-014", "蒋薇", "ORG001", "DEPT-ORG001-FINBI", "财务规则负责人", "财务", "13800010014", "jiangw@shuopan.example", "Y"),
        ("P-HR-015", "EMP-015", "宋凯", "ORG001", "DEPT-ORG001-SCM", "库存预警规则确认人", "供应链", "13800010015", "songk@shuopan.example", "Y"),
    ]
    cur.executemany(
        """
        insert into T_HR_Person
          (
            FPersonId, FPersonNo, FPersonName, FOrgId, FDeptId, FPosition,
            FRoleDomain, FMobile, FEmail, FIsActive
          )
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        on conflict(FPersonId) do update set
          FPersonNo = excluded.FPersonNo,
          FPersonName = excluded.FPersonName,
          FOrgId = excluded.FOrgId,
          FDeptId = excluded.FDeptId,
          FPosition = excluded.FPosition,
          FRoleDomain = excluded.FRoleDomain,
          FMobile = excluded.FMobile,
          FEmail = excluded.FEmail,
          FIsActive = excluded.FIsActive
        """,
        people,
    )

    responsibilities = [
        (
            "RSP-MAT042-DEFECTIVE",
            "MAT042",
            "ORG011",
            None,
            "超保质期半成品转不良品仓及跌价处理",
            "🔴 立即",
            "P-HR-001",
            "实物转正常仓到不良品仓；系统账务处理；跌价44%调至100%。",
            "NEAR_SLOW预警356天>>保质期217天，质量B已失效。",
            "2026-05-13",
            None,
            "Y",
        ),
        (
            "RSP-MAT002-RECHECK",
            "MAT002",
            "ORG011",
            None,
            "质量状态C复检并确认返修/降级/报废",
            "🔴 立即",
            "P-HR-004",
            "出具复检报告；决定返修或报废流程；释放资金1.2万元。",
            "质量C，超期占比10.37%最高，无订单消化。",
            "2026-05-13",
            None,
            "Y",
        ),
        (
            "RSP-MAT022-ISSUE-RETURN",
            "MAT022",
            "ORG001",
            None,
            "保质期剩余约80天安排生产领用或供应商退货",
            "🟡 本周内",
            "P-HR-007",
            "判断是否有领用需求；协调供应商退货；避免过期报废。",
            "SLOW预警200天，保质期280天，无采购无销售订单。",
            "2026-05-13",
            None,
            "Y",
        ),
        (
            "RSP-MAT062-WARN-REVIEW",
            "MAT062",
            "ORG001",
            None,
            "超保质期但预警等级LOW被低估需复核处理",
            "🟡 本周内",
            "P-HR-010",
            "复核预警等级是否应升级；确认实物状态。",
            "预警库龄273天>保质期218天，预警等级仅LOW。",
            "2026-05-13",
            None,
            "Y",
        ),
        (
            "RSP-ALL4-WARN-RULE",
            None,
            "ORG001",
            "全部4个物料",
            "预警分级规则修订：超保质期自动升级HIGH",
            "🟢 本月内",
            "P-HR-013",
            "系统规则配置：NEAR_SLOW/SLOW/EXCESS对应L1/L2/L3需关联保质期。",
            "预警等级与保质期偏差未关联。",
            "2026-05-13",
            None,
            "Y",
        ),
    ]
    cur.executemany(
        """
        insert into T_RSP_MaterialIssueOwner
          (
            FRespId, FMaterialId, FOrgId, FScopeName, FIssueType, FUrgency,
            FPrimaryPersonId, FActionPlan, FAnalysisBasis, FEffectiveFrom,
            FEffectiveTo, FIsActive
          )
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        on conflict(FRespId) do update set
          FMaterialId = excluded.FMaterialId,
          FOrgId = excluded.FOrgId,
          FScopeName = excluded.FScopeName,
          FIssueType = excluded.FIssueType,
          FUrgency = excluded.FUrgency,
          FPrimaryPersonId = excluded.FPrimaryPersonId,
          FActionPlan = excluded.FActionPlan,
          FAnalysisBasis = excluded.FAnalysisBasis,
          FEffectiveFrom = excluded.FEffectiveFrom,
          FEffectiveTo = excluded.FEffectiveTo,
          FIsActive = excluded.FIsActive
        """,
        responsibilities,
    )

    collaborators = [
        ("SUP-RSP-MAT042-001", "RSP-MAT042-DEFECTIVE", "P-HR-002", "财务(跌价核算)", "跌价比例从44%调至100%并完成账务处理。"),
        ("SUP-RSP-MAT042-002", "RSP-MAT042-DEFECTIVE", "P-HR-003", "质量(报废鉴定)", "确认质量失效结论及报废/降级意见。"),
        ("SUP-RSP-MAT002-001", "RSP-MAT002-RECHECK", "P-HR-005", "仓储(隔离)", "对质量C物料做隔离标识并冻结出库。"),
        ("SUP-RSP-MAT002-002", "RSP-MAT002-RECHECK", "P-HR-006", "供应链(返修渠道)", "确认供应商返修通道和周期。"),
        ("SUP-RSP-MAT022-001", "RSP-MAT022-ISSUE-RETURN", "P-HR-008", "采购(供应商沟通)", "确认退货窗口及供应商接受条件。"),
        ("SUP-RSP-MAT022-002", "RSP-MAT022-ISSUE-RETURN", "P-HR-009", "仓储(出库配合)", "配合生产领用或退货出库。"),
        ("SUP-RSP-MAT062-001", "RSP-MAT062-WARN-REVIEW", "P-HR-011", "质量(状态确认)", "复核质量状态是否仍可用。"),
        ("SUP-RSP-MAT062-002", "RSP-MAT062-WARN-REVIEW", "P-HR-012", "仓储(实物盘点)", "盘点实物数量、批次和库位。"),
        ("SUP-RSP-ALL4-001", "RSP-ALL4-WARN-RULE", "P-HR-014", "财务(规则口径)", "确认跌价、报废和预警分级的财务口径。"),
        ("SUP-RSP-ALL4-002", "RSP-ALL4-WARN-RULE", "P-HR-015", "供应链(规则确认)", "确认预警等级和业务处置动作映射。"),
    ]
    cur.executemany(
        """
        insert into T_RSP_IssueCollaborator
          (FSupportId, FRespId, FSupportPersonId, FSupportRole, FSupportAction)
        values (?, ?, ?, ?, ?)
        on conflict(FSupportId) do update set
          FRespId = excluded.FRespId,
          FSupportPersonId = excluded.FSupportPersonId,
          FSupportRole = excluded.FSupportRole,
          FSupportAction = excluded.FSupportAction
        """,
        collaborators,
    )

    cur.execute("drop view if exists V_Material_Issue_Responsibility")
    cur.execute(
        """
        create view V_Material_Issue_Responsibility as
        select
          rsp.FRespId,
          coalesce(mat.FNumber, rsp.FScopeName) as FMaterialScope,
          mat.FMaterialId,
          mat.FCategory as FMaterialCategory,
          mat.FShelfLife,
          mat.FQualityStatus,
          org.FOrgId,
          org.FOrgName,
          rsp.FUrgency,
          rsp.FIssueType,
          owner.FPersonName as FPrimaryOwnerName,
          owner.FPosition as FPrimaryOwnerPosition,
          owner_dept.FDeptName as FPrimaryOwnerDept,
          owner.FMobile as FPrimaryOwnerMobile,
          owner.FEmail as FPrimaryOwnerEmail,
          rsp.FActionPlan,
          rsp.FAnalysisBasis,
          group_concat(
            support.FSupportRole || ':' || support_person.FPersonName || '(' || support_dept.FDeptName || ')',
            '；'
          ) as FCollaborators
        from T_RSP_MaterialIssueOwner rsp
        left join T_BD_Material mat
          on mat.FMaterialId = rsp.FMaterialId
        join T_ORG_Organizations org
          on org.FOrgId = rsp.FOrgId
        join T_HR_Person owner
          on owner.FPersonId = rsp.FPrimaryPersonId
        join T_HR_Department owner_dept
          on owner_dept.FDeptId = owner.FDeptId
        left join T_RSP_IssueCollaborator support
          on support.FRespId = rsp.FRespId
        left join T_HR_Person support_person
          on support_person.FPersonId = support.FSupportPersonId
        left join T_HR_Department support_dept
          on support_dept.FDeptId = support_person.FDeptId
        where rsp.FIsActive = 'Y'
        group by
          rsp.FRespId,
          mat.FNumber,
          rsp.FScopeName,
          mat.FMaterialId,
          mat.FCategory,
          mat.FShelfLife,
          mat.FQualityStatus,
          org.FOrgId,
          org.FOrgName,
          rsp.FUrgency,
          rsp.FIssueType,
          owner.FPersonName,
          owner.FPosition,
          owner_dept.FDeptName,
          owner.FMobile,
          owner.FEmail,
          rsp.FActionPlan,
          rsp.FAnalysisBasis
        """
    )

    con.commit()

    for name in [
        "T_MFG_WorkOrder",
        "T_STK_Inventory",
        "T_PUR_POOrder",
        "T_PUR_POOrderEntry",
        "V_STK_OverdueReason",
        "T_HR_Department",
        "T_HR_Person",
        "T_RSP_MaterialIssueOwner",
        "T_RSP_IssueCollaborator",
        "V_Material_Issue_Responsibility",
    ]:
        count = cur.execute(f"select count(*) from {name}").fetchone()[0]
        print(f"{name}: {count}")

    con.close()


if __name__ == "__main__":
    main()
