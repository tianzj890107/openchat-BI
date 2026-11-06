/**
 * Analytics → Pro BI chart adapter.
 *
 * The generated chart contract is an ECharts-shaped option because that is
 * also the persisted history/export format. Pro BI consumes row data plus a
 * component description, so this module is the single translation point.
 *
 * The adapter deliberately keeps a stable internal series key (`series_1`,
 * `series_2`, …). Display names may repeat (for example two "金额" series for
 * different dimensions); using them as object keys would silently overwrite
 * one series. Display labels stay on the measure field alias instead.
 */

export const PRO_BI_CHART_TYPES = new Set(["bar", "horizontal_bar", "line", "area", "pie"]);

export function proBiChartType(chart) {
  const type = String(chart?.chart_type || chart?.option?.series?.[0]?.type || "").toLowerCase();
  return type === "horizontalbar" || type === "horizontal-bar" ? "horizontal_bar" : type;
}

export function isMoneyLabel(label, unit = "") {
  return /元|金额|金额占比|收入|成本|采购|销售|库存|利润|费用|支出|应收|应付|余额|价格|单价|税额|营收|¥|￥/.test(`${label || ""}${unit || ""}`);
}

export function isPercentLabel(label, unit = "") {
  return /%|百分比|占比|比例|比率|率$/.test(`${label || ""}${unit || ""}`);
}

export function isNumericValue(value) {
  return typeof value === "number" && Number.isFinite(value)
    || typeof value === "string" && value.trim() !== "" && Number.isFinite(Number(value));
}

export function formatDisplayNumber(value, { money = false, unit = "", percent = false } = {}) {
  const num = Number(value);
  if (!Number.isFinite(num)) return String(value ?? "");
  if (percent) return `${num.toFixed(2)}%`;
  if (money) {
    if (num === 0) return "¥0.00";
    const sign = num < 0 ? "-" : "";
    const abs = Math.abs(num);
    if (abs >= 10000) return `${sign}¥${(abs / 10000).toFixed(2)}万`;
    return `${sign}¥${abs.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }
  const formatted = num.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
  return `${formatted}${unit ? ` ${unit}` : ""}`;
}

export function chartDisplayValue(value, labelOrOptions) {
  if (value == null || value === "") return null;
  const options = labelOrOptions && typeof labelOrOptions === "object"
    ? labelOrOptions
    : { label: labelOrOptions };
  const source = value && typeof value === "object" ? value : { value };
  const raw = source.value;
  if (!isNumericValue(raw)) return value;
  const label = options.label ?? "";
  const unit = source.unit || options.unit || "";
  const money = options.money ?? isMoneyLabel(label, unit);
  const percent = options.percent ?? isPercentLabel(label, unit);
  return {
    ...source,
    value: Number(raw),
    formatValue: formatDisplayNumber(raw, { money, unit, percent }),
  };
}

function rawValue(value) {
  if (value && typeof value === "object") return value.value ?? null;
  return value;
}

function seriesLabel(item, index) {
  return String(item?.name || `系列 ${index + 1}`);
}

function measureField(item, index) {
  const label = seriesLabel(item, index);
  const field = {
    id: `series_${index + 1}`,
    identifierCode: `series_${index + 1}`,
    alias: label,
    label,
  };
  if (typeof item?.stack === "string" && item.stack) field.stack = item.stack;
  return field;
}

function buildDualAxisOptions(chart, series, type) {
  const option = chart?.option || {};
  const axes = Array.isArray(option.yAxis)
    ? option.yAxis.map((axis) => ({ ...axis }))
    : [option.yAxis ? { ...option.yAxis } : { type: "value" }, { type: "value" }];
  while (axes.length < 2) axes.push({ type: "value" });
  return {
    yAxis: axes,
    series: series.map((item, index) => {
      const entry = {
        name: seriesLabel(item, index),
        type: item?.type || (type === "area" ? "line" : type === "horizontal_bar" ? "bar" : type),
        yAxisIndex: Number.isFinite(Number(item?.yAxisIndex)) ? Number(item.yAxisIndex) : 0,
        data: Array.isArray(item?.data) ? item.data.map(rawValue) : [],
      };
      if (typeof item?.stack === "string" && item.stack) entry.stack = item.stack;
      if (item?.areaStyle || type === "area") entry.areaStyle = item?.areaStyle || { opacity: 0.15 };
      return entry;
    }),
  };
}

export function buildProBiChart(chart) {
  const type = proBiChartType(chart);
  const option = chart?.option || {};
  const series = Array.isArray(option.series) ? option.series : [];
  const title = String(chart?.title || "分析结果");

  if (type === "pie") {
    const points = Array.isArray(series[0]?.data) ? series[0].data : [];
    const label = series[0]?.name || "值";
    const measures = [{ id: "value", identifierCode: "value", alias: label, label }];
    const rows = points.map((point) => ({
      category: point?.name ?? "",
      value: chartDisplayValue(point?.value ?? point, label),
    }));
    return {
      type,
      title,
      categories: rows.map((row) => row.category),
      rows,
      measures,
      component: {
        id: `chart-${Date.now()}-${Math.random().toString(16).slice(2)}`,
        title,
        showHeader: true,
        dataConfig: {
          categoryAxis: [{ id: "category", identifierCode: "category", label: "类别" }],
          valueAxis: measures,
        },
        visualization: { displayLimit: { enabled: false } },
      },
      visualization: { displayLimit: { enabled: false } },
    };
  }

  const categories = type === "horizontal_bar" ? option.yAxis?.data : option.xAxis?.data;
  const labels = Array.isArray(categories) ? categories : [];
  const measures = series.map(measureField);
  const rows = labels.map((category, index) => {
    const row = { category };
    series.forEach((item, seriesIndex) => {
      const key = `series_${seriesIndex + 1}`;
      const value = Array.isArray(item?.data) ? item.data[index] : null;
      row[key] = chartDisplayValue(value, { label: seriesLabel(item, seriesIndex) });
    });
    return row;
  });

  const dualAxis = series.some((item) => Number(item?.yAxisIndex) > 0);
  const visualization = { displayLimit: { enabled: false } };
  const customOptions = dualAxis ? buildDualAxisOptions(chart, series, type) : undefined;
  if (customOptions) visualization.customOptions = customOptions;

  return {
    type,
    title,
    categories: labels,
    rows,
    measures,
    visualization,
    customOptions,
    component: {
      id: `chart-${Date.now()}-${Math.random().toString(16).slice(2)}`,
      title,
      showHeader: true,
      dataConfig: {
        categoryAxis: [{ id: "category", identifierCode: "category", label: "类别" }],
        valueAxis: measures,
      },
      visualization,
    },
  };
}
