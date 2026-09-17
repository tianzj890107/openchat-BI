#!/usr/bin/env python3
"""Build the deterministic evaluation fixtures for the analytics golden set.

Run:  .venv/bin/python dataset/evals/analytics/fixtures/build_fixtures.py

Design rules (see dataset/evals/analytics/README.md):

* Every table is tiny enough that a reviewer can recompute any expected value
  by hand from the row literals in this file.
* The databases are *inputs*, never outputs: the eval runner opens them
  read-only and never writes to ``dataset/conversations``, ``dataset/charts``
  or any other runtime directory.
* Historical ``dataset/databases/*.db`` files are never read, modified or
  replaced by this script.
* No customer data, no credentials, no secrets: supplier/customer names are
  synthetic placeholders.

The builder is deterministic: running it twice produces byte-identical
databases (fixed row order, fixed ``sqlite_sequence``-free schema, no
timestamps).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

FIXTURE_ROOT = Path(__file__).resolve().parent
SQLITE_DIR = FIXTURE_ROOT / "sqlite"
ONTOLOGY_DIR = FIXTURE_ROOT / "ontology"
REPORT_DIR = FIXTURE_ROOT / "reports"

# ---------------------------------------------------------------------------
# 采购 domain — procurement.db
# ---------------------------------------------------------------------------
SUPPLIERS = [
    # id, code, name, region, is_deleted
    (1, "SUP-A", "华东金属", "华东", 0),
    (2, "SUP-B", "华北电子", "华北", 0),
    (3, "SUP-C", "华南包装", "华南", 0),
    (4, "SUP-D", "华东化工", "华东", 0),
    (5, "SUP-E", "东北机械", "东北", 1),  # 已停用供应商
]

MATERIALS = [
    # id, code, name, category, unit
    (1, "MAT-A", "冷轧钢材", "原材料", "吨"),
    (2, "MAT-B", "控制芯片", "电子件", "千片"),
    (3, "MAT-C", "瓦楞纸箱", "包装", "百个"),
    (4, "MAT-D", "环氧树脂", "原材料", "吨"),
]

ORGS = [
    # id, code, name, business_unit
    (1, "ORG-1", "采购一部", "事业部A"),
    (2, "ORG-2", "采购二部", "事业部A"),
    (3, "ORG-3", "采购三部", "事业部B"),
]

# id, po_no, supplier_id, material_id, org_id, order_month, qty, unit_price, amount, status, is_deleted
PURCHASE_ORDERS = [
    (1, "PO-0001", 1, 1, 1, "2025-01", 10, 100, 1000, "已入库", 0),
    (2, "PO-0002", 1, 1, 1, "2025-01", 20, 100, 2000, "已入库", 0),
    (3, "PO-0003", 2, 2, 1, "2025-01", 5, 300, 1500, "已入库", 0),
    (4, "PO-0004", 3, 3, 2, "2025-01", 100, 2, 200, "已入库", 0),
    (5, "PO-0005", 1, 1, 2, "2025-02", 30, 100, 3000, "已入库", 0),
    (6, "PO-0006", 2, 2, 2, "2025-02", 8, 300, 2400, "已入库", 0),
    (7, "PO-0007", 4, 4, 3, "2025-02", 12, 50, 600, "已入库", 0),
    (8, "PO-0008", 3, 3, 3, "2025-02", 200, 2, 400, "已入库", 0),
    (9, "PO-0009", 1, 1, 1, "2025-03", 15, 110, 1650, "已入库", 0),
    (10, "PO-0010", 2, 2, 1, "2025-03", 6, 300, 1800, "已入库", 0),
    (11, "PO-0011", 4, 4, 2, "2025-03", 20, 50, 1000, "已入库", 0),
    (12, "PO-0012", 3, 3, 2, "2025-03", 150, 2, 300, "已入库", 0),
    (13, "PO-0013", 1, 1, 3, "2025-04", 25, 110, 2750, "已入库", 0),
    (14, "PO-0014", 2, 2, 3, "2025-04", 4, 320, 1280, "已入库", 0),
    (15, "PO-0015", 4, 4, 1, "2025-04", 18, 50, 900, "已入库", 0),
    (16, "PO-0016", 3, 3, 1, "2025-04", 120, 2, 240, "已入库", 0),
    (17, "PO-0017", 1, 1, 1, "2025-05", 10, 110, 1100, "已入库", 0),
    (18, "PO-0018", 2, 2, 1, "2025-05", 0, 300, 0, "已入库", 0),          # 数量为 0
    (19, "PO-0019", 4, 4, 2, "2025-05", -5, 50, -250, "已退货", 0),        # 负数（退货）
    (20, "PO-0020", 3, 3, 3, "2025-05", 80, 2, 160, "已入库", 0),
    (21, "PO-0021", 5, 1, 1, "2025-06", 10, 100, 1000, "已入库", 0),       # 供应商已停用
    (22, "PO-0022", 1, 1, 1, "2025-06", 5, 110, 550, "已入库", 0),
    (23, "PO-0023", 2, 2, 1, "2025-06", 3, 300, 900, "已入库", 0),
    (24, "PO-0024", 1, 1, 2, "2025-06", 7, 110, None, "待确认", 0),        # 金额 NULL
    (25, "PO-0022", 1, 1, 1, "2025-06", 5, 110, 550, "已入库", 0),         # 重复单号
    (26, "PO-0099", 1, 1, 1, "2025-06", 1, 110, 110, "已入库", 1),         # 逻辑删除
]

# ---------------------------------------------------------------------------
# 库存 domain — inventory.db
# ---------------------------------------------------------------------------
WAREHOUSES = [
    (1, "WH-01", "华东中心仓", "华东"),
    (2, "WH-02", "华北中心仓", "华北"),
]

# id, material_id, warehouse_id, snapshot_month, on_hand_qty, unit_cost, aging_days
INVENTORY_SNAPSHOTS = [
    (1, 1, 1, "2025-01", 120, 100, 30),
    (2, 1, 2, "2025-01", 80, 100, 95),
    (3, 2, 1, "2025-01", 40, 300, 12),
    (4, 3, 1, "2025-02", 300, 2, 200),
    (5, 1, 1, "2025-02", 100, 100, 45),
    (6, 2, 2, "2025-02", 25, 300, 160),
    # 2025-03 故意缺失（缺月场景）
    (7, 1, 1, "2025-04", 60, 100, 150),
    (8, 3, 2, "2025-04", 150, 2, 210),
    (9, 1, 2, "2025-04", None, 100, 20),     # 数量 NULL
    (10, 2, 1, "2025-05", -5, 300, 400),     # 负库存（异常）
    (11, 1, 1, "2025-05", 90, 100, 10),
]

# ---------------------------------------------------------------------------
# 销售 domain — sales.db
# ---------------------------------------------------------------------------
CUSTOMERS = [
    (1, "CUS-A", "华东装备", "华东"),
    (2, "CUS-B", "华北能源", "华北"),
    (3, "CUS-C", "华南制造", "华南"),
]

PRODUCTS = [
    # id, code, name, line, unit
    (1, "PRD-A", "标准机型", "主机", "台"),
    (2, "PRD-B", "高配机型", "主机", "台"),
    (3, "PRD-C", "备件包", "备件", "箱"),
]

# id, order_no, customer_id, product_id, order_month, qty, unit_price, amount_cny, amount_usd, currency, is_deleted
SALES_ORDERS = [
    (1, "SO-0001", 1, 1, "2025-01", 10, 5000, 50000, None, "CNY", 0),
    (2, "SO-0002", 1, 2, "2025-01", 4, 8000, 32000, None, "CNY", 0),
    (3, "SO-0003", 2, 1, "2025-01", 6, 5000, 30000, None, "CNY", 0),
    (4, "SO-0004", 3, 3, "2025-01", 20, 600, 12000, None, "CNY", 0),
    (5, "SO-0005", 1, 1, "2025-02", 12, 5000, 60000, None, "CNY", 0),
    (6, "SO-0006", 2, 2, "2025-02", 3, 8000, 24000, None, "CNY", 0),
    (7, "SO-0007", 3, 3, "2025-02", 30, 600, 18000, None, "CNY", 0),
    (8, "SO-0008", 1, 1, "2025-03", 9, 5000, 45000, None, "CNY", 0),
    (9, "SO-0009", 2, 1, "2025-03", 7, 5000, 35000, None, "CNY", 0),
    (10, "SO-0010", 3, 2, "2025-03", 2, 8000, 16000, None, "CNY", 0),
    (11, "SO-0011", 1, 3, "2025-03", 25, 600, 15000, None, "CNY", 0),
    (12, "SO-0012", 2, 1, "2025-04", 11, 5000, 55000, None, "CNY", 0),
    (13, "SO-0013", 3, 1, "2025-04", 5, 5000, 25000, None, "CNY", 0),
    (14, "SO-0014", 1, 2, "2025-04", 6, 8000, 48000, None, "CNY", 0),
    (15, "SO-0015", 1, 3, "2025-04", 40, 600, 24000, None, "CNY", 0),
    # 美元订单：币种不同，禁止与人民币直接相加/同轴对比
    (16, "SO-0016", 2, 2, "2025-04", 2, 8000, None, 16000, "USD", 0),
    (17, "SO-0017", 3, 3, "2025-05", 15, 600, 9000, None, "CNY", 0),
    (18, "SO-0018", 1, 1, "2025-05", 8, 5000, 40000, None, "CNY", 0),
    (19, "SO-0019", 2, 2, "2025-05", 0, 8000, 0, None, "CNY", 0),      # 数量为 0
    (20, "SO-0020", 1, 2, "2025-06", 5, 8000, 40000, None, "CNY", 0),
    (21, "SO-0021", 2, 1, "2025-06", 6, 5000, 30000, None, "CNY", 0),
    (22, "SO-0022", 3, 3, "2025-06", -4, 600, -2400, None, "CNY", 0),  # 退货负数
    (23, "SO-0099", 1, 1, "2025-06", 3, 5000, 15000, None, "CNY", 1),  # 逻辑删除
]

# ---------------------------------------------------------------------------
# 质量 / 制造 domain — quality.db
# ---------------------------------------------------------------------------
# id, batch_no, material_id, plant, inspect_month, inspected_qty, defect_qty, scrap_qty, downtime_minutes
QUALITY_BATCHES = [
    (1, "B-0001", 1, "P1", "2025-01", 1000, 20, 5, 60),
    (2, "B-0002", 2, "P1", "2025-01", 500, 40, 12, 180),
    (3, "B-0003", 3, "P2", "2025-01", 2000, 10, 0, 0),
    (4, "B-0004", 1, "P1", "2025-02", 800, 8, 2, 30),
    (5, "B-0005", 2, "P2", "2025-02", 400, 0, 0, 0),      # 缺陷为 0（分母正常）
    (6, "B-0006", 3, "P2", "2025-02", 0, 0, 0, 45),       # 检验量为 0 → 分母为零
    (7, "B-0007", 1, "P1", "2025-03", 1200, 15, 3, 90),
    (8, "B-0008", 2, "P1", "2025-03", 600, 9, 1, 20),
    (9, "B-0009", 3, "P2", "2025-04", 1500, 30, 10, 300),
    (10, "B-0010", 1, "P2", "2025-04", 900, None, 1, 15),  # 缺陷数 NULL
]


# ---------------------------------------------------------------------------
# 财务 domain — finance.db
# ---------------------------------------------------------------------------
FIN_ACCOUNTS = [
    # id, code, name, account_type
    (1, "6001", "主营业务收入", "收入"),
    (2, "6401", "主营业务成本", "成本"),
    (3, "6601", "销售费用", "费用"),
    (4, "6602", "管理费用", "费用"),
    (5, "1001", "库存现金", "资产"),
]

# id, voucher_no, account_id, org_id, period, debit, credit, currency, is_deleted
FIN_GL_ENTRIES = [
    (1, "GL-0001", 1, 1, "2025-01", None, 300000, "CNY", 0),
    (2, "GL-0002", 1, 2, "2025-01", None, 200000, "CNY", 0),
    (3, "GL-0003", 2, 1, "2025-01", 180000, None, "CNY", 0),
    (4, "GL-0004", 2, 2, "2025-01", 120000, None, "CNY", 0),
    (5, "GL-0005", 3, 1, "2025-01", 20000, None, "CNY", 0),
    (6, "GL-0006", 4, 1, "2025-01", 30000, None, "CNY", 0),
    (7, "GL-0007", 1, 1, "2025-02", None, 250000, "CNY", 0),
    (8, "GL-0008", 2, 1, "2025-02", 150000, None, "CNY", 0),
    (9, "GL-0009", 3, 1, "2025-02", 18000, None, "CNY", 0),
    (10, "GL-0010", 4, 2, "2025-02", 28000, None, "CNY", 0),
    (11, "GL-0011", 1, 1, "2025-03", None, 400000, "CNY", 0),
    (12, "GL-0012", 1, 3, "2025-03", None, 100000, "CNY", 0),
    (13, "GL-0013", 2, 1, "2025-03", 250000, None, "CNY", 0),
    (14, "GL-0014", 2, 3, "2025-03", 60000, None, "CNY", 0),
    (15, "GL-0015", 3, 1, "2025-03", 25000, None, "CNY", 0),
    (16, "GL-0016", 4, 1, "2025-03", 32000, None, "CNY", 0),
    (17, "GL-0017", 1, 2, "2025-04", None, 350000, "CNY", 0),
    (18, "GL-0018", 2, 2, "2025-04", 210000, None, "CNY", 0),
    (19, "GL-0019", 3, 2, "2025-04", 22000, None, "CNY", 0),
    (20, "GL-0020", 4, 1, "2025-04", 26000, None, "CNY", 0),
    (21, "GL-0021", 1, 1, "2025-05", None, 300000, "CNY", 0),
    (22, "GL-0022", 2, 1, "2025-05", 180000, None, "CNY", 0),
    (23, "GL-0023", 3, 1, "2025-05", 30000, None, "CNY", 0),
    (24, "GL-0024", 4, 2, "2025-05", 31000, None, "CNY", 0),
    (25, "GL-0025", 1, 1, "2025-06", None, 450000, "CNY", 0),
    (26, "GL-0026", 1, 1, "2025-06", None, -30000, "CNY", 0),   # 销售退回红冲（负数贷方）
    (27, "GL-0027", 1, 2, "2025-06", None, 30000, "USD", 0),    # 美元收入：禁止与人民币混算
    (28, "GL-0028", 2, 1, "2025-06", 270000, None, "CNY", 0),
    (29, "GL-0029", 3, 2, "2025-06", 27000, None, "CNY", 0),
    (30, "GL-0030", 4, 3, "2025-06", None, None, "CNY", 0),     # 金额为空的未记账凭证
    (31, "GL-0031", 5, 1, "2025-06", 50000, None, "CNY", 0),    # 资产类科目
    (32, "GL-0032", 1, 1, "2024-12", None, 100000, "CNY", 0),   # 期初：2025 年范围之外
    (33, "GL-0099", 2, 2, "2025-06", 999999, None, "CNY", 1),   # 逻辑删除
]

# id, account_id, org_id, period, budget_amount
FIN_BUDGETS = [
    (1, 1, 1, "2025-01", 480000),
    (2, 1, 3, "2025-02", 300000),
    (3, 1, 1, "2025-03", 450000),
    (4, 1, 2, "2025-04", 400000),
    (5, 1, 1, "2025-05", 350000),
    (6, 1, 1, "2025-06", 400000),
    (7, 2, 1, "2025-06", 250000),
    (8, 4, 3, "2025-06", 0),          # 零预算 -> 执行率分母为零
]

# ---------------------------------------------------------------------------
# 制造 domain — manufacturing.db
# ---------------------------------------------------------------------------
WORK_CENTERS = [
    # id, code, name, plant, capacity_per_day
    (1, "WC-01", "一号总装线", "P1", 200),
    (2, "WC-02", "二号总装线", "P1", 150),
    (3, "WC-03", "三号机加线", "P2", 300),
]

# id, order_no, material_id, work_center_id, period, planned_qty, actual_qty,
# scrap_qty, planned_minutes, downtime_minutes, is_deleted
PRODUCTION_ORDERS = [
    (1, "MO-0001", 1, 1, "2025-01", 100, 95, 3, 12000, 600, 0),
    (2, "MO-0002", 2, 2, "2025-01", 80, 80, 1, 9600, 0, 0),
    (3, "MO-0003", 3, 3, "2025-01", 150, 140, 5, 18000, 1200, 0),
    (4, "MO-0004", 1, 1, "2025-02", 110, 120, 2, 13200, 300, 0),
    (5, "MO-0005", 2, 3, "2025-02", 150, 150, 0, 18000, 0, 0),
    (6, "MO-0006", 1, 1, "2025-03", 100, 0, 0, 12000, 12000, 0),   # 全线停机（断点）
    (7, "MO-0007", 1, 1, "2025-04", 120, 112, 4, 14400, 480, 0),
    (8, "MO-0008", 2, 2, "2025-04", 90, 85, 2, 10800, 540, 0),
    (9, "MO-0009", 3, 3, "2025-04", 160, 155, 6, 19200, 960, 0),
    (10, "MO-0010", 1, 1, "2025-05", 130, 125, 3, 15600, 780, 0),
    (11, "MO-0011", 2, 3, "2025-05", 170, 160, 4, 20400, 900, 0),
    (12, "MO-0012", 1, 1, "2025-06", 120, 118, 3, 14400, 200, 0),
    (13, "MO-0013", 2, 2, "2025-06", 140, None, 0, 16800, 1000, 0),  # 未报工（实际为空）
    (14, "MO-0014", 3, 3, "2025-06", 150, 148, -2, 18000, 360, 0),   # 返工冲销（负数报废）
    (15, "MO-0099", 1, 1, "2025-06", 100, 100, 10, 12000, 0, 1),     # 逻辑删除
]


def _reset_db(path: Path) -> sqlite3.Connection:
    if path.exists():
        path.unlink()
    return sqlite3.connect(str(path))


def build_procurement() -> None:
    conn = _reset_db(SQLITE_DIR / "procurement.db")
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE dim_supplier(supplier_id INTEGER PRIMARY KEY, supplier_code TEXT NOT NULL, "
        "supplier_name TEXT NOT NULL, region TEXT NOT NULL, is_deleted INTEGER NOT NULL DEFAULT 0)"
    )
    cur.execute(
        "CREATE TABLE dim_material(material_id INTEGER PRIMARY KEY, material_code TEXT NOT NULL, "
        "material_name TEXT NOT NULL, category TEXT NOT NULL, unit TEXT NOT NULL)"
    )
    cur.execute(
        "CREATE TABLE dim_org(org_id INTEGER PRIMARY KEY, org_code TEXT NOT NULL, "
        "org_name TEXT NOT NULL, business_unit TEXT NOT NULL)"
    )
    cur.execute(
        "CREATE TABLE fact_purchase_order(po_id INTEGER PRIMARY KEY, po_no TEXT NOT NULL, "
        "supplier_id INTEGER NOT NULL, material_id INTEGER NOT NULL, org_id INTEGER NOT NULL, "
        "order_month TEXT NOT NULL, qty REAL, unit_price REAL, amount REAL, status TEXT, "
        "is_deleted INTEGER NOT NULL DEFAULT 0)"
    )
    cur.executemany("INSERT INTO dim_supplier VALUES(?,?,?,?,?)", SUPPLIERS)
    cur.executemany("INSERT INTO dim_material VALUES(?,?,?,?,?)", MATERIALS)
    cur.executemany("INSERT INTO dim_org VALUES(?,?,?,?)", ORGS)
    cur.executemany("INSERT INTO fact_purchase_order VALUES(?,?,?,?,?,?,?,?,?,?,?)", PURCHASE_ORDERS)
    conn.commit()
    conn.close()


def build_inventory() -> None:
    conn = _reset_db(SQLITE_DIR / "inventory.db")
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE dim_warehouse(warehouse_id INTEGER PRIMARY KEY, warehouse_code TEXT NOT NULL, "
        "warehouse_name TEXT NOT NULL, region TEXT NOT NULL)"
    )
    cur.execute(
        "CREATE TABLE dim_material(material_id INTEGER PRIMARY KEY, material_code TEXT NOT NULL, "
        "material_name TEXT NOT NULL, category TEXT NOT NULL, unit TEXT NOT NULL)"
    )
    cur.execute(
        "CREATE TABLE fact_inventory_snapshot(snapshot_id INTEGER PRIMARY KEY, material_id INTEGER NOT NULL, "
        "warehouse_id INTEGER NOT NULL, snapshot_month TEXT NOT NULL, on_hand_qty REAL, "
        "unit_cost REAL, aging_days INTEGER)"
    )
    cur.executemany("INSERT INTO dim_warehouse VALUES(?,?,?,?)", WAREHOUSES)
    cur.executemany("INSERT INTO dim_material VALUES(?,?,?,?,?)", MATERIALS)
    cur.executemany("INSERT INTO fact_inventory_snapshot VALUES(?,?,?,?,?,?,?)", INVENTORY_SNAPSHOTS)
    conn.commit()
    conn.close()


def build_sales() -> None:
    conn = _reset_db(SQLITE_DIR / "sales.db")
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE dim_customer(customer_id INTEGER PRIMARY KEY, customer_code TEXT NOT NULL, "
        "customer_name TEXT NOT NULL, region TEXT NOT NULL)"
    )
    cur.execute(
        "CREATE TABLE dim_product(product_id INTEGER PRIMARY KEY, product_code TEXT NOT NULL, "
        "product_name TEXT NOT NULL, product_line TEXT NOT NULL, unit TEXT NOT NULL)"
    )
    cur.execute(
        "CREATE TABLE fact_sales(order_id INTEGER PRIMARY KEY, order_no TEXT NOT NULL, "
        "customer_id INTEGER NOT NULL, product_id INTEGER NOT NULL, order_month TEXT NOT NULL, "
        "qty REAL, unit_price REAL, amount_cny REAL, amount_usd REAL, currency TEXT NOT NULL, "
        "is_deleted INTEGER NOT NULL DEFAULT 0)"
    )
    cur.executemany("INSERT INTO dim_customer VALUES(?,?,?,?)", CUSTOMERS)
    cur.executemany("INSERT INTO dim_product VALUES(?,?,?,?,?)", PRODUCTS)
    cur.executemany("INSERT INTO fact_sales VALUES(?,?,?,?,?,?,?,?,?,?,?)", SALES_ORDERS)
    conn.commit()
    conn.close()


def build_quality() -> None:
    conn = _reset_db(SQLITE_DIR / "quality.db")
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE dim_material(material_id INTEGER PRIMARY KEY, material_code TEXT NOT NULL, "
        "material_name TEXT NOT NULL, category TEXT NOT NULL, unit TEXT NOT NULL)"
    )
    cur.execute(
        "CREATE TABLE fact_quality_batch(batch_id INTEGER PRIMARY KEY, batch_no TEXT NOT NULL, "
        "material_id INTEGER NOT NULL, plant TEXT NOT NULL, inspect_month TEXT NOT NULL, "
        "inspected_qty REAL, defect_qty REAL, scrap_qty REAL, downtime_minutes REAL)"
    )
    cur.execute("CREATE TABLE fact_empty_probe(probe_id INTEGER PRIMARY KEY, label TEXT NOT NULL)")
    cur.executemany("INSERT INTO dim_material VALUES(?,?,?,?,?)", MATERIALS)
    cur.executemany("INSERT INTO fact_quality_batch VALUES(?,?,?,?,?,?,?,?,?)", QUALITY_BATCHES)
    conn.commit()
    conn.close()


def build_finance() -> None:
    conn = _reset_db(SQLITE_DIR / "finance.db")
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE dim_account(account_id INTEGER PRIMARY KEY, account_code TEXT NOT NULL, "
        "account_name TEXT NOT NULL, account_type TEXT NOT NULL)"
    )
    cur.execute(
        "CREATE TABLE dim_org(org_id INTEGER PRIMARY KEY, org_code TEXT NOT NULL, "
        "org_name TEXT NOT NULL, business_unit TEXT NOT NULL)"
    )
    cur.execute(
        "CREATE TABLE fact_gl_entry(entry_id INTEGER PRIMARY KEY, voucher_no TEXT NOT NULL, "
        "account_id INTEGER NOT NULL, org_id INTEGER NOT NULL, period TEXT NOT NULL, "
        "debit REAL, credit REAL, currency TEXT NOT NULL, is_deleted INTEGER NOT NULL DEFAULT 0)"
    )
    cur.execute(
        "CREATE TABLE fact_budget(budget_id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL, "
        "org_id INTEGER NOT NULL, period TEXT NOT NULL, budget_amount REAL NOT NULL)"
    )
    cur.executemany("INSERT INTO dim_account VALUES(?,?,?,?)", FIN_ACCOUNTS)
    cur.executemany("INSERT INTO dim_org VALUES(?,?,?,?)", ORGS)
    cur.executemany("INSERT INTO fact_gl_entry VALUES(?,?,?,?,?,?,?,?,?)", FIN_GL_ENTRIES)
    cur.executemany("INSERT INTO fact_budget VALUES(?,?,?,?,?)", FIN_BUDGETS)
    conn.commit()
    conn.close()


def build_manufacturing() -> None:
    conn = _reset_db(SQLITE_DIR / "manufacturing.db")
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE dim_work_center(work_center_id INTEGER PRIMARY KEY, work_center_code TEXT NOT NULL, "
        "work_center_name TEXT NOT NULL, plant TEXT NOT NULL, capacity_per_day REAL NOT NULL)"
    )
    cur.execute(
        "CREATE TABLE dim_material(material_id INTEGER PRIMARY KEY, material_code TEXT NOT NULL, "
        "material_name TEXT NOT NULL, category TEXT NOT NULL, unit TEXT NOT NULL)"
    )
    cur.execute(
        "CREATE TABLE fact_production_order(order_id INTEGER PRIMARY KEY, order_no TEXT NOT NULL, "
        "material_id INTEGER NOT NULL, work_center_id INTEGER NOT NULL, period TEXT NOT NULL, "
        "planned_qty REAL, actual_qty REAL, scrap_qty REAL, planned_minutes REAL, "
        "downtime_minutes REAL, is_deleted INTEGER NOT NULL DEFAULT 0)"
    )
    cur.execute("CREATE TABLE fact_empty_probe(probe_id INTEGER PRIMARY KEY, label TEXT NOT NULL)")
    cur.executemany("INSERT INTO dim_work_center VALUES(?,?,?,?,?)", WORK_CENTERS)
    cur.executemany("INSERT INTO dim_material VALUES(?,?,?,?,?)", MATERIALS)
    cur.executemany("INSERT INTO fact_production_order VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    PRODUCTION_ORDERS)
    conn.commit()
    conn.close()


def build_ontology() -> None:
    """Write the ontology workbook used by the retrieval cases."""
    from openpyxl import Workbook

    wb = Workbook()
    wb.remove(wb.active)

    ws = wb.create_sheet("术语")
    ws.append(["术语编码", "术语名称", "别名", "术语英文名", "术语定义", "术语分类", "解释部门"])
    ws.append(["TM-001", "采购订单", "采购单;PO", "PurchaseOrder", "向供应商下达的采购凭证", "业务单据", "采购部"])
    ws.append(["TM-002", "采购金额", "采购额;采购总额", "PurchaseAmount", "采购订单含税金额合计", "指标口径", "财务部"])
    ws.append(["TM-003", "供应商", "厂商;供方", "Supplier", "提供物料或服务的外部组织", "主数据", "采购部"])
    ws.append(["TM-004", "库存数量", "在库数量", "InventoryQty", "某时点仓库中可用物料数量", "指标口径", "仓储部"])
    ws.append(["TM-005", "退货", "退回;红冲", "Return", "已入库后反向退回供应商的业务", "业务动作", "采购部"])
    ws.append(["TM-006", "毛利率", "毛利", "GrossMargin", "(收入-成本)/收入", "指标口径", "财务部"])
    ws.append(["TM-007", "产量达成率", "达成率", "AchievementRate", "实际产量/计划产量", "指标口径", "制造部"])

    ws = wb.create_sheet("业务对象")
    ws.append(["业务对象编号", "业务对象名称", "业务对象英文名", "业务对象定义", "业务对象类型", "关联物理表"])
    ws.append(["BO-001", "采购订单", "PurchaseOrder", "采购业务主单据", "单据", "fact_purchase_order"])
    ws.append(["BO-002", "供应商", "Supplier", "供应商主数据", "主数据", "dim_supplier"])
    ws.append(["BO-003", "物料", "Material", "物料主数据", "主数据", "dim_material"])
    ws.append(["BO-004", "库存快照", "InventorySnapshot", "库存时点快照", "事实", "fact_inventory_snapshot"])
    ws.append(["BO-005", "销售订单", "SalesOrder", "销售业务主单据", "单据", "fact_sales"])
    ws.append(["BO-006", "总账凭证", "JournalEntry", "会计核算凭证", "单据", "fact_gl_entry"])
    ws.append(["BO-007", "生产订单", "ProductionOrder", "生产工单主单据", "单据", "fact_production_order"])

    ws = wb.create_sheet("逻辑实体")
    ws.append(["业务对象编号", "业务对象名称", "逻辑实体编号", "逻辑实体名称", "英文名", "逻辑实体定义", "对应物理表"])
    ws.append(["BO-001", "采购订单", "LE-001", "采购订单头", "PurchaseOrderHeader", "采购订单主表", "fact_purchase_order"])
    ws.append(["BO-001", "采购订单", "LE-002", "采购订单行", "PurchaseOrderLine", "采购订单行项目", "fact_purchase_order"])
    ws.append(["BO-002", "供应商", "LE-003", "供应商主数据", "SupplierMaster", "供应商基础信息", "dim_supplier"])
    ws.append(["BO-003", "物料", "LE-004", "物料主数据", "MaterialMaster", "物料基础信息", "dim_material"])
    ws.append(["BO-004", "库存快照", "LE-005", "库存快照事实", "InventorySnapshotFact", "库存时点事实", "fact_inventory_snapshot"])
    ws.append(["BO-005", "销售订单", "LE-006", "销售订单头", "SalesOrderHeader", "销售订单主表", "fact_sales"])
    ws.append(["BO-006", "总账凭证", "LE-007", "总账分录", "GlEntry", "总账凭证明细", "fact_gl_entry"])
    ws.append(["BO-007", "生产订单", "LE-008", "生产订单头", "ProductionOrderHeader", "生产订单主表", "fact_production_order"])
    ws.append(["BO-007", "生产订单", "LE-009", "产线主数据", "WorkCenterMaster", "生产线基础信息", "dim_work_center"])

    ws = wb.create_sheet("业务属性")
    ws.append(["逻辑实体编号", "逻辑实体名称", "业务属性编号", "业务属性名称", "业务属性英文名", "业务属性定义", "数据类型", "是否主键"])
    ws.append(["LE-001", "采购订单头", "AT-001", "采购订单号", "po_no", "采购订单唯一编号", "字符串", "是"])
    ws.append(["LE-001", "采购订单头", "AT-002", "采购金额", "amount", "采购订单金额", "数值", "否"])
    ws.append(["LE-001", "采购订单头", "AT-003", "下单月份", "order_month", "采购下单所属月份", "字符串", "否"])
    ws.append(["LE-003", "供应商主数据", "AT-004", "供应商编码", "supplier_code", "供应商唯一编码", "字符串", "是"])
    ws.append(["LE-003", "供应商主数据", "AT-005", "供应商所在区域", "region", "供应商所属大区", "字符串", "否"])
    ws.append(["LE-004", "物料主数据", "AT-006", "物料分类", "category", "物料所属分类", "字符串", "否"])
    ws.append(["LE-005", "库存快照事实", "AT-007", "在库数量", "on_hand_qty", "时点库存数量", "数值", "否"])
    ws.append(["LE-005", "库存快照事实", "AT-008", "库龄天数", "aging_days", "库存已存放天数", "数值", "否"])
    ws.append(["LE-007", "总账分录", "AT-009", "会计期间", "period", "凭证所属会计期间", "字符串", "否"])
    ws.append(["LE-007", "总账分录", "AT-010", "借方发生额", "debit", "科目借方金额", "数值", "否"])
    ws.append(["LE-008", "生产订单头", "AT-011", "实际产量", "actual_qty", "工单实际产出数量", "数值", "否"])

    ws = wb.create_sheet("实体关系")
    ws.append(["关系编号", "源实体编号", "源实体名称", "目标实体编号", "目标实体名称", "关系类型", "关系描述", "外键字段", "关系中文名称"])
    ws.append(["ER-001", "LE-001", "采购订单头", "LE-003", "供应商主数据", "多对一", "采购订单属于供应商", "supplier_id", "订单-供应商"])
    ws.append(["ER-002", "LE-001", "采购订单头", "LE-004", "物料主数据", "多对一", "采购订单引用物料", "material_id", "订单-物料"])
    ws.append(["ER-003", "LE-005", "库存快照事实", "LE-004", "物料主数据", "多对一", "库存快照按物料统计", "material_id", "库存-物料"])
    ws.append(["ER-004", "LE-008", "生产订单头", "LE-009", "产线主数据", "多对一", "生产订单在产线上执行", "work_center_id", "工单-产线"])
    ws.append(["ER-005", "LE-007", "总账分录", "LE-004", "物料主数据", "多对一", "总账分录按成本对象归集", "material_id", "分录-成本对象"])

    ws = wb.create_sheet("指标")
    ws.append(["指标编码", "指标名称", "指标别名", "指标英文名", "指标类型", "指标定义", "计算公式(业务)", "统计口径",
               "计算公式(技术)", "对应表名", "业务对象", "聚合列", "聚合类型", "筛选条件", "维度列"])
    ws.append(["MT-001", "采购金额", "采购额", "PurchaseAmount", "原子指标", "采购订单金额合计",
               "Σ采购订单金额", "按订单月份、供应商、事业部统计，排除逻辑删除", "SUM(amount)",
               "fact_purchase_order", "采购订单", "amount", "SUM", "is_deleted = 0", "order_month,supplier_id,org_id"])
    ws.append(["MT-002", "采购数量", "采购量", "PurchaseQty", "原子指标", "采购数量合计",
               "Σ采购数量", "按订单月份、物料统计，排除逻辑删除", "SUM(qty)",
               "fact_purchase_order", "采购订单", "qty", "SUM", "is_deleted = 0", "order_month,material_id"])
    ws.append(["MT-003", "供应商采购占比", "采购占比", "SupplierShare", "派生指标", "某供应商采购金额/总采购金额",
               "供应商采购金额 ÷ 采购总金额", "分母为 0 时不计算", "SUM(amount)/SUM(amount) OVER ()",
               "fact_purchase_order", "采购订单", "amount", "SUM", "is_deleted = 0", "supplier_id"])
    ws.append(["MT-004", "库存数量", "在库数量", "InventoryQty", "原子指标", "时点库存数量合计",
               "Σ在库数量", "按快照月份、仓库统计，排除空值", "SUM(on_hand_qty)",
               "fact_inventory_snapshot", "库存快照", "on_hand_qty", "SUM", "on_hand_qty IS NOT NULL", "snapshot_month,warehouse_id"])
    ws.append(["MT-005", "销售金额", "销售额", "SalesAmount", "原子指标", "销售订单金额合计（人民币）",
               "Σ销售金额", "仅统计人民币订单，排除逻辑删除", "SUM(amount_cny)",
               "fact_sales", "销售订单", "amount_cny", "SUM", "is_deleted = 0 AND currency = 'CNY'", "order_month,customer_id"])
    ws.append(["MT-006", "缺陷率", "不良率", "DefectRate", "派生指标", "缺陷数量/检验数量",
               "缺陷数量 ÷ 检验数量", "分母为 0 时不计算，返回空值而不是 0", "SUM(defect_qty)/SUM(inspected_qty)",
               "fact_quality_batch", "质量批次", "defect_qty", "SUM", "inspected_qty > 0", "inspect_month,plant"])
    ws.append(["MT-007", "毛利率", "毛利", "GrossMargin", "派生指标", "毛利占收入比例",
               "(收入-成本) ÷ 收入", "仅统计人民币分录，排除逻辑删除", "(SUM(credit)-SUM(debit))/SUM(credit)",
               "fact_gl_entry", "总账凭证", "credit", "RATIO",
               "is_deleted = 0 AND currency = 'CNY' AND account_type IN ('收入','成本')", "period,org_id"])
    ws.append(["MT-008", "预算执行率", "预算完成率", "BudgetExecutionRate", "派生指标", "实际收入/收入预算",
               "实际收入 ÷ 预算金额", "预算为 0 时不计算，返回空值", "SUM(actual)/SUM(budget_amount)",
               "fact_budget", "预算", "budget_amount", "RATIO", "account_id = 1", "period,org_id"])
    ws.append(["MT-009", "产量达成率", "达成率", "AchievementRate", "派生指标", "实际产量/计划产量",
               "实际产量 ÷ 计划产量", "未报工（实际产量为空）的行必须排除", "SUM(actual_qty)/SUM(planned_qty)",
               "fact_production_order", "生产订单", "actual_qty", "RATIO",
               "is_deleted = 0 AND actual_qty IS NOT NULL", "period,work_center_id"])
    ws.append(["MT-010", "报废率", "报废占比", "ScrapRate", "派生指标", "报废数量/实际产量",
               "报废数量 ÷ 实际产量", "含返工冲销负数，排除逻辑删除", "SUM(scrap_qty)/SUM(actual_qty)",
               "fact_production_order", "生产订单", "scrap_qty", "RATIO", "is_deleted = 0", "period,work_center_id"])
    ws.append(["MT-011", "设备时间开动率", "开动率", "AvailabilityRate", "派生指标",
               "1 - 停机时长/计划工时", "1 - 停机时长 ÷ 计划工时", "计划工时为 0 时不计算",
               "1-SUM(downtime_minutes)/SUM(planned_minutes)", "fact_production_order", "生产订单",
               "downtime_minutes", "RATIO", "is_deleted = 0", "period,work_center_id"])

    ws = wb.create_sheet("活动")
    ws.append(["活动编码", "活动名称", "活动定义", "所属业务对象"])
    ws.append(["AC-001", "采购下单", "创建采购订单", "采购订单"])
    ws.append(["AC-002", "采购退货", "已入库物料退回供应商", "采购订单"])
    ws.append(["AC-003", "质量检验", "对来料批次执行检验", "质量批次"])

    ws = wb.create_sheet("业务规则")
    # Column layout is driven by OntologyStore._load_rules: 规则编号 / 规则名称
    # (the rule text) / 所属活动编号 / 活动名称 / 规则分类 / 解释部门.
    ws.append(["规则编号", "规则名称", "所属活动编号", "活动名称", "规则分类", "解释部门"])
    ws.append(["BR-001", "所有采购指标必须排除 is_deleted = 1 的记录",
               "AC-001", "采购下单", "数据来源", "采购部"])
    ws.append(["BR-002", "人民币与美元金额不得直接相加或同轴比较",
               "AC-001", "采购下单", "校验", "财务部"])
    ws.append(["BR-003", "比率类指标分母为 0 时必须返回空值，不得写 0 或编造",
               "AC-003", "质量检验", "校验", "质量部"])
    ws.append(["BR-004", "会计期间必须显式声明，不得把自然月与会计期间混用",
               "AC-001", "采购下单", "数据来源", "财务部"])
    ws.append(["BR-005", "计划产量为 0 或未报工时，达成率不得计算，需说明数据缺失",
               "AC-003", "质量检验", "校验", "制造部"])

    ws = wb.create_sheet("维度")
    ws.append(["维度编码", "维度名称", "维度别名", "维度英文名", "维度定义", "维度层级"])
    ws.append(["DIM-1", "订单月份维度", "月份;时间", "OrderMonth", "订单所属自然月", "时间"])
    ws.append(["DIM-2", "供应商维度", "供应商", "Supplier", "供应商主数据", "管理单元"])
    ws.append(["DIM-3", "事业部维度", "事业部", "BusinessUnit", "组织事业部", "管理单元"])
    ws.append(["DIM-4", "物料维度", "物料", "Material", "物料主数据", "品类"])
    ws.append(["DIM-5", "客户维度", "客户", "Customer", "客户主数据", "管理单元"])
    ws.append(["DIM-6", "产线维度", "产线;工作中心", "WorkCenter", "生产线主数据", "管理单元"])
    ws.append(["DIM-7", "会计期间维度", "会计期间;账期", "AccountingPeriod", "会计期间口径", "时间"])

    # 指标维度矩阵 is a WIDE sheet: cols 0/1 are the metric code/name and every
    # following column is one dimension name with a TRUE/FALSE applicability
    # cell (OntologyStore._load_dim_matrix).
    ws = wb.create_sheet("指标维度矩阵")
    ws.append(["指标编码", "指标名称", "订单月份", "供应商", "事业部", "物料", "客户", "产线", "会计期间"])
    ws.append(["MT-001", "采购金额", "TRUE", "TRUE", "TRUE", "FALSE", "FALSE", "FALSE", "TRUE"])
    ws.append(["MT-002", "采购数量", "TRUE", "FALSE", "FALSE", "TRUE", "FALSE", "FALSE", "TRUE"])
    ws.append(["MT-003", "供应商采购占比", "FALSE", "TRUE", "FALSE", "FALSE", "FALSE", "FALSE", "FALSE"])
    ws.append(["MT-004", "库存数量", "TRUE", "FALSE", "FALSE", "TRUE", "FALSE", "FALSE", "TRUE"])
    ws.append(["MT-005", "销售金额", "TRUE", "FALSE", "FALSE", "FALSE", "TRUE", "FALSE", "TRUE"])
    ws.append(["MT-006", "缺陷率", "TRUE", "FALSE", "FALSE", "TRUE", "FALSE", "FALSE", "TRUE"])
    ws.append(["MT-007", "毛利率", "TRUE", "FALSE", "TRUE", "FALSE", "FALSE", "FALSE", "TRUE"])
    ws.append(["MT-008", "预算执行率", "TRUE", "FALSE", "TRUE", "FALSE", "FALSE", "FALSE", "TRUE"])
    ws.append(["MT-009", "产量达成率", "TRUE", "FALSE", "FALSE", "TRUE", "FALSE", "TRUE", "TRUE"])
    ws.append(["MT-010", "报废率", "TRUE", "FALSE", "FALSE", "TRUE", "FALSE", "TRUE", "TRUE"])
    ws.append(["MT-011", "设备时间开动率", "TRUE", "FALSE", "FALSE", "FALSE", "FALSE", "TRUE", "TRUE"])

    wb.save(str(ONTOLOGY_DIR / "analytics_golden_ontology.xlsx"))
    wb.close()


def build_reports() -> None:
    samples = {
        "purchase_summary_2025Q1.txt": (
            "2025 年一季度采购摘要（测试样本）\n"
            "华东金属 采购金额 3650 元；华北电子 采购金额 5700 元；\n"
            "华南包装 采购金额 900 元；华东化工 采购金额 1600 元。\n"
            "合计 11850 元。\n"
        ),
        "quality_note.txt": (
            "质量周报（测试样本）\n"
            "2025-02 P2 工厂 缺陷率 0%；2025-02 P2 工厂 B-0006 检验量为 0，缺陷率不可计算。\n"
        ),
    }
    for name, body in samples.items():
        (REPORT_DIR / name).write_text(body, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build deterministic analytics eval fixtures")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    build_procurement()
    build_inventory()
    build_sales()
    build_quality()
    build_finance()
    build_manufacturing()
    build_ontology()
    build_reports()

    summary = {
        "sqlite": sorted(p.name for p in SQLITE_DIR.glob("*.db")),
        "ontology": sorted(p.name for p in ONTOLOGY_DIR.glob("*.xlsx")),
        "reports": sorted(p.name for p in REPORT_DIR.glob("*.txt")),
    }
    if not args.quiet:
        print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
