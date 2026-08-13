import sqlite3
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bi_agent.paths import DATABASES_DIR, SPREADSHEETS_DIR


REPORT_XLSX = PROJECT_ROOT / SPREADSHEETS_DIR / "超聚变报表.xlsx"
DATA_XLSX = PROJECT_ROOT / SPREADSHEETS_DIR / "超聚变数据.xlsx"
DB_PATH = PROJECT_ROOT / DATABASES_DIR / "HyperFusion.db"


TABLE_SPECS = {
    "T_HF_PL_Detail": {
        "file": REPORT_XLSX,
        "sheet": "1.《损益明细表》",
        "columns": {
            "会计期": "FPeriod",
            "销售合同号": "FSalesContractNo",
            "商务申请编号": "FBusinessApplyNo",
            "国内/国际": "FDomesticInternational",
            "经营单元LV1": "FOperatingUnitLv1",
            "行业": "FIndustry",
            "报表项名称一级": "FReportItemLv1",
            "报表项名称二级": "FReportItemLv2",
            "报表项名称三级": "FReportItemLv3",
            "报表项名称四级": "FReportItemLv4",
            "报告金额CNY": "FAmountCny",
            "报告金额USD": "FAmountUsd",
            "产业": "FIndustrySegment",
            "子产业": "FSubIndustrySegment",
            "销售类型": "FSalesType",
        },
        "numeric": ["FAmountCny", "FAmountUsd"],
    },
    "T_HF_RevenueForecast": {
        "file": REPORT_XLSX,
        "sheet": "2《收入预测清单》",
        "columns": {
            "机会点编码": "FOpportunityNo",
            "机会点名称": "FOpportunityName",
            "是否预测": "FIsForecast",
            "预测类型": "FForecastType",
            "行管": "FIndustryManagement",
            "地区": "FRegion",
            "预测月份": "FForecastMonthRaw",
            "收入": "FRevenue",
            "产业": "FIndustrySegment",
        },
        "numeric": ["FForecastMonthRaw", "FRevenue"],
    },
    "T_HF_DemoData": {
        "file": DATA_XLSX,
        "sheet": "演示数据",
        "columns": {
            "会计期": "FPeriod",
            "公司段": "FCompanySegment",
            "销售合同号": "FSalesContractNo",
            "商务申请编号": "FBusinessApplyNo",
            "国内/国际": "FDomesticInternational",
            "区域段": "FRegionSegment",
            "地区部": "FRegionDept",
            "代表处": "FRepOffice",
            "经营单元LV1": "FOperatingUnitLv1",
            "经营单元LV2": "FOperatingUnitLv2",
            "国家名称": "FCountryName",
            "行业": "FIndustry",
            "合同名称": "FContractName",
            "一级部门名称": "FDeptLv1",
            "报表项名称一级": "FReportItemLv1",
            "报表项名称二级": "FReportItemLv2",
            "报表项名称三级": "FReportItemLv3",
            "报表项名称四级": "FReportItemLv4",
            "会计科目": "FAccountCode",
            "科目名称": "FAccountName",
            "交易币币种": "FTransCurrency",
            "交易币金额": "FTransAmount",
            "报告金额CNY": "FAmountCny",
            "报告金额USD": "FAmountUsd",
            "销售员": "FSalesPerson",
            "机会点编码": "FOpportunityNo",
            "产业": "FIndustrySegment",
            "客户": "FCustomerName",
        },
        "numeric": ["FTransAmount", "FAmountCny", "FAmountUsd"],
    },
    "T_HF_RefreshData": {
        "file": DATA_XLSX,
        "sheet": "12、刷新数据",
        "columns": {
            "会计期": "FPeriod",
            "公司段": "FCompanySegment",
            "销售合同号": "FSalesContractNo",
            "商务申请编号": "FBusinessApplyNo",
            "国内/国际": "FDomesticInternational",
            "区域段": "FRegionSegment",
            "地区部": "FRegionDept",
            "代表处": "FRepOffice",
            "经营单元LV1": "FOperatingUnitLv1",
            "经营单元LV2": "FOperatingUnitLv2",
            "国家名称": "FCountryName",
            "行业": "FIndustry",
            "合同名称": "FContractName",
            "一级部门名称": "FDeptLv1",
            "报表项名称一级": "FReportItemLv1",
            "报表项名称二级": "FReportItemLv2",
            "报表项名称三级": "FReportItemLv3",
            "报表项名称四级": "FReportItemLv4",
            "会计科目": "FAccountCode",
            "科目名称": "FAccountName",
            "交易币币种": "FTransCurrency",
            "交易币金额": "FTransAmount",
            "报告金额CNY": "FAmountCny",
            "报告金额USD": "FAmountUsd",
            "销售员": "FSalesPerson",
            "机会点编码": "FOpportunityNo",
            "产业": "FIndustrySegment",
            "客户": "FCustomerName",
        },
        "numeric": ["FTransAmount", "FAmountCny", "FAmountUsd"],
    },
}


CREATE_SQL = {
    "T_HF_PL_Detail": """
        CREATE TABLE T_HF_PL_Detail (
            FId INTEGER PRIMARY KEY AUTOINCREMENT,
            FPeriod TEXT,
            FSalesContractNo TEXT,
            FBusinessApplyNo TEXT,
            FDomesticInternational TEXT,
            FOperatingUnitLv1 TEXT,
            FIndustry TEXT,
            FReportItemLv1 TEXT,
            FReportItemLv2 TEXT,
            FReportItemLv3 TEXT,
            FReportItemLv4 TEXT,
            FAmountCny REAL,
            FAmountUsd REAL,
            FIndustrySegment TEXT,
            FSubIndustrySegment TEXT,
            FSalesType TEXT,
            FSourceWorkbook TEXT,
            FSourceSheet TEXT,
            FSourceRowNo INTEGER
        )
    """,
    "T_HF_RevenueForecast": """
        CREATE TABLE T_HF_RevenueForecast (
            FId INTEGER PRIMARY KEY AUTOINCREMENT,
            FOpportunityNo TEXT,
            FOpportunityName TEXT,
            FIsForecast TEXT,
            FForecastType TEXT,
            FIndustryManagement TEXT,
            FRegion TEXT,
            FForecastMonthRaw REAL,
            FForecastMonthDate TEXT,
            FForecastPeriod TEXT,
            FRevenue REAL,
            FIndustrySegment TEXT,
            FSourceWorkbook TEXT,
            FSourceSheet TEXT,
            FSourceRowNo INTEGER
        )
    """,
    "T_HF_DemoData": """
        CREATE TABLE T_HF_DemoData (
            FId INTEGER PRIMARY KEY AUTOINCREMENT,
            FPeriod TEXT,
            FCompanySegment TEXT,
            FSalesContractNo TEXT,
            FBusinessApplyNo TEXT,
            FDomesticInternational TEXT,
            FRegionSegment TEXT,
            FRegionDept TEXT,
            FRepOffice TEXT,
            FOperatingUnitLv1 TEXT,
            FOperatingUnitLv2 TEXT,
            FCountryName TEXT,
            FIndustry TEXT,
            FContractName TEXT,
            FDeptLv1 TEXT,
            FReportItemLv1 TEXT,
            FReportItemLv2 TEXT,
            FReportItemLv3 TEXT,
            FReportItemLv4 TEXT,
            FAccountCode TEXT,
            FAccountName TEXT,
            FTransCurrency TEXT,
            FTransAmount REAL,
            FAmountCny REAL,
            FAmountUsd REAL,
            FSalesPerson TEXT,
            FOpportunityNo TEXT,
            FIndustrySegment TEXT,
            FCustomerName TEXT,
            FSourceWorkbook TEXT,
            FSourceSheet TEXT,
            FSourceRowNo INTEGER
        )
    """,
    "T_HF_RefreshData": """
        CREATE TABLE T_HF_RefreshData (
            FId INTEGER PRIMARY KEY AUTOINCREMENT,
            FPeriod TEXT,
            FCompanySegment TEXT,
            FSalesContractNo TEXT,
            FBusinessApplyNo TEXT,
            FDomesticInternational TEXT,
            FRegionSegment TEXT,
            FRegionDept TEXT,
            FRepOffice TEXT,
            FOperatingUnitLv1 TEXT,
            FOperatingUnitLv2 TEXT,
            FCountryName TEXT,
            FIndustry TEXT,
            FContractName TEXT,
            FDeptLv1 TEXT,
            FReportItemLv1 TEXT,
            FReportItemLv2 TEXT,
            FReportItemLv3 TEXT,
            FReportItemLv4 TEXT,
            FAccountCode TEXT,
            FAccountName TEXT,
            FTransCurrency TEXT,
            FTransAmount REAL,
            FAmountCny REAL,
            FAmountUsd REAL,
            FSalesPerson TEXT,
            FOpportunityNo TEXT,
            FIndustrySegment TEXT,
            FCustomerName TEXT,
            FSourceWorkbook TEXT,
            FSourceSheet TEXT,
            FSourceRowNo INTEGER
        )
    """,
}


def read_sheet(spec: dict) -> pd.DataFrame:
    df = pd.read_excel(spec["file"], sheet_name=spec["sheet"], engine="openpyxl", dtype=object)
    df = df.rename(columns=spec["columns"])
    keep_cols = list(spec["columns"].values())
    df = df[keep_cols].copy()

    for col in df.columns:
        if col in spec.get("numeric", []):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        else:
            df[col] = df[col].where(pd.notna(df[col]), None)
            df[col] = df[col].map(lambda v: None if v in ("", "NULL") else str(v).strip() if v is not None else None)

    if "FPeriod" in df.columns:
        df["FPeriod"] = df["FPeriod"].map(lambda v: None if v is None or pd.isna(v) else str(v).split(".")[0])

    if "FForecastMonthRaw" in df.columns:
        dates = pd.to_datetime(df["FForecastMonthRaw"], unit="D", origin="1899-12-30", errors="coerce")
        df["FForecastMonthDate"] = dates.dt.strftime("%Y-%m-%d")
        df["FForecastPeriod"] = dates.dt.strftime("%Y%m")

    df["FSourceWorkbook"] = spec["file"].name
    df["FSourceSheet"] = spec["sheet"]
    df["FSourceRowNo"] = range(2, len(df) + 2)
    return df


def write_column_map(cur: sqlite3.Cursor) -> None:
    cur.execute(
        """
        CREATE TABLE T_META_ColumnMap (
            FTableName TEXT NOT NULL,
            FSourceWorkbook TEXT NOT NULL,
            FSourceSheet TEXT NOT NULL,
            FSourceColumnName TEXT NOT NULL,
            FDbColumnName TEXT NOT NULL,
            FColumnOrder INTEGER NOT NULL,
            PRIMARY KEY (FTableName, FSourceColumnName, FDbColumnName)
        )
        """
    )
    rows = []
    for table, spec in TABLE_SPECS.items():
        for i, (source_col, db_col) in enumerate(spec["columns"].items(), start=1):
            rows.append((table, spec["file"].name, spec["sheet"], source_col, db_col, i))
    cur.executemany("INSERT INTO T_META_ColumnMap VALUES (?, ?, ?, ?, ?, ?)", rows)


def create_views(cur: sqlite3.Cursor) -> None:
    cur.executescript(
        """
        CREATE VIEW V_HF_DataAll AS
        SELECT '演示数据' AS FDataVersion, * FROM T_HF_DemoData
        UNION ALL
        SELECT '刷新数据' AS FDataVersion, * FROM T_HF_RefreshData;

        CREATE VIEW V_HF_PL_Summary AS
        SELECT
            FPeriod,
            FDomesticInternational,
            FOperatingUnitLv1,
            FIndustry,
            FIndustrySegment,
            FSubIndustrySegment,
            FSalesType,
            SUM(CASE WHEN FReportItemLv1 = '净销售收入' THEN FAmountCny ELSE 0 END) AS FNetSalesRevenueCny,
            SUM(CASE WHEN FReportItemLv1 = '销售成本' THEN FAmountCny ELSE 0 END) AS FSalesCostCny,
            SUM(CASE WHEN FReportItemLv1 = '净销售收入' THEN FAmountCny ELSE 0 END)
              - SUM(CASE WHEN FReportItemLv1 = '销售成本' THEN FAmountCny ELSE 0 END) AS FGrossMarginCny,
            CASE
              WHEN SUM(CASE WHEN FReportItemLv1 = '净销售收入' THEN FAmountCny ELSE 0 END) = 0 THEN NULL
              ELSE (
                SUM(CASE WHEN FReportItemLv1 = '净销售收入' THEN FAmountCny ELSE 0 END)
                - SUM(CASE WHEN FReportItemLv1 = '销售成本' THEN FAmountCny ELSE 0 END)
              ) / SUM(CASE WHEN FReportItemLv1 = '净销售收入' THEN FAmountCny ELSE 0 END)
            END AS FGrossMarginRate
        FROM T_HF_PL_Detail
        GROUP BY
            FPeriod, FDomesticInternational, FOperatingUnitLv1, FIndustry,
            FIndustrySegment, FSubIndustrySegment, FSalesType;

        CREATE VIEW V_HF_DataAll_Summary AS
        SELECT
            FDataVersion,
            FPeriod,
            FDomesticInternational,
            FRegionDept,
            FRepOffice,
            FOperatingUnitLv1,
            FOperatingUnitLv2,
            FCountryName,
            FIndustry,
            FIndustrySegment,
            FCustomerName,
            SUM(CASE WHEN FReportItemLv1 = '净销售收入' THEN FAmountCny ELSE 0 END) AS FNetSalesRevenueCny,
            SUM(CASE WHEN FReportItemLv1 = '销售成本' THEN FAmountCny ELSE 0 END) AS FSalesCostCny,
            SUM(CASE WHEN FReportItemLv1 = '净销售收入' THEN FAmountCny ELSE 0 END)
              - SUM(CASE WHEN FReportItemLv1 = '销售成本' THEN FAmountCny ELSE 0 END) AS FGrossMarginCny
        FROM V_HF_DataAll
        GROUP BY
            FDataVersion, FPeriod, FDomesticInternational, FRegionDept, FRepOffice,
            FOperatingUnitLv1, FOperatingUnitLv2, FCountryName, FIndustry,
            FIndustrySegment, FCustomerName;
        """
    )


def create_indexes(cur: sqlite3.Cursor) -> None:
    cur.executescript(
        """
        CREATE INDEX IX_HF_PL_Period ON T_HF_PL_Detail(FPeriod);
        CREATE INDEX IX_HF_PL_Dims ON T_HF_PL_Detail(FOperatingUnitLv1, FIndustry, FIndustrySegment);
        CREATE INDEX IX_HF_PL_Item ON T_HF_PL_Detail(FReportItemLv1, FReportItemLv2);
        CREATE INDEX IX_HF_Forecast_Period ON T_HF_RevenueForecast(FForecastPeriod);
        CREATE INDEX IX_HF_Forecast_Dims ON T_HF_RevenueForecast(FIndustryManagement, FRegion, FIndustrySegment);
        CREATE INDEX IX_HF_Demo_Period ON T_HF_DemoData(FPeriod);
        CREATE INDEX IX_HF_Demo_Dims ON T_HF_DemoData(FRegionDept, FRepOffice, FOperatingUnitLv1, FOperatingUnitLv2);
        CREATE INDEX IX_HF_Demo_Item ON T_HF_DemoData(FReportItemLv1, FReportItemLv2);
        CREATE INDEX IX_HF_Refresh_Period ON T_HF_RefreshData(FPeriod);
        CREATE INDEX IX_HF_Refresh_Dims ON T_HF_RefreshData(FRegionDept, FRepOffice, FOperatingUnitLv1, FOperatingUnitLv2);
        CREATE INDEX IX_HF_Refresh_Item ON T_HF_RefreshData(FReportItemLv1, FReportItemLv2);
        """
    )


def build_database() -> None:
    if not REPORT_XLSX.exists():
        raise FileNotFoundError(REPORT_XLSX)
    if not DATA_XLSX.exists():
        raise FileNotFoundError(DATA_XLSX)

    if DB_PATH.exists():
        DB_PATH.unlink()

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")

    for table, sql in CREATE_SQL.items():
        cur.execute(sql)

    for table, spec in TABLE_SPECS.items():
        df = read_sheet(spec)
        df.to_sql(table, con, if_exists="append", index=False)
        print(f"{table}: {len(df)} rows from {spec['file'].name} / {spec['sheet']}")

    write_column_map(cur)
    create_views(cur)
    create_indexes(cur)
    cur.execute("VACUUM")
    con.commit()
    con.close()
    print(f"created: {DB_PATH}")


if __name__ == "__main__":
    build_database()
