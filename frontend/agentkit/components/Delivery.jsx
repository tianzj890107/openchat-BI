import React, {useEffect, useRef, useState} from "react";

import {requestJson} from "../api.js";
import {loadEcharts} from "./ProBiChart.jsx";

const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
})[char]);
const paragraph = (value) => escape(value).replace(/\n/g, "<br>");
const cells = (row, columns) => Array.isArray(row) ? row : columns.map((column) => row?.[column]);

function tableHtml(columns, rows) {
  return `<table><thead><tr>${columns.map((column) => `<th>${escape(column)}</th>`).join("")}</tr></thead><tbody>${
    rows.map((row) => `<tr>${cells(row, columns).map((cell) => `<td>${escape(cell ?? "—")}</td>`).join("")}</tr>`).join("")
  }</tbody></table>`;
}

function chartData({slices, categories = [], series = [], spec}) {
  if (slices) return {columns: ["分类", "数值"], rows: slices.map(({name, value}) => [name, value])};
  if (!categories.length) {
    return {columns: ["系列", "数值"], rows: (spec?.option?.series || []).flatMap((entry) =>
      (entry.data || []).map((point) => [entry.name || "", JSON.stringify(point)]))};
  }
  return {columns: ["分类", ...series.map(({name}) => name)], rows: categories.map((label, index) =>
    [label, ...series.map(({values}) => values[index])])};
}

async function chartHtml(chart) {
  const {columns, rows} = chartData(chart);
  let image = "";
  let instance;
  try {
    await loadEcharts();
    instance = window.echarts.init(document.createElement("canvas"), null, {width: 840, height: 390});
    instance.setOption({...chart.spec.option, animation: false, backgroundColor: "#fff"});
    const png = instance.getDataURL({type: "png", pixelRatio: 2});
    if (png?.startsWith("data:image/png;base64,")) image = `<img alt="${escape(chart.title)}" src="${png}">`;
  } catch {
    // Preserve the chart's data if an offscreen renderer is unavailable.
  } finally { instance?.dispose(); }
  const source = chart.spec?.source_note;
  return image + tableHtml(columns, rows) + (source ? `<p>${paragraph(source)}</p>` : "");
}

function manifestBlock(item, idx) {
  const values = item.kind === "table" ? item.rows.slice(0, 12) :
    item.kind === "chart" ? (item.dimensions || [{chart: item}]).map(({chart}) => chartData(chart).rows.slice(0, 10)) : null;
  return {idx, kind: item.kind, title: item.title,
    content: item.content || item.summary || (values ? JSON.stringify(values).slice(0, 1200) : "")};
}

async function blockHtml(item) {
  let content;
  if (item.kind === "table") content = tableHtml(item.columns, item.rows) +
    [item.summary, item.footnote, item.sourceNote].filter(Boolean).map((note) => `<p>${paragraph(note)}</p>`).join("");
  else if (item.kind === "chart") content = item.dimensions
    ? (await Promise.all(item.dimensions.map(async ({label, summary, chart}) =>
      `<h4>${escape(label)}</h4><p>${paragraph(summary)}</p>${await chartHtml(chart)}`))).join("")
    : await chartHtml(item);
  else content = `<p>${paragraph(item.content)}</p>`;
  return `<section><h3>${escape(item.title)}</h3>${content}</section>`;
}

async function reportHtml(turn, items, plan) {
  const blocks = await Promise.all(items.map(blockHtml));
  const seen = new Set();
  const chapters = (plan?.sections || []).map(({heading, intro, blocks: indices}) => {
    const content = (Array.isArray(indices) ? indices : []).flatMap((index) => {
      const key = Number(index);
      if (seen.has(key) || !blocks[key]) return [];
      seen.add(key);
      return [blocks[key]];
    });
    return `<h2>${escape(heading)}</h2><p>${paragraph(intro)}</p>${content.join("")}`;
  }).join("");
  const title = plan?.title || turn.user || "分析报告";
  const appendix = blocks.filter((_, index) => !seen.has(index)).join("");
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>${escape(title)}</title>
<style>body{font:14px/1.65 Arial,"Microsoft YaHei",sans-serif;color:#222;max-width:960px;margin:2em auto;padding:0 1em}table{border-collapse:collapse;width:100%;margin:1em 0}td,th{border:1px solid #c6d0df;padding:.4em;text-align:left}th{background:#eaf1ff}img{max-width:100%;height:auto}section{margin:1.5em 0}</style></head>
<body><h1>${escape(title)}</h1>${plan?.summary ? `<h2>执行摘要</h2><p>${paragraph(plan.summary)}</p>` : ""}
${chapters}${plan && appendix ? "<h2>附录</h2>" : ""}${appendix}</body></html>`;
}

function download(html, name, type) {
  const link = document.createElement("a");
  const href = URL.createObjectURL(new Blob(["\uFEFF", html], {type: `${type};charset=utf-8`}));
  link.href = href;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(href), 60000);
}

function parentOrigin() {
  if (window.parent === window) return "";
  try { return new URL(document.referrer).origin; } catch { return ""; }
}

export default function Delivery({turn, items, index}) {
  const [pending, setPending] = useState("");
  const [notice, setNotice] = useState("");
  const [word, setWord] = useState(null);
  const stopWaiting = useRef(null);
  useEffect(() => () => stopWaiting.current?.(), []);
  const origin = parentOrigin();
  const fileName = `report-turn${index + 1}`;
  const perform = async (action) => {
    setPending(action);
    setNotice("");
    try {
      if (action === "word") {
        const plan = await requestJson("api/report/compose", {method: "POST", body: {blocks: items.map(manifestBlock)}});
        const html = await reportHtml(turn, items, plan);
        setWord({items, html});
        setNotice("Word 已生成，可以下载。");
      } else {
        const html = await reportHtml(turn, items);
        if (action === "html") download(html, fileName + ".html", "text/html");
        else {
          const quadrant = new URLSearchParams(window.location.search).get("quadrant");
          const req = globalThis.crypto?.randomUUID?.() || String(Date.now());
          const ack = new Promise((resolve, reject) => {
            const finish = () => { clearTimeout(timer); window.removeEventListener("message", receive); };
            const receive = (event) => {
              if (event.origin !== origin || event.source !== window.parent ||
                  event.data?.channel !== "cockpit-home-sync-ack" || event.data.req !== req) return;
              finish();
              resolve();
            };
            const timer = setTimeout(() => { finish(); reject(new Error("主页未确认同步，可重试。")); }, 4000);
            stopWaiting.current = finish;
            window.addEventListener("message", receive);
          });
          window.parent.postMessage({channel: "cockpit-home-sync", quadrant,
            source: quadrant ? "象限分析" : "通用AI助手", summary: turn.user.slice(0, 80),
            html, ts: new Date().toISOString(), req}, origin);
          await ack;
          setNotice("已同步到主页问题清单。");
        }
      }
    } catch (error) { setNotice(error.message); }
    finally { setPending(""); }
  };
  // A settled turn's content is immutable; compare the manifest when a restored
  // result is enriched so the download always matches the visible cards.
  const canDownload = word && JSON.stringify(word.items) === JSON.stringify(items);
  return <div className="ak-delivery">
    <div className="ak-inline-actions">
      <button type="button" className="ak-ghost" disabled={!!pending} onClick={() => perform("html")}>导出 HTML</button>
      <button type="button" className="ak-ghost" disabled={!!pending} onClick={() => canDownload
        ? download(word.html, fileName + ".doc", "application/msword") : perform("word")}>
        {canDownload ? "下载 Word" : "导出 Word"}</button>
      {origin ? <button type="button" className="ak-ghost" disabled={!!pending} onClick={() => perform("sync")}>同步到主页</button> : null}
    </div>
    {pending || notice ? <p role="status">{pending ? "正在准备报告…" : notice}</p> : null}
  </div>;
}
