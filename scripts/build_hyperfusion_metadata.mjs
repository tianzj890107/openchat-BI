import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = process.cwd();
const outputDir = path.join(root, "dataset", "spreadsheets");
const outputPath = path.join(outputDir, "超聚变本体元数据.xlsx");

const columnMeta = {
  FId: ["主键ID", "INTEGER", "数据库自增主键。"],
  FPeriod: ["会计期", "TEXT", "业务发生或报表统计所属期间，通常为年月。"],
  FSalesContractNo: ["销售合同号", "TEXT", "销售合同唯一编号。"],
  FBusinessApplyNo: ["商务申请编号", "TEXT", "商务申请流程编号。"],
  FDomesticInternational: ["国内/国际", "TEXT", "国内、国际业务分类。"],
  FOperatingUnitLv1: ["经营单元LV1", "TEXT", "一级经营单元。"],
  FOperatingUnitLv2: ["经营单元LV2", "TEXT", "二级经营单元，别名可作为办事处使用。"],
  FIndustry: ["行业", "TEXT", "客户或业务归属行业。"],
  FReportItemLv1: ["报表项名称一级", "TEXT", "损益报表一级项目，如净销售收入、销售成本。"],
  FReportItemLv2: ["报表项名称二级", "TEXT", "损益报表二级项目，如服务收入、设备收入、其他收入。"],
  FReportItemLv3: ["报表项名称三级", "TEXT", "损益报表三级项目。"],
  FReportItemLv4: ["报表项名称四级", "TEXT", "损益报表四级项目。"],
  FAmountCny: ["报告金额CNY", "REAL", "以人民币口径折算的报告金额。"],
  FAmountUsd: ["报告金额USD", "REAL", "以美元口径折算的报告金额。"],
  FIndustrySegment: ["产业", "TEXT", "业务产业分段。"],
  FSubIndustrySegment: ["子产业", "TEXT", "业务子产业分段。"],
  FSalesType: ["销售类型", "TEXT", "销售业务类型，用于行管规则识别。"],
  FSourceWorkbook: ["来源工作簿", "TEXT", "数据来源 Excel 文件名。"],
  FSourceSheet: ["来源工作表", "TEXT", "数据来源 Excel 页签名。"],
  FSourceRowNo: ["来源行号", "INTEGER", "来源 Excel 中的数据行号。"],
  FOpportunityNo: ["机会点编码", "TEXT", "收入预测或经营明细中的机会点编码。"],
  FOpportunityName: ["机会点名称", "TEXT", "收入预测机会点名称。"],
  FIsForecast: ["是否预测", "TEXT", "标识记录是否纳入预测。"],
  FForecastType: ["预测类型", "TEXT", "预测收入类型。"],
  FIndustryManagement: ["行管", "TEXT", "行业管理或行管归属，用于销毛率基线匹配。"],
  FRegion: ["地区", "TEXT", "预测清单中的地区。"],
  FForecastMonthRaw: ["预测月份原值", "TEXT", "来源表中的预测月份原始值。"],
  FForecastMonthDate: ["预测月份日期", "TEXT", "规范化后的预测月份日期。"],
  FForecastPeriod: ["预测期间", "TEXT", "规范化后的预测年月。"],
  FRevenue: ["收入", "REAL", "收入预测金额。"],
  FCompanySegment: ["公司段", "TEXT", "公司段维度。"],
  FRegionSegment: ["区域段", "TEXT", "区域段维度。"],
  FRegionDept: ["地区部", "TEXT", "地区部维度。"],
  FRepOffice: ["代表处", "TEXT", "代表处维度。"],
  FCountryName: ["国家名称", "TEXT", "国家或地区名称。"],
  FContractName: ["合同名称", "TEXT", "销售合同名称。"],
  FDeptLv1: ["一级部门名称", "TEXT", "一级部门名称。"],
  FAccountCode: ["会计科目", "TEXT", "会计科目编码。"],
  FAccountName: ["科目名称", "TEXT", "会计科目名称。"],
  FTransCurrency: ["交易币币种", "TEXT", "交易币种。"],
  FTransAmount: ["交易币金额", "REAL", "以交易币计量的原币金额。"],
  FSalesPerson: ["销售员", "TEXT", "销售责任人或销售员。"],
  FCustomerName: ["客户", "TEXT", "签约或业务客户名称。"],
  FDataVersion: ["数据版本", "TEXT", "合并视图中的数据版本，如演示数据、刷新数据。"],
  FNetSalesRevenueCny: ["净销售收入CNY", "REAL", "人民币口径净销售收入。"],
  FSalesCostCny: ["销售成本CNY", "REAL", "人民币口径销售成本。"],
  FGrossMarginCny: ["销毛额CNY", "REAL", "净销售收入减销售成本后的毛利金额。"],
  FGrossMarginRate: ["销毛率", "REAL", "销毛额除以净销售收入。"],
  FTableName: ["物理表名", "TEXT", "字段映射所属数据库表。"],
  FSourceColumnName: ["来源字段名", "TEXT", "Excel 来源字段名称。"],
  FDbColumnName: ["数据库字段名", "TEXT", "SQLite 数据库字段名称。"],
  FColumnOrder: ["字段顺序", "INTEGER", "来源字段顺序。"],
};

const entities = [
  {
    bo: "BO0001",
    boName: "损益明细",
    id: "LE00001",
    name: "损益明细",
    en: "T_HF_PL_Detail",
    table: "T_HF_PL_Detail",
    definition: "承载超聚变报表《损益明细表》的实际数明细，用于收入、成本、销毛分析和基线搭建。",
    columns: ["FId", "FPeriod", "FSalesContractNo", "FBusinessApplyNo", "FDomesticInternational", "FOperatingUnitLv1", "FIndustry", "FReportItemLv1", "FReportItemLv2", "FReportItemLv3", "FReportItemLv4", "FAmountCny", "FAmountUsd", "FIndustrySegment", "FSubIndustrySegment", "FSalesType", "FSourceWorkbook", "FSourceSheet", "FSourceRowNo"],
  },
  {
    bo: "BO0002",
    boName: "收入预测",
    id: "LE00002",
    name: "收入预测清单",
    en: "T_HF_RevenueForecast",
    table: "T_HF_RevenueForecast",
    definition: "承载超聚变报表《收入预测清单》，用于按行管、地区、产业和预测月份进行收入销毛推演。",
    columns: ["FId", "FOpportunityNo", "FOpportunityName", "FIsForecast", "FForecastType", "FIndustryManagement", "FRegion", "FForecastMonthRaw", "FForecastMonthDate", "FForecastPeriod", "FRevenue", "FIndustrySegment", "FSourceWorkbook", "FSourceSheet", "FSourceRowNo"],
  },
  {
    bo: "BO0003",
    boName: "经营明细",
    id: "LE00003",
    name: "演示经营明细",
    en: "T_HF_DemoData",
    table: "T_HF_DemoData",
    definition: "承载超聚变数据《演示数据》，用于问数测试、经营分析和多维查询演示。",
    columns: ["FId", "FPeriod", "FCompanySegment", "FSalesContractNo", "FBusinessApplyNo", "FDomesticInternational", "FRegionSegment", "FRegionDept", "FRepOffice", "FOperatingUnitLv1", "FOperatingUnitLv2", "FCountryName", "FIndustry", "FContractName", "FDeptLv1", "FReportItemLv1", "FReportItemLv2", "FReportItemLv3", "FReportItemLv4", "FAccountCode", "FAccountName", "FTransCurrency", "FTransAmount", "FAmountCny", "FAmountUsd", "FSalesPerson", "FOpportunityNo", "FIndustrySegment", "FCustomerName", "FSourceWorkbook", "FSourceSheet", "FSourceRowNo"],
  },
  {
    bo: "BO0003",
    boName: "经营明细",
    id: "LE00004",
    name: "刷新经营明细",
    en: "T_HF_RefreshData",
    table: "T_HF_RefreshData",
    definition: "承载超聚变数据《12、刷新数据》，用于实时刷新后的经营明细查询与报表更新。",
    columns: ["FId", "FPeriod", "FCompanySegment", "FSalesContractNo", "FBusinessApplyNo", "FDomesticInternational", "FRegionSegment", "FRegionDept", "FRepOffice", "FOperatingUnitLv1", "FOperatingUnitLv2", "FCountryName", "FIndustry", "FContractName", "FDeptLv1", "FReportItemLv1", "FReportItemLv2", "FReportItemLv3", "FReportItemLv4", "FAccountCode", "FAccountName", "FTransCurrency", "FTransAmount", "FAmountCny", "FAmountUsd", "FSalesPerson", "FOpportunityNo", "FIndustrySegment", "FCustomerName", "FSourceWorkbook", "FSourceSheet", "FSourceRowNo"],
  },
  {
    bo: "BO0003",
    boName: "经营明细",
    id: "LE00005",
    name: "经营明细合并视图",
    en: "V_HF_DataAll",
    table: "V_HF_DataAll",
    definition: "合并演示数据与刷新数据，增加数据版本维度，支持刷新前后对比和统一问数。",
    columns: ["FDataVersion", "FId", "FPeriod", "FCompanySegment", "FSalesContractNo", "FBusinessApplyNo", "FDomesticInternational", "FRegionSegment", "FRegionDept", "FRepOffice", "FOperatingUnitLv1", "FOperatingUnitLv2", "FCountryName", "FIndustry", "FContractName", "FDeptLv1", "FReportItemLv1", "FReportItemLv2", "FReportItemLv3", "FReportItemLv4", "FAccountCode", "FAccountName", "FTransCurrency", "FTransAmount", "FAmountCny", "FAmountUsd", "FSalesPerson", "FOpportunityNo", "FIndustrySegment", "FCustomerName", "FSourceWorkbook", "FSourceSheet", "FSourceRowNo"],
  },
  {
    bo: "BO0004",
    boName: "收入销毛分析",
    id: "LE00006",
    name: "损益销毛汇总",
    en: "V_HF_PL_Summary",
    table: "V_HF_PL_Summary",
    definition: "按期间、国内国际、经营单元、行业、产业、子产业、销售类型聚合净销售收入、销售成本、销毛额和销毛率。",
    columns: ["FPeriod", "FDomesticInternational", "FOperatingUnitLv1", "FIndustry", "FIndustrySegment", "FSubIndustrySegment", "FSalesType", "FNetSalesRevenueCny", "FSalesCostCny", "FGrossMarginCny", "FGrossMarginRate"],
  },
  {
    bo: "BO0004",
    boName: "收入销毛分析",
    id: "LE00007",
    name: "经营明细销毛汇总",
    en: "V_HF_DataAll_Summary",
    table: "V_HF_DataAll_Summary",
    definition: "按数据版本、期间、区域、经营单元、国家、行业、产业、客户聚合净销售收入、销售成本和销毛额。",
    columns: ["FDataVersion", "FPeriod", "FDomesticInternational", "FRegionDept", "FRepOffice", "FOperatingUnitLv1", "FOperatingUnitLv2", "FCountryName", "FIndustry", "FIndustrySegment", "FCustomerName", "FNetSalesRevenueCny", "FSalesCostCny", "FGrossMarginCny"],
  },
  {
    bo: "BO0005",
    boName: "元数据字段映射",
    id: "LE00008",
    name: "来源字段映射",
    en: "T_META_ColumnMap",
    table: "T_META_ColumnMap",
    definition: "记录 Excel 源字段到 SQLite 字段的映射，用于本体属性溯源和数据治理。",
    columns: ["FTableName", "FSourceWorkbook", "FSourceSheet", "FSourceColumnName", "FDbColumnName", "FColumnOrder"],
  },
];

const businessObjects = [
  ["BO0001", "损益明细", "ProfitAndLossDetail", "基于《损益明细表》的实际收入、成本和报表项明细对象。", "明细业务对象", "T_HF_PL_Detail"],
  ["BO0002", "收入预测", "RevenueForecast", "基于《收入预测清单》的预测收入和销毛推演对象。", "明细业务对象", "T_HF_RevenueForecast"],
  ["BO0003", "经营明细", "BusinessOperationDetail", "基于《演示数据》和《12、刷新数据》的经营问数明细对象。", "明细业务对象", "T_HF_DemoData; T_HF_RefreshData; V_HF_DataAll"],
  ["BO0004", "收入销毛分析", "RevenueGrossMarginAnalysis", "围绕净销售收入、销售成本、销毛额和销毛率形成的汇总分析对象。", "分析业务对象", "V_HF_PL_Summary; V_HF_DataAll_Summary"],
  ["BO0005", "元数据字段映射", "MetadataColumnMap", "源 Excel 字段与数据库字段之间的治理映射对象。", "治理业务对象", "T_META_ColumnMap"],
];

const terms = [
  ["TERM001", "净销售收入", "收入、收入金额、净收入", "Net Sales Revenue", "报表项名称一级为净销售收入的金额合计。", "指标", "财务"],
  ["TERM002", "销售成本", "成本、销售成本金额", "Sales Cost", "报表项名称一级为销售成本的金额合计。", "指标", "财务"],
  ["TERM003", "销毛额", "毛利、销毛", "Gross Margin", "净销售收入减销售成本。", "指标", "财务"],
  ["TERM004", "销毛率", "毛利率、销毛率", "Gross Margin Rate", "销毛额除以净销售收入。", "指标", "财务"],
  ["TERM005", "报告金额CNY", "收入、收入金额、收入人民币金额、收入人民币", "Amount CNY", "以人民币口径折算的报告金额。", "金额", "财务"],
  ["TERM006", "报告金额USD", "收入、收入金额、收入美元金额、收入美元", "Amount USD", "以美元口径折算的报告金额。", "金额", "财务"],
  ["TERM007", "本位币金额", "收入、收入金额、收入本币金额、收入本币", "Functional Currency Amount", "以本位币口径展示的金额。", "金额", "财务"],
  ["TERM008", "经营单元LV2", "办事处", "Operating Unit LV2", "二级经营单元，可按办事处口径问数。", "维度", "经营管理"],
  ["TERM009", "报表项名称一级", "收入、净销售收入", "Report Item Level 1", "损益报表一级项目。", "维度", "财务"],
  ["TERM010", "报表项名称二级", "服务收入、设备收入、其他收入", "Report Item Level 2", "损益报表二级项目。", "维度", "财务"],
  ["TERM011", "产业", "产业线、产业分段", "Industry Segment", "收入和销毛分析的产业分类。", "维度", "经营管理"],
  ["TERM012", "子产业", "子产业线", "Sub Industry Segment", "收入和销毛分析的子产业分类。", "维度", "经营管理"],
  ["TERM013", "行管", "行业管理、行管归属", "Industry Management", "收入预测与销毛基线匹配使用的行管分类。", "维度", "经营管理"],
  ["TERM014", "代表处", "区域代表处", "Representative Office", "区域组织维度，用于地区经营分析。", "维度", "销售管理"],
  ["TERM015", "地区部", "地区", "Region Department", "区域管理维度。", "维度", "销售管理"],
  ["TERM016", "机会点编码", "商机编号、机会点", "Opportunity No", "收入预测或经营明细中的机会点编码。", "主数据", "销售管理"],
  ["TERM017", "销售合同号", "合同号、销售合同", "Sales Contract No", "销售合同唯一编号。", "主数据", "销售管理"],
  ["TERM018", "商务申请编号", "商务申请", "Business Application No", "商务流程申请编号。", "主数据", "商务管理"],
  ["TERM019", "交易币金额", "原币金额、交易金额", "Transaction Amount", "以交易币种计量的业务金额。", "金额", "财务"],
  ["TERM020", "数据版本", "演示数据、刷新数据", "Data Version", "区分演示数据和刷新数据的数据版本。", "维度", "数据治理"],
  ["TERM021", "名义销毛", "名义毛利", "Nominal Gross Margin", "净销售收入减设备成本、期间成本、服务成本、其他成本和质量保证金。", "指标", "财务"],
  ["TERM022", "名义销毛率", "名义毛利率", "Nominal Gross Margin Rate", "名义销毛除以净销售收入。", "指标", "财务"],
];

const activities = [
  ["ACT001", "超聚变数据导入", "将超聚变报表和超聚变数据导入 SQLite，保留来源工作簿、页签和行号。", "", "数据工程师", "BO0001;BO0002;BO0003", "损益明细;收入预测;经营明细"],
  ["ACT002", "实际数经营分析", "按产业、子产业、经营单元、行业、报表项分析收入、成本和趋势。", "ACT001", "财务分析师", "BO0001;BO0004", "损益明细;收入销毛分析"],
  ["ACT003", "销毛率基线搭建", "根据国内/国际、经营单元LV1、行业和销售类型识别行管并计算产业+行管销毛率基线。", "ACT002", "财务BP", "BO0001;BO0004", "损益明细;收入销毛分析"],
  ["ACT004", "销毛基线调整", "根据总览页基线调整规则对指定行管和产业进行收入、成本或销毛率修正。", "ACT003", "财务BP", "BO0004", "收入销毛分析"],
  ["ACT005", "收入销毛推演", "将收入预测清单按产业+行管匹配销毛率基线，形成月度收入、销毛额和销毛率推演。", "ACT004", "经营分析师", "BO0002;BO0004", "收入预测;收入销毛分析"],
  ["ACT006", "智能问数测试", "覆盖代表处、产业、客户、币种、同比环比、预测、刷新数据等测试场景。", "ACT001", "BI用户", "BO0003;BO0004", "经营明细;收入销毛分析"],
  ["ACT007", "别名治理维护", "维护字段别名为通用设置，跨主题共享收入、金额、办事处等问法。", "ACT006", "数据治理员", "BO0005", "元数据字段映射"],
];

const rules = [
  ["RULE001", "实际数分析基于《损益明细表》，按产业/子产业、经营单元、行业、报表项、变化趋势、历史实际数基线、预算执行率和全年预测执行率输出经营分析结论。", "ACT002", "实际数经营分析", "分析口径", "财务"],
  ["RULE002", "销毛额=净销售收入-销售成本。", "ACT003", "销毛率基线搭建", "指标公式", "财务"],
  ["RULE003", "销毛率=销毛额/净销售收入；净销售收入为0时销毛率为空。", "ACT003", "销毛率基线搭建", "指标公式", "财务"],
  ["RULE004", "行管1-5按国内业务、经营单元/办事处、行业及销售类型非类型a进行匹配，作为产业+行管销毛率基线维度。", "ACT003", "销毛率基线搭建", "分类规则", "经营管理"],
  ["RULE005", "行管6匹配国内/国际=国际且销售类型<>类型a。", "ACT003", "销毛率基线搭建", "分类规则", "经营管理"],
  ["RULE006", "行管7匹配销售类型=类型a。", "ACT003", "销毛率基线搭建", "分类规则", "经营管理"],
  ["RULE007", "基线调整：行管1&产业2收入减少5200万、成本减少4100万。", "ACT004", "销毛基线调整", "调整规则", "财务"],
  ["RULE008", "基线调整：行管1&产业3收入增加5200万、成本增加4100万。", "ACT004", "销毛基线调整", "调整规则", "财务"],
  ["RULE009", "特殊利好/利空：行管3&产业2收入减少5500万、成本减少500万。", "ACT004", "销毛基线调整", "调整规则", "财务"],
  ["RULE010", "基线替换：行管5&产业3最终基线销毛率替换为20%。", "ACT004", "销毛基线调整", "调整规则", "财务"],
  ["RULE011", "销毛推演按《收入预测清单》的产业+行管匹配最终销毛率基线，计算月度收入、销毛额和销毛率。", "ACT005", "收入销毛推演", "推演规则", "经营分析"],
  ["RULE012", "名义销毛=净销售收入-设备成本-期间成本-服务成本-其他成本-质量保证金；名义销毛率=名义销毛/净销售收入。", "ACT006", "智能问数测试", "指标公式", "财务"],
  ["RULE013", "别名维护为通用设置，不按主题孤立维护；收入主题别名调整后，损益主题同步生效。", "ACT007", "别名治理维护", "治理规则", "数据治理"],
];

const metrics = [
  ["MET001", "净销售收入", "NetSalesRevenueCny", "人民币口径净销售收入。", "SUM(FAmountCny) WHERE FReportItemLv1='净销售收入'", "金额", "T_HF_PL_Detail; V_HF_DataAll", "财务"],
  ["MET002", "销售成本", "SalesCostCny", "人民币口径销售成本。", "SUM(FAmountCny) WHERE FReportItemLv1='销售成本'", "金额", "T_HF_PL_Detail; V_HF_DataAll", "财务"],
  ["MET003", "销毛额", "GrossMarginCny", "净销售收入减销售成本。", "净销售收入-销售成本", "金额", "V_HF_PL_Summary; V_HF_DataAll_Summary", "财务"],
  ["MET004", "销毛率", "GrossMarginRate", "销毛额与净销售收入的比率。", "销毛额/净销售收入", "比例", "V_HF_PL_Summary", "财务"],
  ["MET005", "报告金额CNY", "AmountCny", "人民币报告金额。", "SUM(FAmountCny)", "金额", "T_HF_PL_Detail; V_HF_DataAll", "财务"],
  ["MET006", "报告金额USD", "AmountUsd", "美元报告金额。", "SUM(FAmountUsd)", "金额", "T_HF_PL_Detail; V_HF_DataAll", "财务"],
  ["MET007", "收入预测", "ForecastRevenue", "预测清单中的收入预测金额。", "SUM(FRevenue)", "金额", "T_HF_RevenueForecast", "经营分析"],
  ["MET008", "交易币金额", "TransactionAmount", "以交易币种计量的金额。", "SUM(FTransAmount)", "金额", "T_HF_DemoData; T_HF_RefreshData; V_HF_DataAll", "财务"],
  ["MET009", "名义销毛", "NominalGrossMargin", "测试场景要求的名义销毛。", "净销售收入-设备成本-期间成本-服务成本-其他成本-质量保证金", "金额", "V_HF_DataAll_Summary", "财务"],
  ["MET010", "名义销毛率", "NominalGrossMarginRate", "名义销毛与净销售收入的比率。", "名义销毛/净销售收入", "比例", "V_HF_DataAll_Summary", "财务"],
];

const matrixDims = [
  ["会计期", "FPeriod", "期间趋势、同比环比、月度刷新"],
  ["国内/国际", "FDomesticInternational", "国内国际拆分"],
  ["地区部", "FRegionDept", "区域分析"],
  ["代表处", "FRepOffice", "代表处收入、成本、排名"],
  ["经营单元LV1", "FOperatingUnitLv1", "经营单元经营分析"],
  ["经营单元LV2", "FOperatingUnitLv2", "办事处问数"],
  ["国家名称", "FCountryName", "国家维度分析"],
  ["行业", "FIndustry", "行业经营分析"],
  ["产业", "FIndustrySegment", "产业趋势和销毛基线"],
  ["子产业", "FSubIndustrySegment", "子产业拆分"],
  ["销售类型", "FSalesType", "行管识别"],
  ["行管", "FIndustryManagement", "预测基线匹配"],
  ["客户", "FCustomerName", "客户TOP分析"],
  ["销售员", "FSalesPerson", "销售责任人分析"],
  ["机会点编码", "FOpportunityNo", "机会点追踪"],
];

const testScenarios = [
  ["TS001", "深圳办事处25年8月新增收入是多少？", "办事处月度新增收入", "FOperatingUnitLv2/FRepOffice;FPeriod;FAmountCny", "经营明细", "数值回答"],
  ["TS002", "北京代表处2025年6月份的设备收入是多少？", "代表处设备收入", "FRepOffice;FPeriod;FReportItemLv2;FAmountCny", "经营明细", "数值回答"],
  ["TS003", "河北代表处下哪个办事处的收入最高？", "代表处下办事处排名", "FRepOffice;FOperatingUnitLv2;FAmountCny", "经营明细", "排序"],
  ["TS004", "近3年哪个产业的收入增长的较快？", "产业收入增长趋势", "FPeriod;FIndustrySegment;FAmountCny", "经营明细", "趋势排名"],
  ["TS005", "江苏办事处下TOP3签约客户及对应的收入金额分别是？", "客户TOP分析", "FOperatingUnitLv2;FCustomerName;FAmountCny", "经营明细", "TOPN"],
  ["TS006", "25年1-5月全公司收入的币种是哪几种，并对收入金额排序。", "币种收入排序", "FPeriod;FTransCurrency;FTransAmount", "经营明细", "排序"],
  ["TS007", "25年河南哪个产业收入最高？最高的是哪个月？销售成本哪个月最高？最高多少是多少金额？", "追问式经营分析", "FRegionDept/FRepOffice;FIndustrySegment;FPeriod;FAmountCny", "经营明细", "多轮问答"],
  ["TS008", "在追问场景中提示用户可能会询问的问题", "提示问题推荐", "上下文意图;指标;维度", "智能问数", "推荐问题"],
  ["TS009", "25年5月河北代表处销售成本同比环比，总结出具体波动原因", "成本同比环比归因", "FPeriod;FRepOffice;FReportItemLv1;FAmountCny", "经营明细", "分析结论"],
  ["TS010", "根据每年增长趋势，预测下26年黑龙江收入是多少？", "趋势预测", "FPeriod;FRepOffice/FRegionDept;FAmountCny", "经营明细", "预测值"],
  ["TS011", "四川代表处需增加多少收入，才可以在收入排名中达到第一？", "目标差距测算", "FRepOffice;FAmountCny", "经营明细", "差额测算"],
  ["TS012", "根据提供最新的数据实时更新报表，列出河北代表处25年每月收入情况", "刷新数据报表更新", "FDataVersion;FRepOffice;FPeriod;FAmountCny", "经营明细合并视图", "月度列表"],
  ["TS013", "现场随机问问题，现场解答，考验问答准确性。", "自由问数", "按问题动态识别", "经营明细", "问答"],
  ["TS014", "根据线下最新的区域维表算出陕西代表处各年度最新销售成本数据。", "维表调整后重算", "FRepOffice;FPeriod;FReportItemLv1;FAmountCny", "经营明细", "重算结果"],
  ["TS015", "请根据规则计算出25年全年中国区的名义销毛、名义销毛率。", "名义销毛计算", "FPeriod;FDomesticInternational;FReportItemLv1/2;FAmountCny", "经营明细", "指标计算"],
  ["TS016", "根据以上数据，出一份关于25年中国区的经营报告，横轴为产业、纵轴根据报表项名称层级展示。", "经营报告生成", "FIndustrySegment;FReportItemLv1-4;FAmountCny", "经营明细", "报表/图表"],
  ["TS017", "用户咨询问题后，结果出具为Excel或PPT，支持下载到本地", "结果导出", "问答结果", "智能问数", "Excel/PPT"],
  ["TS018", "支持上传EXCEL/PDF文件，进行问数", "文件问数", "上传文件字段", "智能问数", "问答"],
  ["TS019", "根据数据表中的字段，用户可以自行拖拉字段，自定义报告样式，同时关联数据", "自助拖拽报表", "字段元数据", "元数据字段映射", "自定义报表"],
  ["TS020", "别名补充维护为通用设置，不能一个主题、一个主题维护。", "通用别名治理", "字段别名", "别名维护", "治理规则"],
  ["TS021", "在使用问答功能后将问题及整个分析过程保存或收藏", "问答收藏", "问题;分析过程;结果", "智能问数", "收藏"],
  ["TS022", "点赞和点踩按钮设置到意图识别框内，业务可以直接反馈意图识别的准确性", "意图反馈", "意图识别结果;反馈", "智能问数", "反馈"],
  ["TS023", "功能可以关联在其他系统界面，例如报告系统", "系统集成", "问数入口;上下文", "智能问数", "嵌入"],
  ["TS024", "支持英文界面，支持多国语音输入。", "多语言入口", "语言;语音输入", "智能问数", "多语言"],
  ["TS025", "在用户权限内问题答复结果可转发给别的用户或者上传到welink", "结果分享", "用户权限;问答结果", "智能问数", "分享"],
];

const aliases = [
  ["报告金额CNY", "收入、收入金额、收入人民币金额、收入人民币", "FAmountCny", "金额字段", "来自超聚变数据《别名维护》"],
  ["报告金额usd", "收入、收入金额、收入美元金额、收入美元", "FAmountUsd", "金额字段", "来自超聚变数据《别名维护》"],
  ["本位币金额", "收入、收入金额、收入本币金额、收入本币", "", "金额字段", "来自超聚变数据《别名维护》"],
  ["经营单元LV2", "办事处", "FOperatingUnitLv2", "维度字段", "来自超聚变数据《别名维护》"],
  ["报表项名称一", "收入、净销售收入", "FReportItemLv1", "维度字段", "来自超聚变数据《别名维护》"],
  ["报表项名称二", "服务收入、设备收入、其他收入", "FReportItemLv2", "维度字段", "来自超聚变数据《别名维护》"],
];

function colName(index) {
  let n = index + 1;
  let s = "";
  while (n > 0) {
    const m = (n - 1) % 26;
    s = String.fromCharCode(65 + m) + s;
    n = Math.floor((n - m) / 26);
  }
  return s;
}

function addSheet(workbook, name, headers, data, widths = []) {
  const sheet = workbook.worksheets.add(name);
  const rows = [headers, ...data];
  const range = sheet.getRangeByIndexes(0, 0, rows.length, headers.length);
  range.values = rows;
  range.format = {
    font: { name: "Microsoft YaHei", size: 10, color: "#1F2937" },
    borders: { preset: "all", style: "thin", color: "#D9E2F3" },
    verticalAlignment: "top",
    wrapText: true,
  };
  const header = sheet.getRangeByIndexes(0, 0, 1, headers.length);
  header.format = {
    fill: "#1F4E79",
    font: { name: "Microsoft YaHei", size: 10, color: "#FFFFFF", bold: true },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
  };
  sheet.getRangeByIndexes(0, 0, 1, headers.length).format.rowHeightPx = 32;
  if (rows.length > 1) {
    sheet.getRangeByIndexes(1, 0, rows.length - 1, headers.length).format.rowHeightPx = 44;
  }
  for (let i = 0; i < headers.length; i += 1) {
    sheet.getRangeByIndexes(0, i, rows.length, 1).format.columnWidthPx = widths[i] ?? 150;
  }
  sheet.freezePanes.freezeRows(1);
  return sheet;
}

const workbook = Workbook.create();

addSheet(
  workbook,
  "目录",
  ["序号", "页签", "内容说明", "来源参考"],
  [
    [1, "术语", "ChatBI 问数与报表常用业务术语、别名和定义。", "超聚变数据-别名维护；当前数据库字段"],
    [2, "业务规则", "收入销毛分析、基线调整、推演和别名治理规则。", "超聚变报表-总览；超聚变数据-测试场景"],
    [3, "活动", "从数据导入到问数、推演和别名治理的业务活动。", "超聚变报表-总览"],
    [4, "业务对象", "按数据库物理表/视图聚合后的业务对象。", "HyperFusion.db"],
    [5, "逻辑实体", "SQLite 物理表和视图。", "HyperFusion.db"],
    [6, "业务属性", "逻辑实体字段级元数据。", "HyperFusion.db"],
    [7, "实体关系", "实体之间的业务关联与关联条件。", "HyperFusion.db"],
    [8, "指标", "可问数、可出报表的经营指标口径。", "超聚变报表-总览；测试场景"],
    [9, "指标维度矩阵", "指标可按哪些维度分析。", "当前数据库字段"],
    [10, "测试场景映射", "测试问题到实体、字段和输出形式的映射。", "超聚变数据-测试场景"],
    [11, "别名维护", "源别名维护页内容转为通用别名元数据。", "超聚变数据-别名维护"],
  ],
  [55, 130, 380, 300],
);

addSheet(workbook, "术语", ["术语编码", "术语名称", "别名", "英文名", "术语定义", "术语分类", "解释部门"], terms, [90, 130, 280, 170, 360, 100, 100]);
addSheet(workbook, "业务规则", ["规则编号", "规则", "所属活动编号", "活动名称", "规则分类", "解释部门"], rules, [90, 620, 110, 150, 110, 100]);
addSheet(workbook, "活动", ["活动编码", "活动名称", "活动描述", "上游活动编码", "业务角色", "操作业务对象编号", "操作业务对象名称"], activities, [90, 150, 390, 120, 120, 160, 210]);
addSheet(workbook, "业务对象", ["业务对象编号", "业务对象名称", "业务对象英文名", "业务对象定义", "业务对象类型", "关联物理表"], businessObjects, [105, 145, 190, 380, 130, 330]);

addSheet(
  workbook,
  "逻辑实体",
  ["业务对象编号", "业务对象名称", "逻辑实体编号", "逻辑实体名称", "英文名", "逻辑实体定义", "对应物理表"],
  entities.map((e) => [e.bo, e.boName, e.id, e.name, e.en, e.definition, e.table]),
  [105, 140, 105, 160, 210, 420, 210],
);

let attrNo = 1;
const attrs = [];
for (const entity of entities) {
  for (const field of entity.columns) {
    const [cn, type, def] = columnMeta[field] ?? [field, "TEXT", "当前数据库字段。"];
    attrs.push([
      entity.id,
      entity.name,
      entity.en,
      `AT${String(attrNo).padStart(5, "0")}`,
      cn,
      field,
      def,
      type,
      field === "FId" || (entity.table === "T_META_ColumnMap" && ["FTableName", "FSourceColumnName", "FDbColumnName"].includes(field)) ? "是" : "否",
      `${entity.table}.${field}`,
    ]);
    attrNo += 1;
  }
}

addSheet(
  workbook,
  "业务属性",
  ["逻辑实体编号", "逻辑实体名称", "逻辑实体英文名", "业务属性编号", "业务属性名称", "属性英文名", "业务属性定义", "数据类型", "是否主键", "来源字段"],
  attrs,
  [105, 150, 210, 115, 150, 170, 350, 90, 80, 260],
);

const relations = [
  ["REL001", "LE00003", "演示经营明细", "LE00004", "刷新经营明细", "同构合并", "字段结构一致，通过 V_HF_DataAll UNION ALL 合并", "用于刷新前后数据统一问数。"],
  ["REL002", "LE00003;LE00004", "经营明细", "LE00005", "经营明细合并视图", "派生视图", "V_HF_DataAll 增加 FDataVersion 后合并两张明细表", "提供统一数据版本维度。"],
  ["REL003", "LE00001", "损益明细", "LE00006", "损益销毛汇总", "聚合派生", "按 FPeriod、FDomesticInternational、FOperatingUnitLv1、FIndustry、FIndustrySegment、FSubIndustrySegment、FSalesType 聚合", "支撑总览页经营分析和销毛率基线。"],
  ["REL004", "LE00005", "经营明细合并视图", "LE00007", "经营明细销毛汇总", "聚合派生", "按数据版本、期间、区域、经营单元、国家、行业、产业、客户聚合", "支撑测试场景中的代表处、客户和刷新数据问数。"],
  ["REL005", "LE00001", "损益明细", "LE00002", "收入预测清单", "口径匹配", "FIndustrySegment=FIndustrySegment，并通过行管规则匹配 FIndustryManagement", "用于收入销毛推演。"],
  ["REL006", "LE00008", "来源字段映射", "LE00001-LE00004", "源字段映射", "FTableName 对应表名，FDbColumnName 对应字段名", "用于字段溯源和本体属性治理。"],
];
addSheet(workbook, "实体关系", ["关系编号", "主实体编号", "主实体名称", "从实体编号", "从实体名称", "关系类型", "关联条件", "关系说明"], relations, [90, 130, 150, 130, 170, 110, 430, 300]);

addSheet(workbook, "指标", ["指标编号", "指标名称", "指标英文名", "指标定义", "计算口径", "数据类型", "来源实体", "解释部门"], metrics, [90, 140, 190, 300, 420, 90, 290, 100]);

const metricMatrix = [];
for (const metric of metrics) {
  for (const [dimName, dimField, usage] of matrixDims) {
    const source = dimField === "FIndustryManagement" ? "T_HF_RevenueForecast" : metric[6];
    metricMatrix.push([metric[0], metric[1], dimName, dimField, source, usage]);
  }
}
addSheet(workbook, "指标维度矩阵", ["指标编号", "指标名称", "维度名称", "维度字段", "来源实体", "适用场景"], metricMatrix, [90, 140, 140, 170, 300, 260]);

addSheet(workbook, "测试场景映射", ["场景编号", "测试问题", "意图分类", "关键字段", "推荐实体/对象", "输出形式"], testScenarios, [90, 520, 170, 260, 170, 120]);
addSheet(workbook, "别名维护", ["字段/术语", "别名", "映射字段", "类型", "来源"], aliases, [150, 360, 160, 120, 250]);

const checks = [
  ["检查项", "结果", "说明"],
  ["逻辑实体数量", entities.length, "来自当前 HyperFusion.db 的表和视图建模"],
  ["业务属性数量", attrs.length, "按逻辑实体字段展开，包含重复实体字段"],
  ["测试场景数量", testScenarios.length, "来自超聚变数据《测试场景》"],
  ["别名维护数量", aliases.length, "来自超聚变数据《别名维护》"],
  ["业务规则数量", rules.length, "来自超聚变报表《总览》和测试场景"],
];
addSheet(workbook, "检查", checks[0], checks.slice(1), [160, 100, 380]);

for (const sheetName of ["目录", "业务对象", "逻辑实体", "业务属性", "业务规则", "测试场景映射", "别名维护", "检查"]) {
  await workbook.render({ sheetName, range: `A1:${colName(workbook.worksheets.getItem(sheetName).getUsedRange().columnCount - 1)}${Math.min(workbook.worksheets.getItem(sheetName).getUsedRange().rowCount, 30)}`, scale: 1 });
}

const preview = await workbook.inspect({
  kind: "table",
  range: "业务对象!A1:F8",
  include: "values",
  tableMaxRows: 10,
  tableMaxCols: 8,
});
console.log(preview.ndjson);

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "final formula error scan",
});
console.log(errors.ndjson);

await fs.mkdir(outputDir, { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(outputPath);
