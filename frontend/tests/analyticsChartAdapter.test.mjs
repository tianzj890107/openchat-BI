import test from "node:test";
import assert from "node:assert/strict";
import {
  buildProBiChart,
  chartDisplayValue,
} from "../src/analyticsChartAdapter.js";

function moneyChart(overrides = {}) {
  return {
    chart_type: "bar",
    title: "收入与成本",
    option: {
      xAxis: { data: ["华东", "华南"] },
      series: [
        { name: "收入", type: "bar", data: [120000, 80000] },
        { name: "成本", type: "bar", data: [70000, 50000] },
      ],
      ...overrides,
    },
  };
}

test("duplicate series display names keep distinct stable row keys", () => {
  const chart = buildProBiChart({
    chart_type: "bar",
    option: {
      xAxis: { data: ["A", "B"] },
      series: [
        { name: "金额", data: [1, 2] },
        { name: "金额", data: [3, 4] },
      ],
    },
  });

  assert.deepEqual(Object.keys(chart.rows[0]).sort(), ["category", "series_1", "series_2"]);
  assert.equal(chart.rows[0].series_1.value, 1);
  assert.equal(chart.rows[0].series_2.value, 3);
  assert.equal(chart.rows[1].series_1.value, 2);
  assert.equal(chart.rows[1].series_2.value, 4);
  assert.equal(chart.measures[0].label, "金额");
  assert.equal(chart.measures[1].label, "金额");
  assert.notEqual(chart.measures[0].identifierCode, chart.measures[1].identifierCode);
});

test("stack semantics are preserved on measure fields", () => {
  const chart = buildProBiChart({
    chart_type: "bar",
    option: {
      xAxis: { data: ["A"] },
      series: [
        { name: "线上", data: [3], stack: "total" },
        { name: "线下", data: [7], stack: "total" },
      ],
    },
  });
  assert.equal(chart.measures[0].stack, "total");
  assert.equal(chart.measures[1].stack, "total");
});

test("dual axis series keep yAxisIndex instead of silently collapsing", () => {
  const chart = buildProBiChart({
    chart_type: "bar",
    option: {
      xAxis: { data: ["A"] },
      yAxis: [{ name: "金额" }, { name: "占比" }],
      series: [
        { name: "金额", data: [100], yAxisIndex: 0 },
        { name: "占比", data: [12.5], yAxisIndex: 1 },
      ],
    },
  });
  assert.equal(chart.customOptions.yAxis.length, 2);
  assert.equal(chart.customOptions.series[0].yAxisIndex, 0);
  assert.equal(chart.customOptions.series[1].yAxisIndex, 1);
  assert.equal(chart.customOptions.series[1].data[0], 12.5);
});

test("empty values stay empty rather than becoming a displayed zero", () => {
  const chart = buildProBiChart({
    chart_type: "line",
    option: {
      xAxis: { data: ["A", "B"] },
      series: [{ name: "收入", data: [null, 0] }],
    },
  });
  assert.equal(chart.rows[0].series_1, null);
  assert.equal(chart.rows[1].series_1.value, 0);
});

test("percent units format values as percentages", () => {
  const value = chartDisplayValue(12.5, { label: "毛利率", unit: "%" });
  assert.equal(value.value, 12.5);
  assert.equal(value.formatValue, "12.50%");
});

test("analysis charts do not silently truncate categories with the renderer default", () => {
  const chart = buildProBiChart(moneyChart());
  assert.equal(chart.visualization.displayLimit.enabled, false);
});

test("pie charts keep slice names and numeric values", () => {
  const chart = buildProBiChart({
    chart_type: "pie",
    option: {
      series: [{ name: "占比", data: [{ name: "华东", value: 62 }, { name: "华南", value: 38 }] }],
    },
  });
  assert.deepEqual(chart.rows.map((row) => row.category), ["华东", "华南"]);
  assert.equal(chart.rows[0].value.value, 62);
  assert.equal(chart.rows[1].value.value, 38);
});
