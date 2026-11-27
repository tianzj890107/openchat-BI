import React, {useEffect, useMemo, useRef, useState} from "react";

import {buildProBiChart} from "../../src/analyticsChartAdapter.js";
import {withBasePath} from "../api.js";

const chartComponents = {
  bar: "ProBarChart",
  horizontal_bar: "ProHorizontalBarChart",
  line: "ProLineChart",
  area: "ProAreaChart",
  pie: "ProPieChart",
};

let chartLibrary;
let scatterLibrary;

function loadScript(path) {
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = withBasePath(path);
    script.onload = resolve;
    script.onerror = () => {
      script.remove();
      reject(new Error("图表组件加载失败"));
    };
    document.head.append(script);
  });
}

function loadChartLibrary() {
  if (window.ProUIBi && window.Vue) return Promise.resolve();
  if (!chartLibrary) {
    chartLibrary = (window.Vue ? Promise.resolve() : loadScript("static/vendor/antd/lib/vue.global.js?v=1"))
      .then(() => loadScript("static/vendor/antd/lib/pro-bi-ui.min.js?v=2"))
      .catch((error) => {
        chartLibrary = undefined;
        throw error;
      });
  }
  return chartLibrary;
}

export function loadEcharts() {
  if (window.echarts) return Promise.resolve();
  if (!scatterLibrary) {
    scatterLibrary = loadScript("static/vendor/echarts.min.js").catch((error) => {
      scatterLibrary = undefined;
      throw error;
    });
  }
  return scatterLibrary;
}

export default function ProBiChart({chart}) {
  const host = useRef(null);
  const [error, setError] = useState("");
  const {title, chart_type: chartType, option} = chart;
  const spec = useMemo(() => buildProBiChart({title, chart_type: chartType, option}), [title, chartType, option]);
  const useProBi = Object.hasOwn(chartComponents, spec.type);
  const hasData = !useProBi
    ? Array.isArray(option?.series) && option.series.some((series) => Array.isArray(series?.data) && series.data.length)
    : spec.rows.length > 0;
  const hasMissing = spec.rows.some((row) => spec.measures.some((field) => row[field.id] == null));
  useEffect(() => {
    if (!hasData) return undefined;
    const node = host.current;
    let active = true;
    let dispose;
    setError("");
    const mount = async () => {
      try {
        if (!useProBi) {
          await loadEcharts();
          if (!active) return;
          // Preserve charts the component library does not render, including
          // scatter with its original numeric axes.
          const instance = window.echarts.init(node);
          const resize = new ResizeObserver(() => instance.resize());
          resize.observe(node);
          dispose = () => { resize.disconnect(); instance.dispose(); };
          instance.setOption(option);
          return;
        }
        await loadChartLibrary();
        if (!active) return;
        const {Vue, ProUIBi} = window;
        const component = ProUIBi?.[chartComponents[spec.type]];
        if (!component) throw new Error("图表组件不可用");
        const app = Vue.createApp({
          render: () => Vue.h(component, {
            component: {...spec.component, showHeader: false},
            data: spec.rows,
          }),
        });
        dispose = () => app.unmount();
        app.mount(node);
      } catch (failure) {
        if (active) setError(failure.message);
      }
    };
    const observer = typeof IntersectionObserver === "function" ? new IntersectionObserver((entries) => {
      if (!entries.some((item) => item.isIntersecting)) return;
      observer.disconnect();
      void mount();
    }) : null;
    if (observer) observer.observe(node);
    else void mount();
    return () => {
      active = false;
      observer?.disconnect();
      dispose?.();
    };
  }, [option, hasData, useProBi, spec]);

  if (!hasData) return <p className="ak-card-note">该图没有可展示的数据。</p>;
  return (
    <>
      <div className="ak-pro-bi-chart" ref={host} aria-label={spec.title} hidden={Boolean(error)} />
      {error ? <p className="ak-card-note" role="status">{error}</p> : null}
      {hasMissing ? <p className="ak-card-note">— 表示暂无数据</p> : null}
    </>
  );
}
