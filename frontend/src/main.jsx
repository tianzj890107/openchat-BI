import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Button, Card, Collapse, ConfigProvider, Divider, Layout, List, Menu, Progress, Tag, Tooltip } from "antd";
import { ThoughtChain } from "@ant-design/x";
import { Bubble } from "@ant-design/x";
import shellDocument from "./shell.html?raw";
import {
  bootWorkbenchRuntime,
  fetchConversationSummaries,
} from "./runtime.js";
import {
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  PlusOutlined,
} from "@ant-design/icons";
import "antd/dist/reset.css";
import "./workbench.css";

const { Sider } = Layout;

const DECORATIVE_EMOJI_TOKEN = "(?:📌|📊|📎|🧭|📈|📉|📄|🧩|🧠|✅|⚠️|🔍|💡)";
function stripDecorativeAssistantMarkup(value) {
  let html = String(value == null ? "" : value);
  // New responses may still be plain Markdown when a history snapshot was
  // created by an older renderer. Remove icon-only bold fragments first.
  html = html.replace(
    new RegExp(`\\*\\*\\s*${DECORATIVE_EMOJI_TOKEN}(?:\\s*${DECORATIVE_EMOJI_TOKEN})*\\s*\\*\\*`, "gu"),
    "",
  );
  html = html.replace(
    new RegExp(`<strong>\\s*${DECORATIVE_EMOJI_TOKEN}(?:\\s*${DECORATIVE_EMOJI_TOKEN})*\\s*</strong>`, "gu"),
    "",
  );
  // Only remove a marker at the beginning of a rendered block, not emoji
  // that are part of a sentence, a table value, or a user-provided label.
  html = html.replace(
    new RegExp(`(>\\s*(?:<strong>)?)${DECORATIVE_EMOJI_TOKEN}+(?=\\s|<|$)`, "gu"),
    "$1",
  );
  return html;
}

/* Result badges use the same compact SVG language as the surrounding shell.
 * Keep these paths local to the React layer so both live and restored cards
 * can render the exact same glyph without depending on an icon font. */
function TypeGlyph({ variant }) {
  if (variant === "table") {
    return <span className="antd-type-glyph" aria-hidden="true"><svg fill="none" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M0 0h16v16H0z" /><path fillRule="evenodd" fill="currentColor" d="M10.152.857a.487.487 0 0 1 .2.124l3.324 3.323a.487.487 0 0 1 .156.407v8.623c0 .253-.044.488-.134.704-.09.216-.224.414-.403.593a1.821 1.821 0 0 1-.592.402c-.216.09-.45.135-.704.135h-8c-.253 0-.488-.045-.704-.134a1.823 1.823 0 0 1-.592-.403 1.82 1.82 0 0 1-.403-.593 1.822 1.822 0 0 1-.134-.704V2.668c0-.254.044-.488.134-.704.09-.216.224-.414.403-.593A1.82 1.82 0 0 1 3.295.97c.216-.09.45-.135.704-.135h5.956a.49.49 0 0 1 .197.023Zm2.68 4.31v8.167c0 .278-.069.486-.208.625-.139.14-.347.209-.625.209h-8c-.278 0-.486-.07-.625-.209-.139-.139-.208-.347-.208-.625V2.668c0-.278.07-.487.208-.625.139-.14.347-.209.625-.209h5.5v2.167c0 .161.028.31.085.448.057.137.143.263.257.377.114.114.24.2.377.256.137.057.287.086.448.086h2.166ZM10.5 4.002v-1.46l1.626 1.627h-1.46c-.055 0-.096-.014-.124-.042-.028-.028-.042-.07-.042-.125Zm-.132 3.317H5.634a.491.491 0 0 1-.5-.5.49.49 0 0 1 .277-.45.488.488 0 0 1 .223-.05h4.733a.492.492 0 0 1 .5.5.491.491 0 0 1-.5.5ZM5.634 9.684h4.733a.491.491 0 0 0 .5-.5.49.49 0 0 0-.278-.449.488.488 0 0 0-.222-.05H5.634a.492.492 0 0 0-.5.5.491.491 0 0 0 .5.5Z" data-follow-fill="currentColor" /></svg></span>;
  }
  if (variant === "bars") {
    return <span className="antd-type-glyph" aria-hidden="true"><svg fill="none" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M0 0h16v16H0z" /><path fill="currentColor" d="M6.5 14V2h3v12h-3ZM2 14V7h3v7H2Zm9 0V5h3v9h-3Z" data-follow-fill="currentColor" /></svg></span>;
  }
  if (variant === "pie") {
    return <span className="antd-type-glyph" aria-hidden="true"><svg fill="none" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M0 0h16v16H0z" /><path fillRule="evenodd" fill="currentColor" d="M3.055 3.055C4.372 1.737 6.02 1.052 8 1v8.167h6.89a6.813 6.813 0 0 1-1.945 3.778C11.628 14.263 9.98 14.948 8 15c-1.98-.052-3.628-.737-4.945-2.055C1.737 11.628 1.052 9.98 1 8c.052-1.98.737-3.628 2.055-4.945ZM14.964 8H9.167V1.036c1.557.156 2.873.771 3.95 1.847 1.207 1.208 1.835 2.72 1.883 4.534a8.009 8.009 0 0 1-.036.583Z" data-follow-fill="currentColor" /></svg></span>;
  }
  return null;
}

function AgentMark() {
  return <span className="antd-agent-mark" aria-hidden="true"><svg fill="none" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M0 0h16v16H0z" /><path fill="currentColor" d="M14.481 7.5h-3.523A3.008 3.008 0 0 0 8.5 5.042V1.519A6.501 6.501 0 0 1 14.481 7.5Zm0 1A6.5 6.5 0 0 1 8.5 14.481v-3.523A3.008 3.008 0 0 0 10.958 8.5h3.523ZM1.52 8.5h3.523A3.008 3.008 0 0 0 7.5 10.958v3.523A6.5 6.5 0 0 1 1.519 8.5h.001Zm0-1A6.501 6.501 0 0 1 7.5 1.519v3.523A3.008 3.008 0 0 0 5.042 7.5H1.519h.001Z" data-follow-fill="currentColor" /></svg></span>;
}

function resultGlyphVariant(label, kind = "") {
  const value = String(label || "").toLowerCase();
  if (/table|表格|表$/.test(value) || kind === "table") return "table";
  if (/line|bar/.test(value)) return "bars";
  if (/pie|chart/.test(value) || kind === "chart") return "pie";
  return null;
}

function cleanResultTypeLabel(label) {
  return String(label || "").replace(/^\s*[📊📈📉📋]+\s*/, "").trim();
}

const TYPE_GLYPH_MARKUP = Object.freeze({
  table: '<svg fill="none" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M0 0h16v16H0z"/><path fill-rule="evenodd" fill="currentColor" d="M10.152.857a.487.487 0 0 1 .2.124l3.324 3.323a.487.487 0 0 1 .156.407v8.623c0 .253-.044.488-.134.704-.09.216-.224.414-.403.593a1.821 1.821 0 0 1-.592.402c-.216.09-.45.135-.704.135h-8c-.253 0-.488-.045-.704-.134a1.823 1.823 0 0 1-.592-.403 1.82 1.82 0 0 1-.403-.593 1.822 1.822 0 0 1-.134-.704V2.668c0-.254.044-.488.134-.704.09-.216.224-.414.403-.593A1.82 1.82 0 0 1 3.295.97c.216-.09.45-.135.704-.135h5.956a.49.49 0 0 1 .197.023Zm2.68 4.31v8.167c0 .278-.069.486-.208.625-.139.14-.347.209-.625.209h-8c-.278 0-.486-.07-.625-.209-.139-.139-.208-.347-.208-.625V2.668c0-.278.07-.487.208-.625.139-.14.347-.209.625-.209h5.5v2.167c0 .161.028.31.085.448.057.137.143.263.257.377.114.114.24.2.377.256.137.057.287.086.448.086h2.166ZM10.5 4.002v-1.46l1.626 1.627h-1.46c-.055 0-.096-.014-.124-.042-.028-.028-.042-.07-.042-.125Zm-.132 3.317H5.634a.491.491 0 0 1-.5-.5.49.49 0 0 1 .277-.45.488.488 0 0 1 .223-.05h4.733a.492.492 0 0 1 .5.5.491.491 0 0 1-.5.5ZM5.634 9.684h4.733a.491.491 0 0 0 .5-.5.49.49 0 0 0-.278-.449.488.488 0 0 0-.222-.05H5.634a.492.492 0 0 0-.5.5.491.491 0 0 0 .5.5Z" data-follow-fill="currentColor"/></svg>',
  pie: '<svg fill="none" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M0 0h16v16H0z"/><path fill-rule="evenodd" fill="currentColor" d="M3.055 3.055C4.372 1.737 6.02 1.052 8 1v8.167h6.89a6.813 6.813 0 0 1-1.945 3.778C11.628 14.263 9.98 14.948 8 15c-1.98-.052-3.628-.737-4.945-2.055C1.737 11.628 1.052 9.98 1 8c.052-1.98.737-3.628 2.055-4.945ZM14.964 8H9.167V1.036c1.557.156 2.873.771 3.95 1.847 1.207 1.208 1.835 2.72 1.883 4.534a8.009 8.009 0 0 1-.036.583Z" data-follow-fill="currentColor"/></svg>',
  bars: '<svg fill="none" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M0 0h16v16H0z"/><path fill="currentColor" d="M6.5 14V2h3v12h-3ZM2 14V7h3v7H2Zm9 0V5h3v9h-3Z" data-follow-fill="currentColor"/></svg>',
});

function decorateResultTypeBadge(node, kind = "") {
  if (!node || node.dataset.typeGlyphReady === "1") return;
  const raw = node.textContent || "";
  const variant = resultGlyphVariant(raw, kind);
  if (!variant || !TYPE_GLYPH_MARKUP[variant]) return;
  node.replaceChildren();
  const icon = document.createElement("span");
  icon.className = "antd-type-glyph";
  icon.setAttribute("aria-hidden", "true");
  icon.innerHTML = TYPE_GLYPH_MARKUP[variant];
  node.append(icon, document.createTextNode(cleanResultTypeLabel(raw)));
  node.classList.add("antd-type-badge");
  node.dataset.typeGlyphReady = "1";
}

/* Semantic result badges share the same SVG language as chart/table badges.
 * The paths intentionally use currentColor so the glyph always follows the
 * badge color in both the conversation and dashboard surfaces. */
const SEMANTIC_GLYPH_MARKUP = Object.freeze({
  rootcause: '<svg fill="none" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M0 0h16v16H0z"/><path fill-rule="evenodd" fill="currentColor" d="m14.624 13.921-1.952-1.952c.692-.845 1.154-1.744 1.388-2.7.15-.613.205-1.25.167-1.91-.1-1.686-.79-3.15-2.07-4.389-.826-.729-1.716-1.228-2.67-1.498a6.429 6.429 0 0 0-1.877-.236 6.395 6.395 0 0 0-1.883.313c-.935.306-1.797.837-2.585 1.593-.756.788-1.287 1.65-1.594 2.585a6.394 6.394 0 0 0-.312 1.883 6.43 6.43 0 0 0 .236 1.876c.27.955.769 1.845 1.498 2.67.744.769 1.568 1.325 2.473 1.668a6.437 6.437 0 0 0 1.917.402c1.687.1 3.224-.419 4.609-1.554l1.952 1.953c.104.093.221.14.352.14a.47.47 0 0 0 .344-.148.473.473 0 0 0 .148-.344.513.513 0 0 0-.14-.352Zm-4.268-1.346c-.77.413-1.643.633-2.62.659-1.563-.042-2.86-.578-3.89-1.61a5.413 5.413 0 0 1-.95-1.269c-.414-.77-.633-1.642-.66-2.62.042-1.562.579-2.858 1.61-3.89a5.412 5.412 0 0 1 1.27-.95c.768-.413 1.642-.632 2.62-.658 1.561.042 2.858.578 3.89 1.609.385.386.702.809.95 1.27.413.769.632 1.642.658 2.62-.042 1.561-.578 2.858-1.609 3.889a5.413 5.413 0 0 1-1.27.95Z" data-follow-fill="currentColor"/></svg>',
  conclusion: '<svg fill="none" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M0 0h16v16H0z"/><path stroke-linejoin="round" stroke-linecap="round" stroke="currentColor" d="m6.443 2.958 1.414 1.414M9.743 1.59v2m3.3-.633-1.415 1.414m2.781 1.885h-2m.634 3.3-1.415-1.414m-1.885 2.781v-2m-3.3.633 1.414-1.414M5.076 6.257h2m-.863 3.53L1.59 14.41" data-follow-stroke="currentColor"/></svg>',
  actions: '<svg fill="none" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M0 0h16v16H0z"/><path fill="currentColor" d="M6 15v-1h3.001v1h-3Zm7-8.5a5.48 5.48 0 0 1-2.005 4.241c-.599.494-.995 1.193-.995 1.97V13H5v-.224c0-.75-.303-1.49-.894-1.953A5.493 5.493 0 0 1 2.1 5.444c.396-2.132 2.092-3.877 4.215-4.32A5.506 5.506 0 0 1 13 6.5ZM4.5 7c0-2.067 1.186-3.5 3-3.5v-1c-2.413 0-4 1.918-4 4.5h1Z" data-follow-fill="currentColor"/></svg>',
});

function semanticBadgeVariant(node) {
  if (!node) return null;
  if (node.classList.contains("rootcause")) return "rootcause";
  if (node.classList.contains("conclusion")) return "conclusion";
  if (node.classList.contains("actions")) return "actions";
  return null;
}

function decorateSemanticBadge(node) {
  if (!node || node.dataset.semanticGlyphReady === "1") return;
  const variant = semanticBadgeVariant(node);
  if (!variant || !SEMANTIC_GLYPH_MARKUP[variant]) return;
  const raw = node.textContent || "";
  const label = raw.replace(/^\s*[📌🔍🔎💡]\s*/u, "").trim();
  node.replaceChildren();
  const icon = document.createElement("span");
  icon.className = "antd-semantic-glyph";
  icon.setAttribute("aria-hidden", "true");
  icon.innerHTML = SEMANTIC_GLYPH_MARKUP[variant];
  node.append(icon, document.createTextNode(label));
  node.dataset.semanticGlyphReady = "1";
}

function GridNavIcon() {
  return <span className="antd-custom-nav-icon" aria-hidden="true"><svg fill="none" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M0 0h16v16H0z" /><path fill="#8F9299" d="M2.5 7a.5.5 0 0 1-.5-.5V2.501a.5.5 0 0 1 .5-.5h4a.5.5 0 0 1 .5.5V6.5a.5.5 0 0 1-.5.5h-4Zm7 0a.5.5 0 0 1-.5-.5V2.501a.5.5 0 0 1 .5-.5h3.999a.5.5 0 0 1 .5.5V6.5a.5.5 0 0 1-.5.5H9.5Zm-7 7a.5.5 0 0 1-.5-.5v-4a.5.5 0 0 1 .5-.5h4a.5.5 0 0 1 .5.5v4a.5.5 0 0 1-.5.5h-4Zm7 0a.5.5 0 0 1-.5-.5v-4a.5.5 0 0 1 .5-.5h3.999a.5.5 0 0 1 .5.5v4a.5.5 0 0 1-.5.5H9.5Z" data-follow-fill="#8F9299" /></svg></span>;
}

const FEATURE_OUTLINE_D = Object.freeze({
  ontology: "M15.142 9.191c-.892.966-1.83 1.764-2.816 2.395C10.854 12.53 9.412 13 8 13c-1.412 0-2.854-.471-4.326-1.414Q2.196 10.64.858 9.191a1.761 1.761 0 0 1-.368-.59A1.732 1.732 0 0 1 .387 8c0-.213.035-.413.103-.6.079-.214.201-.41.368-.591Q2.196 5.36 3.674 4.414C5.146 3.47 6.588 3 8 3c1.412 0 2.854.471 4.326 1.414.985.63 1.924 1.429 2.816 2.395.167.18.29.377.368.59.068.188.103.388.103.601 0 .213-.035.413-.103.6-.079.214-.201.41-.368.591Z",
  model: "m14.7 8.93-2.549 4.333a1.821 1.821 0 0 1-.66.678 1.82 1.82 0 0 1-.92.225H5.429a1.82 1.82 0 0 1-.919-.225 1.82 1.82 0 0 1-.66-.678L1.3 8.929A1.818 1.818 0 0 1 1.027 8c0-.31.09-.62.273-.93l2.55-4.333a1.82 1.82 0 0 1 .66-.678c.263-.15.57-.226.92-.226h5.14c.35 0 .657.076.92.226.263.15.484.377.661.678L14.7 7.07c.182.31.273.62.273.93 0 .31-.09.62-.273.93Z",
});

function FeatureGlyph({ kind }) {
  // The first path is a transparent SVG canvas. Keeping the canvas fill none
  // prevents the icon from becoming a solid square when the menu color is
  // inherited by the SVG.
  const common = { fill: "none", xmlns: "http://www.w3.org/2000/svg", viewBox: "0 0 16 16", "aria-hidden": true };
  if (FEATURE_OUTLINE_D[kind]) {
    return <span className={`antd-feature-icon antd-feature-icon-${kind}`}><svg {...common}>
      <path fill="none" stroke="currentColor" strokeWidth="1.25" strokeLinejoin="round" strokeLinecap="round" d={FEATURE_OUTLINE_D[kind]} />
      <circle cx="8" cy="8" r={kind === "ontology" ? "2.2" : "1.67"} fill="none" stroke="currentColor" strokeWidth="1.25" />
    </svg></span>;
  }
  const path = {
    bars: <path strokeLinejoin="round" strokeLinecap="round" stroke="currentColor" d="m6.443 2.958 1.414 1.414M9.743 1.59v2m3.3-.633-1.415 1.414m2.781 1.885h-2m.634 3.3-1.415-1.414m-1.885 2.781v-2m-3.3.633 1.414-1.414M5.076 6.257h2m-.863 3.53L1.59 14.41" data-follow-stroke="currentColor" />,
    report: <path fillRule="evenodd" fill="currentColor" d="M14.114 2.32c.171.076.326.185.456.32A1.39 1.39 0 0 1 15 3.7v4a.5.5 0 0 1-1 0V6.49H2v5.64a.421.421 0 0 0 .47.45h5.09a.51.51 0 0 1 .5.5.529.529 0 0 1-.15.34.497.497 0 0 1-.35.14H2.43a1.42 1.42 0 0 1-1-.43 1.396 1.396 0 0 1-.43-1V3.68a1.392 1.392 0 0 1 .47-1.04 1.43 1.43 0 0 1 1-.44h11.1c.187.004.372.045.544.12ZM2 5.49h12V3.68a.493.493 0 0 0-.29-.444.453.453 0 0 0-.18-.036H2.47a.42.42 0 0 0-.47.48v1.81Zm11.982 5.564a2.5 2.5 0 0 1-.322 1.026l.89.85a.495.495 0 0 1-.34.86.463.463 0 0 1-.34-.13l-.87-.81a2.384 2.384 0 0 1-1.5.48 2.492 2.492 0 0 1-2.16-3.747 2.488 2.488 0 0 1 2.17-1.233 2.37 2.37 0 0 1 1.76.73 2.5 2.5 0 0 1 .712 1.974Zm-1.897 1.133a1.499 1.499 0 0 0 .485-2.448 1.473 1.473 0 0 0-1.06-.44 1.441 1.441 0 0 0-1.06.44 1.5 1.5 0 0 0 0 2.12 1.44 1.44 0 0 0 1.06.44 1.47 1.47 0 0 0 .575-.111Z" data-follow-fill="currentColor" />,
    ontology: <path fill="none" stroke="currentColor" strokeWidth="1.25" strokeLinejoin="round" strokeLinecap="round" d="M15.142 9.191c-.892.966-1.83 1.764-2.816 2.395C10.854 12.53 9.412 13 8 13c-1.412 0-2.854-.471-4.326-1.414Q2.196 10.64.858 9.191a1.761 1.761 0 0 1-.368-.59A1.732 1.732 0 0 1 .387 8c0-.213.035-.413.103-.6.079-.214.201-.41.368-.591Q2.196 5.36 3.674 4.414C5.146 3.47 6.588 3 8 3c1.412 0 2.854.471 4.326 1.414.985.63 1.924 1.429 2.816 2.395.167.18.29.377.368.59.068.188.103.388.103.601 0 .213-.035.413-.103.6-.079.214-.201.41-.368.591ZM10.75 8c0 .38-.067.731-.201 1.056-.135.324-.336.62-.604.889-.269.268-.565.47-.89.604A2.73 2.73 0 0 1 8 10.75a2.73 2.73 0 0 1-1.056-.201 2.732 2.732 0 0 1-.889-.604 2.735 2.735 0 0 1-.604-.89A2.733 2.733 0 0 1 5.25 8c0-.38.067-.731.201-1.056.135-.324.336-.62.604-.889.269-.268.565-.47.89-.604A2.731 2.731 0 0 1 8 5.25c.38 0 .732.067 1.056.201.324.135.62.336.889.604.268.269.47.565.604.89.134.324.201.675.201 1.055Zm-1 0c0-.242-.043-.466-.128-.672a1.737 1.737 0 0 0-.385-.566c-.17-.17-.359-.298-.565-.384A1.737 1.737 0 0 0 8 6.25c-.242 0-.466.043-.672.128a1.741 1.741 0 0 0-.565.384c-.171.171-.3.36-.385.566-.085.206-.128.43-.128.672 0 .242.043.466.128.672.086.206.214.395.385.566.17.17.359.298.565.384.206.085.43.128.672.128.242 0 .466-.043.672-.128.206-.086.395-.214.565-.384.171-.171.3-.36.385-.566.085-.206.128-.43.128-.672Z" data-follow-stroke="currentColor" />,
    syslog: <path fillRule="evenodd" fill="currentColor" d="M15.167 8c0 .99-.175 1.907-.525 2.751a7.118 7.118 0 0 1-1.574 2.317c-.7.7-1.472 1.224-2.317 1.574A7.12 7.12 0 0 1 8 15.167c-.99 0-1.907-.175-2.751-.525a7.122 7.122 0 0 1-2.317-1.574 7.118 7.118 0 0 1-1.574-2.317 7.116 7.116 0 0 1-.525-2.75c0-.99.175-1.907.525-2.752a7.117 7.117 0 0 1 1.574-2.316c.7-.7 1.472-1.225 2.317-1.575a7.118 7.118 0 0 1 2.75-.525c.99 0 1.907.175 2.752.525.845.35 1.617.875 2.317 1.575.7.7 1.224 1.471 1.574 2.316.35.845.525 1.762.525 2.751Zm-1 0c0-.851-.15-1.64-.452-2.367A6.126 6.126 0 0 0 12.36 3.64a6.124 6.124 0 0 0-1.993-1.355A6.125 6.125 0 0 0 8 1.833c-.852 0-1.64.151-2.367.452A6.124 6.124 0 0 0 3.639 3.64a6.124 6.124 0 0 0-1.354 1.993A6.126 6.126 0 0 0 1.833 8c0 .852.15 1.64.452 2.367a6.125 6.125 0 0 0 1.354 1.994 6.124 6.124 0 0 0 1.994 1.354A6.123 6.123 0 0 0 8 14.167c.851 0 1.64-.15 2.367-.452a6.124 6.124 0 0 0 1.993-1.354 6.124 6.124 0 0 0 1.355-1.994A6.125 6.125 0 0 0 14.167 8ZM8.4 8.244h3.5a.5.5 0 0 1 0 1h-4a.5.5 0 0 1-.5-.5v-4.5a.5.5 0 0 1 1 0v4Z" data-follow-fill="currentColor" />,
    adapt: <path fill="currentColor" d="M7 7.126V1.5a.5.5 0 0 1 .5-.501l3 .001a.5.5 0 1 1 0 1H8v2h2.5a.5.5 0 1 1 0 1H8v2a4 4 0 1 1-1 .126ZM8 14a3.001 3.001 0 1 0 0-6.002A3.001 3.001 0 0 0 8 14Z" data-follow-fill="currentColor" />,
    sources: <path fillRule="evenodd" fill="currentColor" d="M12.654 14.497v.003h-10a1.82 1.82 0 0 1-.704-.134 1.82 1.82 0 0 1-.592-.403 1.823 1.823 0 0 1-.403-.593 1.82 1.82 0 0 1-.134-.703V3.333c0-.253.044-.487.134-.703.09-.216.224-.414.402-.593.18-.18.377-.313.593-.403.216-.09.45-.134.704-.134h2.709c.286 0 .546.055.781.165.235.11.444.275.627.495l1.067 1.28c.017.02.036.035.057.045.022.01.045.015.071.015h4.688c.253 0 .488.045.704.134.216.09.413.224.592.403.18.179.314.377.403.593.09.216.134.414.134.703V7.23a2 2 0 0 1 .272.275c.184.224.307.463.37.716.064.254.067.523.01.806l-.8 4c-.043.214-.117.41-.223.586a1.822 1.822 0 0 1-.412.473c-.17.138-.35.242-.544.311-.16.057-.329.09-.506.1ZM1.821 11.09V3.333c0-.278.069-.486.208-.625.139-.139.347-.208.625-.208h2.709c.13 0 .248.025.355.075.107.05.202.125.285.225L7.07 4.08c.117.14.25.245.399.315.15.07.315.105.497.105h4.688c.278 0 .486.07.625.208.139.14.208.348.208.625v1.505a2.13 2.13 0 0 0-.146-.005H4.29c-.481 0-.87.117-1.168.351-.297.234-.502.586-.614 1.054L1.82 11.09Zm12.338-2.26a.826.826 0 0 0-.005-.366.828.828 0 0 0-.168-.326.827.827 0 0 0-.286-.228.828.828 0 0 0-.358-.077H4.288c-.219 0-.396.054-.53.16-.136.106-.229.266-.28.479l-.962 4a.828.828 0 0 0-.009.374c.026.118.08.23.164.336.084.106.18.186.289.239.11.053.231.079.366.079h9.214c.228 0 .41-.056.546-.168.137-.111.227-.279.272-.502l.8-4Z" data-follow-fill="currentColor" />,
    model: <path fill="none" stroke="currentColor" strokeWidth="1.25" strokeLinejoin="round" strokeLinecap="round" d="m14.7 8.93-2.549 4.333a1.821 1.821 0 0 1-.66.678 1.82 1.82 0 0 1-.92.225H5.429a1.82 1.82 0 0 1-.919-.225 1.82 1.82 0 0 1-.66-.678L1.3 8.929A1.818 1.818 0 0 1 1.027 8c0-.31.09-.62.273-.93l2.55-4.333a1.82 1.82 0 0 1 .66-.678c.263-.15.57-.226.92-.226h5.14c.35 0 .657.076.92.226.263.15.484.377.661.678L14.7 7.07c.182.31.273.62.273.93 0 .31-.09.62-.273.93Zm-4.533-.93c0 .3-.053.576-.159.832a2.157 2.157 0 0 1-.476.7c-.211.211-.445.37-.7.476a2.152 2.152 0 0 1-.832.159c-.3 0-.576-.053-.832-.159a2.16 2.16 0 0 1-.7-.476 2.152 2.152 0 0 1-.476-.7A2.152 2.152 0 0 1 5.833 8c0-.3.053-.576.159-.832.106-.255.264-.489.476-.7.211-.212.445-.37.7-.476.256-.106.533-.159.832-.159.3 0 .576.053.832.159.255.105.489.264.7.476.211.211.37.445.476.7.106.256.159.533.159.832Zm-1 0c0-.161-.029-.31-.086-.448a1.158 1.158 0 0 0-.256-.377c-.114-.114-.24-.2-.377-.256A1.16 1.16 0 0 0 8 6.833c-.161 0-.31.029-.448.086a1.155 1.155 0 0 0-.377.256c-.114.114-.2.24-.256.377A1.16 1.16 0 0 0 6.833 8c0 .16.029.31.086.448.057.137.142.263.256.377.114.114.24.2.377.256.137.057.287.086.448.086.16 0 .31-.029.448-.086.137-.057.263-.142.377-.256.114-.114.2-.24.256-.377.057-.138.086-.287.086-.448Z" data-follow-stroke="currentColor" />,
    roles: <path fillRule="evenodd" fill="currentColor" d="M10.935 5.882c.154-.373.232-.778.232-1.215 0-.438-.078-.843-.232-1.216a3.146 3.146 0 0 0-.696-1.023c-.309-.31-.65-.542-1.023-.696A3.146 3.146 0 0 0 8 1.5c-.437 0-.842.077-1.216.232a3.146 3.146 0 0 0-1.023.696c-.31.309-.541.65-.696 1.023a3.145 3.145 0 0 0-.232 1.216c0 .437.078.842.232 1.215.155.374.387.715.696 1.024.31.31.65.54 1.023.696.374.154.779.231 1.216.231.437 0 .843-.077 1.216-.231a3.148 3.148 0 0 0 1.023-.696c.31-.31.541-.65.696-1.024ZM10.008 3.835c.106.255.159.532.159.832 0 .299-.053.576-.159.832a2.153 2.153 0 0 1-.476.7c-.211.211-.445.37-.7.476A2.149 2.149 0 0 1 8 6.833c-.3 0-.576-.052-.832-.158a2.152 2.152 0 0 1-.7-.476 2.152 2.152 0 0 1-.476-.7 2.152 2.152 0 0 1-.159-.832c0-.3.053-.577.16-.832.105-.255.263-.489.475-.7.212-.212.445-.37.7-.476.256-.106.533-.159.832-.159.3 0 .576.053.832.159.255.105.489.264.7.476.212.211.37.445.476.7ZM1.646 14.353A.481.481 0 0 0 2 14.5h12a.481.481 0 0 0 .354-.146A.482.482 0 0 0 14.5 14v-.4c0-1.574-.115-2.586-.345-3.038a3.154 3.154 0 0 0-.58-.804 3.152 3.152 0 0 0-.804-.58c-.452-.23-1.464-.345-3.038-.345H6.267c-1.574 0-2.586.115-3.038.345a3.152 3.152 0 0 0-.804.58c-.23.23-.424.499-.58.804-.23.452-.345 1.464-.345 3.038v.4c0 .138.049.256.146.354ZM2.5 13.5h11c-.004-1.354-.082-2.182-.236-2.484a2.154 2.154 0 0 0-.397-.55 2.156 2.156 0 0 0-.55-.397c-.31-.157-1.17-.236-2.584-.236H6.267c-1.414 0-2.275.079-2.584.236a2.156 2.156 0 0 0-.55.397c-.158.158-.29.341-.397.55-.153.302-.232 1.13-.236 2.484Z" data-follow-fill="currentColor" />,
    memory: <path fillRule="evenodd" fill="currentColor" d="M12.078 4.328c.326.365.602.774.828 1.228a.495.495 0 0 0 .668.226h.002a.495.495 0 0 0 .226-.669v-.002a6.49 6.49 0 0 0-.981-1.453 6.499 6.499 0 0 0-1.373-1.155 6.444 6.444 0 0 0-1.611-.738 6.476 6.476 0 0 0-1.86-.265c-.667 0-1.305.095-1.913.284a6.341 6.341 0 0 0-1.537.72 6.484 6.484 0 0 0-1.38 1.184V2.667a.49.49 0 0 0-.5-.5.49.49 0 0 0-.5.5v2.632a.492.492 0 0 0 .19.43c.025.02.053.037.082.051l.005.003h.001c.035.017.07.03.109.038a.467.467 0 0 0 .154.012h2.219a.495.495 0 0 0 .5-.497v-.003a.495.495 0 0 0-.498-.5H3.52a5.406 5.406 0 0 1 1.546-1.486 5.34 5.34 0 0 1 1.28-.602A5.396 5.396 0 0 1 7.977 2.5c.55 0 1.077.076 1.581.227.472.14.923.348 1.355.621.441.28.83.606 1.165.98Zm-8.984 6.116c.226.454.502.863.828 1.228.335.374.724.7 1.165.98.432.273.883.48 1.355.621a5.478 5.478 0 0 0 1.581.227c.57 0 1.113-.082 1.631-.245.446-.14.872-.34 1.28-.602a5.476 5.476 0 0 0 1.546-1.486h-1.387a.49.49 0 0 1-.449-.277.488.488 0 0 1-.05-.223.491.491 0 0 1 .5-.5h2.219a.493.493 0 0 1 .263.05.491.491 0 0 1 .204.185.492.492 0 0 1 .073.305v2.629a.495.495 0 0 1-.5.497h-.002a.495.495 0 0 1-.498-.5v-1.02a6.415 6.415 0 0 1-1.38 1.182 6.33 6.33 0 0 1-1.537.72 6.39 6.39 0 0 1-1.913.285 6.47 6.47 0 0 1-1.86-.265 6.444 6.444 0 0 1-1.61-.738 6.5 6.5 0 0 1-1.374-1.155 6.49 6.49 0 0 1-.98-1.453.49.49 0 0 1 .048-.525.487.487 0 0 1 .177-.145.49.49 0 0 1 .526.048c.06.045.108.104.144.177Z" data-follow-fill="currentColor" />,
    analyst: <path fill="currentColor" d="M9.824 8.264A6.5 6.5 0 0 1 14.5 14.5h-13a6.498 6.498 0 0 1 4.676-6.236L8 11l1.824-2.736ZM11.25 4.75a3.25 3.25 0 1 1-6.5 0 3.25 3.25 0 0 1 6.5 0Z" data-follow-fill="currentColor" />,
  };
  return <span className={`antd-feature-icon antd-feature-icon-${kind}`}><svg {...common}><path fill="none" d="M0 0h16v16H0z" />{path[kind] || path.bars}</svg></span>;
}

const navItems = [
  { key: "data", view: "workspace", label: "智能分析", icon: <FeatureGlyph kind="bars" /> },
  { key: "report", view: "workspace", label: "报表分析", icon: <FeatureGlyph kind="report" /> },
  { type: "group", label: "内容" },
  { key: "ontology", view: "ontology", label: "本体内容", icon: <FeatureGlyph kind="ontology" /> },
  { key: "syslog", view: "syslog", label: "系统调用记录", icon: <FeatureGlyph kind="syslog" /> },
  { type: "divider" },
  { type: "group", label: "设置" },
  { key: "ontology-adapt", view: "ontology-adapt", label: "本体适配", icon: <FeatureGlyph kind="adapt" /> },
  { key: "sources", view: "sources", label: "数据源", icon: <FeatureGlyph kind="sources" /> },
  { key: "model", view: "model", label: "模型参数", icon: <FeatureGlyph kind="model" /> },
  { key: "roles", view: "roles", label: "角色选择", icon: <FeatureGlyph kind="roles" /> },
];

function getRuntimeButton(key) {
  const bridge = document.getElementById("sidebar");
  if (!bridge) return null;
  if (key === "data" || key === "report") {
    return bridge.querySelector(`.mode-btn[data-mode="${key}"]`);
  }
  return bridge.querySelector(`[data-view="${key}"]`);
}

function dispatchRuntime(key) {
  const button = getRuntimeButton(key);
  if (button) button.click();
}

function readRecent() {
  const list = document.getElementById("recent-list");
  if (!list) return [];
  return [...list.querySelectorAll(".recent-item")].map((node, index) => ({
    key: node.dataset?.cid || `recent-${index}`,
    title: node.querySelector(".recent-title")?.textContent?.trim() || node.textContent.trim(),
    updatedAt: node.dataset?.updatedAt || "",
    active: node.classList.contains("active"),
    node,
  }));
}

async function fetchRecent(mode = "data") {
  const conversations = await fetchConversationSummaries(mode);
  const activeIds = new Set([...document.querySelectorAll("#recent-list .recent-item.active")].map((node) => node.dataset?.cid));
  return conversations.map((item) => ({
    key: item.id,
    cid: item.id,
    title: item.title || "未命名对话",
    firstUserQuestion: item.first_user_question || "",
    updatedAt: item.updated_at || item.created_at || "",
    turnCount: Number(item.turn_count || 0),
    active: activeIds.has(item.id),
  }));
}

function recentItemFromSummary(item, activeIds = new Set()) {
  return {
    key: item.id,
    cid: item.id,
    title: item.title || "未命名对话",
    updatedAt: item.updated_at || item.created_at || "",
    turnCount: Number(item.turn_count || 0),
    active: activeIds.has(item.id),
  };
}

function recentTimeLabel(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function requestRecentRefresh(mode = document.body.dataset.mode || "data") {
  window.dispatchEvent(new CustomEvent("bi-conversations-retry", { detail: { mode } }));
}

function routeUsesSingleColumn() {
  const params = new URLSearchParams(window.location.search);
  const value = String(params.get("layout") || params.get("columns") || "").toLowerCase();
  return ["1", "one", "single", "single-column"].includes(value)
    || /\/(?:one|single)(?:\/)?$/.test(window.location.pathname);
}

function Sidebar() {
  const [sidebarLevel, setSidebarLevel] = useState(
    routeUsesSingleColumn()
      ? 1
      : document.body.classList.contains("sidebar-collapsed") ? 1 : 0,
  );
  const collapsed = sidebarLevel > 0;
  const [recent, setRecent] = useState(readRecent);
  const [recentStatus, setRecentStatus] = useState("loading");
  const [active, setActive] = useState("data");

  useEffect(() => {
    let disposed = false;
    const refresh = async (mode = document.body.dataset.mode || "data") => {
      if (!disposed) {
        setRecentStatus("loading");
        setRecent([]);
      }
      try {
        const items = await fetchRecent(mode);
        if (!disposed) {
          setRecent(items);
          setRecentStatus(items.length ? "success" : "empty");
        }
      } catch (_) {
        if (!disposed) {
          setRecent([]);
          setRecentStatus("error");
        }
      }
    };
    refresh();
    const onUpdated = (event) => {
      // The shared runtime coordinator publishes the already-fetched list.
      // Do not turn the event into a second GET request.
      const eventMode = event.detail?.mode || "data";
      // Both mode caches share this event channel. A report-mode empty result
      // must never replace the intelligent-analysis history (and vice versa).
      if (eventMode !== (document.body.dataset.mode || "data")) return;
      if (Array.isArray(event.detail?.conversations)) {
        const activeIds = new Set([...document.querySelectorAll("#recent-list .recent-item.active")].map((node) => node.dataset?.cid));
        setRecent(event.detail.conversations.map((item) => recentItemFromSummary(item, activeIds)));
        setRecentStatus(event.detail.status || (event.detail.conversations.length ? "success" : "empty"));
      }
    };
    const onMode = (event) => {
      refresh(event.detail?.mode || document.body.dataset.mode || "data");
    };
    window.addEventListener("bi-conversations-updated", onUpdated);
    window.addEventListener("bi-mode-changed", onMode);
    const onRetry = (event) => refresh(event.detail?.mode || document.body.dataset.mode || "data");
    window.addEventListener("bi-conversations-retry", onRetry);
    return () => {
      disposed = true;
      window.removeEventListener("bi-conversations-updated", onUpdated);
      window.removeEventListener("bi-mode-changed", onMode);
      window.removeEventListener("bi-conversations-retry", onRetry);
    };
  }, []);

  // Keep the shell selection in sync with the legacy runtime router. In
  // particular, opening a history row is still a data/report workspace view;
  // it must clear the previous “记忆管理” selection instead of leaving that
  // button permanently blue.
  useEffect(() => {
    const onMode = (event) => setActive(event.detail?.mode || document.body.dataset.mode || "data");
    window.addEventListener("bi-mode-changed", onMode);
    return () => window.removeEventListener("bi-mode-changed", onMode);
  }, []);
  // Let the history list use all available height when it fits. If the full
  // navigation content overflows the sidebar, cap the list at six rows so the
  // outer surface can reveal that complete window before inner scrolling.
  useEffect(() => {
    if (collapsed) return undefined;
    const root = document.querySelector("#antd-sidebar-root");
    const outer = root?.querySelector(".antd-sidebar-scroll");
    const inner = root?.querySelector(".antd-recent-list");
    if (!outer || !inner) return undefined;

    let frame = 0;
    const syncRecentWindow = () => {
      window.cancelAnimationFrame(frame);
      inner.classList.remove("antd-recent-list-capped");
      frame = window.requestAnimationFrame(() => {
        if (!inner.isConnected) return;
        const hasHistory = !inner.querySelector(".antd-recent-empty");
        const needsOuterScroll = outer.scrollHeight > outer.clientHeight + 1;
        inner.classList.toggle("antd-recent-list-capped", hasHistory && needsOuterScroll);
      });
    };

    syncRecentWindow();
    const resizeObserver = typeof ResizeObserver === "function"
      ? new ResizeObserver(syncRecentWindow)
      : null;
    resizeObserver?.observe(outer);
    window.addEventListener("resize", syncRecentWindow);
    return () => {
      window.cancelAnimationFrame(frame);
      resizeObserver?.disconnect();
      window.removeEventListener("resize", syncRecentWindow);
      inner.classList.remove("antd-recent-list-capped");
    };
  }, [collapsed, recent.length]);

  // The history list is a nested scroll surface. Keep the outer sidebar in
  // control until the complete six-row history window is visible; otherwise a
  // partially visible list can consume the wheel and make navigation stick.
  useEffect(() => {
    if (collapsed) return undefined;
    const root = document.querySelector("#antd-sidebar-root");
    const outer = root?.querySelector(".antd-sidebar-scroll");
    const inner = root?.querySelector(".antd-recent-list");
    if (!outer || !inner) return undefined;

    const onWheel = (event) => {
      const delta = Number(event.deltaY || 0);
      if (!delta) return;
      const outerMax = Math.max(0, outer.scrollHeight - outer.clientHeight);
      const outerCanMove = delta > 0
        ? outer.scrollTop < outerMax - 1
        : outer.scrollTop > 1;
      if (!outerCanMove) return;

      const historyTarget = event.target instanceof Element
        ? event.target.closest(".antd-recent-list")
        : null;
      if (historyTarget === inner) {
        const outerRect = outer.getBoundingClientRect();
        const innerRect = inner.getBoundingClientRect();
        const historyWindowFullyVisible =
          innerRect.top >= outerRect.top - 1 &&
          innerRect.bottom <= outerRect.bottom + 1;
        const innerMax = Math.max(0, inner.scrollHeight - inner.clientHeight);
        const innerCanMove = delta > 0
          ? inner.scrollTop < innerMax - 1
          : inner.scrollTop > 1;

        if (historyWindowFullyVisible && innerCanMove) return;
      }

      event.preventDefault();
      outer.scrollTop = Math.max(0, Math.min(outerMax, outer.scrollTop + delta));
    };

    // Capture makes this run before the nested list's native wheel handling.
    outer.addEventListener("wheel", onWheel, { passive: false, capture: true });
    return () => outer.removeEventListener("wheel", onWheel, true);
  }, [collapsed]);

  useEffect(() => {
    document.body.classList.toggle("sidebar-collapsed", collapsed);
    document.body.dataset.sidebarState = sidebarLevel === 1 ? "icons" : "expanded";
  }, [collapsed, sidebarLevel]);

  useEffect(() => {
    const onViewportMode = (event) => {
      setSidebarLevel(1);
    };
    window.addEventListener("bi-viewport-mode", onViewportMode);
    return () => window.removeEventListener("bi-viewport-mode", onViewportMode);
  }, []);

  // Two states only: expanded (full labels) and collapsed (icon rail).
  // The sidebar is never removed from the layout entirely.
  const toggle = () => {
    setSidebarLevel((level) => (level === 0 ? 1 : 0));
  };

  // Turn the three section labels into explicit expand controls in collapsed
  // mode. The menu items themselves keep their labels for tooltips and the
  // expanded layout.
  const items = useMemo(() => [{
    key: "new-chat",
    label: "新会话",
    title: "新会话",
    icon: <PlusOutlined />,
  }, ...navItems].map((item) => {
    if (item.type === "group") {
      return {
        ...item,
        label: <button type="button" className="antd-collapsed-section-button" onClick={toggle}>{item.label}</button>,
      };
    }
    if (item.type) return item;
    return { ...item, label: item.label, title: item.label };
  }), [toggle]);

  const handleSidebarSurfaceClick = (event) => {
    if (!collapsed) return;
    const target = event.target instanceof Element ? event.target : null;
    const interactive = target?.closest("button, a, .ant-menu-item, .ant-menu-submenu-title");
    if (!interactive) toggle();
  };

  return (
    <ConfigProvider theme={{ token: { colorPrimary: "#2563EB", colorInfo: "#2563EB", colorSuccess: "#15803D", colorError: "#B91C1C", colorWarning: "#C2410C", borderRadius: 8, fontFamily: "PingFang SC, -apple-system, sans-serif" } }}>
      <Sider className="antd-workbench-sidebar" collapsed={collapsed} width={260} collapsedWidth={72} theme="light">
        <div className="antd-sidebar-scroll" onClick={handleSidebarSurfaceClick}>
          <div className="antd-sidebar-brand">
            <AgentMark />
            {!collapsed && <span><strong>智析</strong><small id="antd-agent-name">bi-analyst</small></span>}
            <Tooltip
              placement="right"
              title={collapsed ? "展开侧栏" : "折叠侧栏"}
              color="#fff"
              overlayClassName="antd-workbench-tooltip"
            >
              <Button type="text" size="small" icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />} onClick={toggle} />
            </Tooltip>
          </div>
          <Menu
            mode="inline"
            inlineCollapsed={collapsed}
            selectedKeys={[active]}
            items={items}
            onClick={({ key }) => {
              if (key === "new-chat") {
                document.getElementById("nav-new-chat")?.click();
                return;
              }
              setActive(key);
              dispatchRuntime(key);
            }}
          />
          {!collapsed && <>
            <Divider className="antd-sidebar-divider" />
            <div className="antd-sidebar-section-row">
              <div className="antd-sidebar-section-title">最近</div>
              <button
                type="button"
                className={`antd-memory-entry${active === "memory" ? " active" : ""}`}
                onClick={() => { setActive("memory"); dispatchRuntime("memory"); }}
                title="记忆管理"
              >
                <FeatureGlyph kind="memory" />
                <span>记忆管理</span>
              </button>
            </div>
            <div className="antd-recent-list" data-status={recentStatus} aria-busy={recentStatus === "loading" ? "true" : "false"}>
              {recentStatus === "loading" ? <>
                <span className="antd-recent-loading">正在加载最近会话…</span>
                {Array.from({ length: 6 }, (_, index) => <span key={`recent-skeleton-${index}`} className="antd-recent-skeleton" aria-hidden="true" />)}
              </> : recentStatus === "error" ? <button type="button" className="antd-recent-error" onClick={() => requestRecentRefresh()}>
                加载失败，点击重试
              </button> : recent.length ? recent.map((item) => {
                const timeLabel = recentTimeLabel(item.updatedAt);
                return <button
                  key={item.key}
                  className={`antd-recent-item${item.active ? " active" : ""}`}
                  onClick={() => {
                    setActive(document.body.dataset.mode || "data");
                    setRecent((items) => items.map((current) => ({ ...current, active: current.key === item.key })));
                    const legacyNode = item.node || document.querySelector(`#recent-list .recent-item[data-cid="${CSS.escape(item.cid || item.key)}"]`);
                    legacyNode?.click();
                  }}
                  title={timeLabel ? `${item.title} · ${timeLabel}` : item.title}
                >
                  <span className="antd-recent-title">{item.title}</span>
                  {timeLabel && <small className="antd-recent-meta">{timeLabel}</small>}
                </button>;
              }) : <span className="antd-recent-empty">暂无历史会话</span>}
            </div>
            <button className="antd-account" onClick={() => document.getElementById("sidebar-account")?.click()}><FeatureGlyph kind="analyst" /> <span>分析员</span></button>
          </>}
          {collapsed && (
            <>
              <button type="button" className="antd-collapsed-section-button antd-collapsed-recent-button" onClick={toggle}>最近</button>
              <Tooltip placement="right" title="记忆管理" color="#fff" overlayClassName="antd-workbench-tooltip">
                <button
                  type="button"
                  className="antd-memory-entry antd-memory-entry-collapsed"
                  onClick={() => { setActive("memory"); dispatchRuntime("memory"); }}
                  aria-label="记忆管理"
                >
                  <FeatureGlyph kind="memory" />
                </button>
              </Tooltip>
              <Tooltip placement="right" title="分析员" color="#fff" overlayClassName="antd-workbench-tooltip">
                <button
                  type="button"
                  className="antd-account antd-account-collapsed"
                  onClick={() => document.getElementById("sidebar-account")?.click()}
                  aria-label="分析员"
                >
                  <FeatureGlyph kind="analyst" />
                </button>
              </Tooltip>
            </>
          )}
        </div>
      </Sider>
    </ConfigProvider>
  );
}

function readWorkflow() {
  const sop = document.getElementById("chat-sop");
  const todo = document.getElementById("chat-todo");
  const readItems = (root, selector) => root ? [...root.querySelectorAll(selector)].map((node, index) => ({
    key: `${index}`,
    text: node.querySelector(".chat-sop-text, .chat-todo-text")?.textContent?.trim() || node.textContent.trim(),
    status: [...node.classList].find((name) => name.startsWith("is-"))?.slice(3) || "pending",
  })) : [];
  const questions = todo ? [...todo.querySelectorAll(".chat-question-item")].map((node, index) => ({
    key: node.dataset.questionTurn || `${index}`,
    turn: node.dataset.questionTurn,
    text: node.querySelector(".chat-question-text")?.textContent?.trim() || node.textContent.trim(),
  })) : [];
  return {
    sop: readItems(sop, ".chat-sop-item"),
    todos: readItems(todo, ".chat-todo-item"),
    questions,
    sopHidden: !!sop?.hidden,
    todoHidden: !!todo?.hidden,
  };
}

function workflowIcon(status) {
  if (status === "completed") return <span className="antd-sop-status-check" aria-hidden="true">✓</span>;
  return <span className={`antd-sop-status-circle antd-sop-status-${status}`} aria-hidden="true" />;
}

function WorkflowPanels() {
  const [workflow, setWorkflow] = useState(readWorkflow);
  const [sopOpen, setSopOpen] = useState(true);
  const [todoOpen, setTodoOpen] = useState(true);
  const [mode, setMode] = useState(() => document.body.dataset.mode || "data");
  const [activeQuestionTurn, setActiveQuestionTurn] = useState(() =>
    document.getElementById("chat-todo")?.dataset.activeQuestionTurn || ""
  );
  useEffect(() => {
    const targets = [document.getElementById("chat-sop"), document.getElementById("chat-todo")].filter(Boolean);
    const observer = new MutationObserver(() => setWorkflow(readWorkflow()));
    targets.forEach((target) => observer.observe(target, { attributes: true, childList: true, subtree: true, characterData: true }));
    const onMode = (event) => setMode(event.detail?.mode || document.body.dataset.mode || "data");
    const onQuestionSelection = (event) => {
      const turn = String(event.detail?.turn || "");
      if (turn) setActiveQuestionTurn(turn);
    };
    window.addEventListener("bi-mode-changed", onMode);
    window.addEventListener("bi-question-selection-changed", onQuestionSelection);
    return () => {
      observer.disconnect();
      window.removeEventListener("bi-mode-changed", onMode);
      window.removeEventListener("bi-question-selection-changed", onQuestionSelection);
    };
  }, []);
  useLayoutEffect(() => {
    const firstTurn = workflow.questions[0]?.turn;
    if (firstTurn == null) return;
    const rememberedTurn = String(activeQuestionTurn || "");
    const value = workflow.questions.some((item) => String(item.turn) === rememberedTurn)
      ? rememberedTurn
      : String(firstTurn);
    if (value !== rememberedTurn) setActiveQuestionTurn(value);
    document.querySelectorAll(".antd-question-item[data-question-turn], .chat-question-item[data-question-turn]")
      .forEach((node) => node.classList.toggle("active", node.dataset.questionTurn === value));
  }, [workflow.questions, activeQuestionTurn]);
  const showEmptySop = mode === "data" && !workflow.sop.length;
  if (workflow.sopHidden && workflow.todoHidden && !showEmptySop) return null;
  const done = workflow.sop.filter((item) => item.status === "completed").length;
  const total = workflow.sop.length;
  const chainItems = workflow.sop.map((item) => ({
    key: item.key,
    title: <span className={`antd-sop-title is-${item.status}`}>{item.text}</span>,
    status: item.status === "completed" ? "success" : item.status === "in_progress" ? "pending" : "pending",
    icon: workflowIcon(item.status),
  }));
  return (
    <div className="antd-workflow-panels">
      {(!!workflow.sop.length || showEmptySop) && <Collapse
        ghost
        className="antd-workflow-collapse antd-workflow-sop"
        activeKey={sopOpen ? ["sop"] : []}
        onChange={(keys) => setSopOpen(keys.includes("sop"))}
        items={[{ key: "sop", label: <span className="antd-workflow-title">分析 SOP <Tag color="blue">{total ? `${done}/${total}` : "待开始"}</Tag></span>, children: total ? <ThoughtChain items={chainItems} size="small" /> : <div className="antd-workflow-empty-sop">开始一轮智能分析后，这里会显示本次对话的六步执行进度。</div> }]}
      />}
      {!!workflow.questions.length && <Collapse
        ghost
        className="antd-workflow-collapse antd-workflow-todo"
        activeKey={todoOpen ? ["todo"] : []}
        onChange={(keys) => setTodoOpen(keys.includes("todo"))}
        items={[{ key: "todo", label: <span className="antd-workflow-title">任务清单 <Tag>{workflow.questions.length} 个问题</Tag></span>, children: <>
          {!!workflow.questions.length && <List size="small" dataSource={workflow.questions} renderItem={(item, index) => <List.Item data-question-turn={item.turn} className="antd-question-item" onClick={() => document.querySelector(`#chat-todo .chat-question-item[data-question-turn="${CSS.escape(item.turn)}"]`)?.click()}><Tag>{index + 1}</Tag><span>{item.text}</span></List.Item>} />}
        </> }]}
      />}
    </div>
  );
}

const messageRoots = new WeakMap();
const stepRoots = new WeakMap();

function AntdMessage({ role, iteration, html }) {
  const user = role === "user";
  // Tool-only iterations can create an assistant message host before any
  // text arrives. Do not render an empty Bubble with only the iteration
  // header; the tool step itself remains visible below it.
  const rawHtml = String(html || "");
  const visibleHtml = stripDecorativeAssistantMarkup(
    rawHtml.replace(/<span class="thinking-line">[\s\S]*?思考中…<\/span>/g, ""),
  ).trim();
  if (!user && !visibleHtml) return null;
  const hasMarkup = /<\/?[a-z][^>]*>/i.test(visibleHtml);
  const hasMarkdown = /\*\*|__|```|^\s{0,3}#{1,6}\s|^\s*[-+*]\s|\|.+\|/m.test(visibleHtml);
  const contentHtml = !hasMarkup && hasMarkdown && typeof window.biRenderMarkdown === "function"
    ? window.biRenderMarkdown(visibleHtml)
    : visibleHtml;
  return <Bubble
    placement={user ? "end" : "start"}
    variant="filled"
    shape="corner"
    className={`antd-message-bubble ${user ? "antd-message-user" : "antd-message-assistant"}`}
    header={!user && <span className="antd-message-header">助手 · 迭代 {iteration || ""}</span>}
    content={contentHtml}
    messageRender={(content) => <div className="antd-message-html" dangerouslySetInnerHTML={{ __html: String(content || "") }} />}
  />;
}

function mountMessage(msg, role, iteration) {
  if (!msg || messageRoots.has(msg)) return;
  const host = document.createElement("div");
  host.className = "antd-message-host";
  msg.appendChild(host);
  const root = createRoot(host);
  const update = () => {
    const body = msg.querySelector(":scope > .msg-body");
    root.render(<AntdMessage role={role} iteration={iteration} html={body?.innerHTML || ""} />);
  };
  const body = msg.querySelector(":scope > .msg-body");
  const observer = body ? new MutationObserver(update) : null;
  if (body) observer.observe(body, { childList: true, subtree: true, characterData: true });
  messageRoots.set(msg, { root, observer, update });
  msg.classList.add("antd-message-enhanced");
  update();
}

window.antdMessageMount = mountMessage;

// Keep tool-result labels visually distinct while using the same semantic
// palette as 本体内容. The collapse arrow uses the same tone as its title.
const TOOL_RESULT_TONES = {
  OntologyQuery: "blue",
  TermDisambiguate: "teal",
  MetricLookup: "amber",
  RelationLookup: "slate",
  EntityDescribe: "teal",
  ListBusinessObjects: "red",
  SQLRun: "blue",
  ListTables: "slate",
  DescribeTable: "muted",
  ChartGenerate: "green",
  ChartGenerateMultiDim: "violet",
  TableGenerate: "green",
  AskUser: "approval",
  GraphContext: "blue",
  GraphExpand: "violet",
};

// Execution-step icons are deliberately independent from tool tones and
// execution status. The same AntdStep component is mounted for live steps and
// restored steps, so this one mapping keeps both paths identical.
const TOOL_STEP_ICON_SVG = Object.freeze({
  search: '<path d="M0 0h16v16H0z"/><path fill-rule="evenodd" fill="#8F9299" d="m14.624 13.921-1.952-1.952c.692-.845 1.154-1.744 1.388-2.7.15-.613.205-1.25.167-1.91-.1-1.686-.79-3.15-2.07-4.389-.826-.729-1.716-1.228-2.67-1.498a6.429 6.429 0 0 0-1.877-.236 6.395 6.395 0 0 0-1.883.313c-.935.306-1.797.837-2.585 1.593-.756.788-1.287 1.65-1.594 2.585a6.394 6.394 0 0 0-.312 1.883 6.43 6.43 0 0 0 .236 1.876c.27.955.769 1.845 1.498 2.67.744.769 1.568 1.325 2.473 1.668a6.437 6.437 0 0 0 1.917.402c1.687.1 3.224-.419 4.609-1.554l1.952 1.953c.104.093.221.14.352.14a.47.47 0 0 0 .344-.148.473.473 0 0 0 .148-.344.513.513 0 0 0-.14-.352Zm-4.268-1.346c-.77.413-1.643.633-2.62.659-1.563-.042-2.86-.578-3.89-1.61a5.413 5.413 0 0 1-.95-1.269c-.414-.77-.633-1.642-.66-2.62.042-1.562.579-2.858 1.61-3.89a5.412 5.412 0 0 1 1.27-.95c.768-.413 1.642-.632 2.62-.658 1.561.042 2.858.578 3.89 1.609.385.386.702.809.95 1.27.413.769.632 1.642.658 2.62-.042 1.561-.578 2.858-1.609 3.889a5.413 5.413 0 0 1-1.27.95Z" data-follow-fill="#8F9299"/>',
  term: '<path d="M0 0h16v16H0z"/><path fill-rule="evenodd" fill="#8F9299" d="M5.919 6.56a1 1 0 1 0 0-2 1 1 0 0 0 0 2Zm0 1a2 2 0 1 1 0-3.999 2 2 0 0 1 0 4Z" data-follow-fill="#8F9299"/><path fill-rule="evenodd" fill="#8F9299" d="M9.074 14.401c.216-.09.414-.224.593-.403l2.211-2.21 1.511-1.513.636-.635c.18-.18.315-.38.405-.597a1.82 1.82 0 0 0 .132-.709 1.82 1.82 0 0 0-.14-.708 1.821 1.821 0 0 0-.41-.593L8.866 1.99a1.82 1.82 0 0 0-.588-.393 1.822 1.822 0 0 0-.695-.131H2.604c-.16 0-.31.028-.448.085a1.158 1.158 0 0 0-.377.257c-.113.113-.199.24-.256.377a1.159 1.159 0 0 0-.085.447v4.97c0 .254.045.489.134.705.09.216.225.414.404.593l2.174 2.169 1.515 1.521L7.075 14c.178.178.376.313.592.402.216.09.45.134.704.134.253 0 .487-.044.703-.134Zm2.097-3.32L8.96 13.29a.824.824 0 0 1-.27.183.828.828 0 0 1-.32.061.828.828 0 0 1-.32-.06.824.824 0 0 1-.269-.184l-1.409-1.409-1.514-1.52-2.176-2.17a.83.83 0 0 1-.183-.27.828.828 0 0 1-.061-.32v-4.97c0-.056.014-.098.041-.126.028-.027.07-.041.125-.041h4.979c.113 0 .219.02.316.06.097.04.186.099.267.178l5.146 5.045c.083.08.145.17.187.269a.83.83 0 0 1 .063.322c0 .116-.02.223-.06.322a.825.825 0 0 1-.184.271l-.635.635-1.512 1.513Z" data-follow-fill="#8F9299"/>',
  metric: '<path d="M0 0h16v16H0z"/><path fill="#8F9299" d="M8.5 12v2h3a.5.5 0 0 1 0 1h-7a.5.5 0 0 1 0-1h3v-2H3a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v6a2 2 0 0 1-2 2H8.5ZM3 3a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1V4a1 1 0 0 0-1-1H3Z" data-follow-fill="#8F9299"/>',
  relation: '<path d="M0 0h16v16H0z"/><path fill-rule="evenodd" fill="#8F9299" d="m5.906 8.39 4.719-2.937A2.002 2.002 0 0 0 11.922 6c.49.02.935-.133 1.336-.462.401-.328.64-.732.719-1.21a1.9 1.9 0 0 0-.297-1.376c-.276-.437-.646-.726-1.11-.867a1.905 1.905 0 0 0-1.398.11c-.28.128-.513.297-.696.509a1.99 1.99 0 0 0-.382 1.905l-4.72 2.937a1.934 1.934 0 0 0-1.49-.539c-.256.018-.51.086-.76.203a1.892 1.892 0 0 0-.874.813 1.971 1.971 0 0 0-.235 1.172 1.964 1.964 0 0 0 1.476 1.735c.413.109.811.093 1.196-.047.386-.14.703-.388.953-.742l4.375 1.64c-.051.52.066.979.352 1.375s.68.654 1.18.774a1.92 1.92 0 0 0 1.399-.164c.43-.23.736-.586.913-1.071.111-.305.154-.603.127-.895a1.925 1.925 0 0 0-1.065-1.55 1.944 1.944 0 0 0-1.398-.188 1.98 1.98 0 0 0-1.164.797l-4.375-1.64a2.024 2.024 0 0 0-.078-.829Z" data-follow-fill="#8F9299"/>',
  graph: '<path d="M0 0h16v16H0z"/><path fill-rule="evenodd" fill="#8F9299" d="M1 8a7 7 0 1 0 14 0A7 7 0 0 0 1 8Zm1 0a6 6 0 1 0 12 0A6 6 0 0 0 2 8Zm6-2.5A.75.75 0 1 0 8 4a.75.75 0 0 0 0 1.5Zm-.5 1.602a.5.5 0 0 1 1 0v4.4a.5.5 0 1 1-1 0v-4.4Z" data-follow-fill="#8F9299"/>',
  database: '<path d="M0 0h16v16H0z"/><path fill-rule="evenodd" fill="#8F9299" d="M14.114 2.32c.171.076.326.185.456.32A1.39 1.39 0 0 1 15 3.7v4a.5.5 0 0 1-1 0V6.49H2v5.64a.421.421 0 0 0 .47.45h5.09a.51.51 0 0 1 .5.5.529.529 0 0 1-.15.34.497.497 0 0 1-.35.14H2.43a1.42 1.42 0 0 1-1-.43 1.396 1.396 0 0 1-.43-1V3.68a1.392 1.392 0 0 1 .47-1.04 1.43 1.43 0 0 1 1-.44h11.1c.187.004.372.045.544.12ZM2 5.49h12V3.68a.493.493 0 0 0-.29-.444.453.453 0 0 0-.18-.036H2.47a.42.42 0 0 0-.47.48v1.81Zm11.982 5.564a2.5 2.5 0 0 1-.322 1.026l.89.85a.495.495 0 0 1-.34.86.463.463 0 0 1-.34-.13l-.87-.81a2.384 2.384 0 0 1-1.5.48 2.492 2.492 0 0 1-2.16-3.747 2.488 2.488 0 0 1 2.17-1.233 2.37 2.37 0 0 1 1.76.73 2.5 2.5 0 0 1 .712 1.974Zm-1.897 1.133a1.499 1.499 0 0 0 .485-2.448 1.473 1.473 0 0 0-1.06-.44 1.441 1.441 0 0 0-1.06.44 1.5 1.5 0 0 0 0 2.12 1.44 1.44 0 0 0 1.06.44 1.47 1.47 0 0 0 .575-.111Z" data-follow-fill="#8F9299"/>',
  result: '<path d="M0 0h16v16H0z"/><path fill-rule="evenodd" fill="#8F9299" d="m9.822 8.776 4.225-3.974c.184-.173.325-.367.42-.58.097-.213.149-.446.156-.7a1.82 1.82 0 0 0-.112-.707 1.82 1.82 0 0 0-.385-.605l-.183-.195a1.82 1.82 0 0 0-.58-.42 1.824 1.824 0 0 0-.7-.156 1.82 1.82 0 0 0-.707.112c-.219.083-.42.211-.605.385L7.13 5.906a1.158 1.158 0 0 0-.342.606l-.4 1.876a.824.824 0 0 0 .007.402c.035.125.104.24.205.347.1.106.213.18.336.22.123.042.257.05.402.027l1.873-.307a1.163 1.163 0 0 0 .61-.301Zm4.554 4.286v-5a.491.491 0 0 0-.498-.5h-.002a.491.491 0 0 0-.5.498v5.002c0 .167-.042.292-.125.375-.083.084-.208.125-.375.125h-10c-.167 0-.292-.041-.375-.125-.084-.083-.125-.208-.125-.375v-10c0-.166.041-.291.125-.375.083-.084.208-.125.375-.125h5a.491.491 0 0 0 .5-.498v-.002a.491.491 0 0 0-.5-.5h-5c-.207 0-.4.037-.576.11a1.487 1.487 0 0 0-.485.33 1.487 1.487 0 0 0-.33.484c-.073.177-.11.37-.11.576v10c0 .207.037.4.11.576.074.177.184.339.33.485.146.146.308.256.485.33.177.073.369.11.576.11h10c.207 0 .399-.037.576-.11.176-.074.338-.184.484-.33.147-.146.257-.308.33-.485a1.49 1.49 0 0 0 .11-.576Zm-.823-9.252a.83.83 0 0 1-.191.264L9.137 8.047a.17.17 0 0 1-.087.043l-1.633.268.35-1.637a.167.167 0 0 1 .048-.087l4.221-3.97c.203-.19.402-.282.598-.276.197.006.39.11.58.312l.184.196a.828.828 0 0 1 .175.274c.037.1.054.207.05.322a.827.827 0 0 1-.07.318Z" data-follow-fill="#8F9299"/>',
  question: '<path d="M0 0h16v16H0z"/><path fill-rule="evenodd" fill="#8F9299" d="M15 8A7 7 0 1 1 1 8a7 7 0 0 1 14 0Zm-1 0A6 6 0 1 1 2 8a6 6 0 0 1 12 0Zm-5.02.33c-.14.05-.26.15-.35.27-.09.13-.13.28-.13.43 0 0 .34-.09.47-.22-.1.12-.24.22-.41.22-.17 0-.31-.09-.41-.22-.12-.16-.1-.45-.1-.45 0-.36.11-.72.31-1.01.2-.29.48-.51.81-.64.53-.2.88-.65.88-1.14 0-.69-.67-1.25-1.5-1.25-.76 0-1.39.47-1.49 1.08 0 .02-.05.35-.12.42-.06.09-.23.16-.38.16s-.28-.07-.37-.17a.545.545 0 0 1-.13-.31c0-.02.01-.16.01-.21.07-.51.32-.98.74-1.34C6.72 4.23 7.34 4 7.99 4c.65 0 1.27.23 1.74.64.49.43.76 1 .75 1.61.02.91-.58 1.72-1.5 2.08ZM8 12.014a.75.75 0 0 0 .532-.218.711.711 0 0 0 .218-.532.75.75 0 0 0-.218-.532.805.805 0 0 0-.532-.218.75.75 0 0 0-.532.218.782.782 0 0 0-.218.532.75.75 0 0 0 .218.532.806.806 0 0 0 .532.218Z" data-follow-fill="#8F9299"/>',
});

const TOOL_STEP_ICON_BY_NAME = Object.freeze({
  OntologyQuery: TOOL_STEP_ICON_SVG.search,
  ListBusinessObjects: TOOL_STEP_ICON_SVG.search,
  TermDisambiguate: TOOL_STEP_ICON_SVG.term,
  MetricLookup: TOOL_STEP_ICON_SVG.metric,
  EntityDescribe: TOOL_STEP_ICON_SVG.metric,
  RelationLookup: TOOL_STEP_ICON_SVG.relation,
  GraphContext: TOOL_STEP_ICON_SVG.graph,
  GraphExpand: TOOL_STEP_ICON_SVG.graph,
  SQLRun: TOOL_STEP_ICON_SVG.database,
  ListTables: TOOL_STEP_ICON_SVG.database,
  DescribeTable: TOOL_STEP_ICON_SVG.database,
  TableGenerate: TOOL_STEP_ICON_SVG.result,
  ChartGenerate: TOOL_STEP_ICON_SVG.result,
  ChartGenerateMultiDim: TOOL_STEP_ICON_SVG.result,
  AskUser: TOOL_STEP_ICON_SVG.question,
});

// The SVG assets remain centralized, but their paint must follow the same
// tone as the title/circle. Normalize the supplied paths once at the shared
// mapping boundary so neither live nor restored ThoughtChains can retain the
// old fixed gray fill.
const inheritToolIconColor = (markup) => String(markup || "")
  .replaceAll('fill="#8F9299"', 'fill="currentColor"')
  .replaceAll('data-follow-fill="#8F9299"', 'data-follow-fill="currentColor"');
const TOOL_STEP_ICON_BY_NAME_COLORED = Object.freeze(
  Object.fromEntries(Object.entries(TOOL_STEP_ICON_BY_NAME)
    .map(([name, markup]) => [name, inheritToolIconColor(markup)])),
);

function ToolStepIcon({ name, tone }) {
  const markup = TOOL_STEP_ICON_BY_NAME_COLORED[name] || inheritToolIconColor(TOOL_STEP_ICON_SVG.result);
  return <span className={`antd-step-result-icon antd-step-tool-icon antd-step-tone-${tone || "muted"}`} aria-hidden="true">
    <svg fill="none" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" dangerouslySetInnerHTML={{ __html: markup }} />
  </span>;
}

// Legacy history snapshots may have emitted consecutive .step nodes directly
// under a message/chat container. Move each consecutive run into the same
// timeline wrapper used by live execution. Existing timelines are left alone,
// making this safe to call from every MutationObserver pass.
function normalizeStepTimelineTree(container) {
  if (!container) return;
  const parents = new Set();
  container.querySelectorAll(".step").forEach((step) => {
    const parent = step.parentElement;
    if (parent && !parent.classList.contains("antd-step-timeline")) parents.add(parent);
  });
  parents.forEach((parent) => {
    const children = [...parent.children];
    let run = [];
    const flush = () => {
      if (!run.length) return;
      const timeline = document.createElement("div");
      timeline.className = "antd-step-timeline";
      timeline.dataset.normalized = "1";
      run[0].before(timeline);
      run.forEach((step) => timeline.appendChild(step));
      run = [];
    };
    children.forEach((child) => {
      if (child.classList.contains("step")) run.push(child);
      else flush();
    });
    flush();
  });

  // Legacy snapshots placed the timeline beside (or occasionally inside) an
  // assistant message. Normalize both shapes into the same execution block
  // used by live SSE rendering: message/results first, timeline last.
  container.querySelectorAll(".antd-step-timeline").forEach((timeline) => {
    if (timeline.closest(".assistant-execution-block")) return;
    const parent = timeline.parentElement;
    const isAssistant = (node) => node?.classList?.contains("msg") &&
      !node.classList.contains("msg-user") &&
      (node.classList.contains("msg-assistant") || node.classList.contains("antd-message-enhanced"));
    let message = isAssistant(timeline.previousElementSibling)
      ? timeline.previousElementSibling
      : null;
    if (!message && isAssistant(parent)) {
      message = parent;
      timeline.remove();
    }
    if (!message) return;
    const block = document.createElement("div");
    block.className = "assistant-execution-block";
    block.dataset.iteration = timeline.dataset.iteration || message.dataset.iteration || "";
    const nodes = [message];
    if (timeline.parentElement !== message) {
      let node = message.nextElementSibling;
      while (node) {
        nodes.push(node);
        if (node === timeline) break;
        node = node.nextElementSibling;
      }
    } else {
      timeline.remove();
      nodes.push(timeline);
    }
    message.before(block);
    nodes.forEach((node) => block.appendChild(node));
  });
}

window.antdNormalizeStepTimelines = normalizeStepTimelineTree;

const thoughtRailObservers = new WeakMap();
let thoughtRailFrame = 0;

function syncThoughtChainRail(timeline) {
  if (!timeline || !timeline.isConnected) return;
  const icons = [...timeline.querySelectorAll(":scope > .step > .antd-step-host .ant-thought-chain-item-icon")];
  if (!icons.length) return;
  const timelineRect = timeline.getBoundingClientRect();
  const firstRect = icons[0].getBoundingClientRect();
  const lastRect = icons[icons.length - 1].getBoundingClientRect();
  const centerX = firstRect.left + firstRect.width / 2 - timelineRect.left;
  const firstCenterY = firstRect.top + firstRect.height / 2 - timelineRect.top;
  const lastCenterY = lastRect.top + lastRect.height / 2 - timelineRect.top;
  timeline.style.setProperty("--thought-step-rail-center-x", `${centerX}px`);
  timeline.style.setProperty("--thought-step-rail-top", `${firstCenterY}px`);
  timeline.style.setProperty("--thought-step-rail-bottom", `${lastCenterY}px`);
  timeline.style.setProperty("--thought-step-rail-height", `${Math.max(0, lastCenterY - firstCenterY)}px`);
  if (!thoughtRailObservers.has(timeline) && typeof ResizeObserver === "function") {
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(thoughtRailFrame);
      thoughtRailFrame = requestAnimationFrame(() => syncThoughtChainRail(timeline));
    });
    observer.observe(timeline);
    thoughtRailObservers.set(timeline, observer);
  }
}

function syncAllThoughtChainRails(container) {
  container?.querySelectorAll(".antd-step-timeline").forEach(syncThoughtChainRail);
}

function AntdStep({ name, summary, duration, html }) {
  const [expanded, setExpanded] = useState(false);
  const expandedRef = useRef(false);
  const shellRef = useRef(null);
  const innerRef = useRef(null);
  const frameRef = useRef(0);
  const transition = "height 220ms cubic-bezier(.22,.61,.36,1)";
  const detailHtml = String(html || "").trim() || '<div class="antd-step-empty">暂无详细内容</div>';
  const tone = TOOL_RESULT_TONES[name] || "muted";
  const toneClass = `antd-step-tone-${tone}`;
  useEffect(() => () => cancelAnimationFrame(frameRef.current), []);
  useEffect(() => {
    const shell = shellRef.current;
    const inner = innerRef.current;
    if (!shell || !inner || typeof ResizeObserver !== "function") return undefined;
    const observer = new ResizeObserver(() => {
      if (!expandedRef.current || shell.dataset.animating !== "true") return;
      shell.style.height = `${inner.scrollHeight}px`;
    });
    observer.observe(inner);
    return () => observer.disconnect();
  }, []);
  const toggle = (event) => {
    event.preventDefault();
    event.stopPropagation();
    const shell = shellRef.current;
    const inner = innerRef.current;
    if (!shell || !inner) return;
    cancelAnimationFrame(frameRef.current);
    const next = !expandedRef.current;
    expandedRef.current = next;
    setExpanded(next);
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
    const current = shell.getBoundingClientRect().height;
    shell.dataset.animating = reduced ? "false" : "true";
    shell.style.transition = "none";
    shell.style.height = `${current}px`;
    if (reduced) {
      shell.style.height = next ? "auto" : "0px";
      return;
    }
    void shell.offsetHeight;
    frameRef.current = requestAnimationFrame(() => {
      shell.style.transition = transition;
      shell.style.height = next ? `${inner.scrollHeight}px` : "0px";
    });
  };
  const onTransitionEnd = (event) => {
    if (event.target !== shellRef.current || event.propertyName !== "height") return;
    const shell = shellRef.current;
    shell.dataset.animating = "false";
    shell.style.transition = transition;
    shell.style.height = expandedRef.current ? "auto" : "0px";
  };
  return <div className="thinking-step">
    <ThoughtChain
      size="small"
      className={`antd-thought-chain ${toneClass}`}
      // Ant Design's content motion is intentionally bypassed. The body
      // shell below is a direct sibling of the header chain, so its pixel
      // height participates in normal document flow and pushes later steps.
      collapsible={false}
      items={[{
        key: "step",
        // Tool results are the only execution events shown in the conversation.
        // The runtime owns the shared thinking row; this component renders the
        // completed result once the tool has returned.
        icon: <ToolStepIcon name={name} tone={tone} />,
        title: <button type="button" className="thinking-step-header" aria-expanded={expanded} onClick={toggle}>
          <span className={`antd-step-label ${toneClass}`}>
            <b>{name}</b>
            {summary && <span className="antd-step-summary">{summary}</span>}
            {duration && <em>{duration}</em>}
          </span>
        </button>,
      }]}
    />
    <div ref={shellRef} className="thinking-step-body-shell" data-expanded={expanded ? "true" : "false"} onTransitionEnd={onTransitionEnd}>
      <div ref={innerRef} className="thinking-step-body-inner">
        <div className="antd-step-html" dangerouslySetInnerHTML={{ __html: detailHtml }} />
      </div>
    </div>
  </div>;
}

function mountStep(step) {
  if (!step || stepRoots.has(step)) return;
  if (!step.parentElement?.classList.contains("antd-step-timeline")) {
    normalizeStepTimelineTree(step.parentElement || step);
  }
  const header = step.querySelector(":scope > .step-header");
  const body = step.querySelector(":scope > .step-body");
  const text = (selector) => step.querySelector(selector)?.textContent?.trim() || "";
  // Saved conversation HTML can already contain the host and the rendered
  // ThoughtChain markup. Reuse one direct child host and clear its stale
  // snapshot before creating the new React root, otherwise restoring a
  // conversation adds a second timeline node.
  // History snapshots may contain an older host/thinking-step alongside the
  // legacy .step nodes. Keep exactly one host before rendering the canonical
  // AntdStep tree; repeated enhancement passes remain idempotent.
  const hosts = [...step.querySelectorAll(":scope > .antd-step-host")];
  const host = hosts.shift() || null;
  hosts.forEach((duplicate) => duplicate.remove());
  step.querySelectorAll(":scope > .thinking-step").forEach((legacy) => legacy.remove());
  if (!host) {
    const createdHost = document.createElement("div");
    createdHost.className = "antd-step-host";
    step.appendChild(createdHost);
    return mountStep(step);
  } else {
    host.replaceChildren();
  }
  const root = createRoot(host);
  const update = () => {
    root.render(<AntdStep name={text(".step-name")} summary={text(".step-summary")} duration={text(".step-duration")} html={body?.innerHTML || ""} />);
    requestAnimationFrame(() => syncThoughtChainRail(step.closest(".antd-step-timeline")));
  };
  const observer = body ? new MutationObserver(update) : null;
  if (body) observer.observe(body, { childList: true, subtree: true, characterData: true });
  if (header) header.style.display = "none";
  if (body) body.style.display = "none";
  step.classList.add("antd-step-enhanced");
  stepRoots.set(step, { root, observer });
  update();
}

window.antdStepMount = mountStep;

const cardRoots = new WeakMap();
function isProUiChartCard(card) {
  if (!card?.dataset?.chartJson) return false;
  try {
    const chart = JSON.parse(decodeURIComponent(card.dataset.chartJson));
    const type = String(chart?.chart_type || chart?.option?.series?.[0]?.type || "").toLowerCase();
    return ["bar", "horizontal_bar", "line", "area", "pie"].includes(type);
  } catch (_) {
    return false;
  }
}

function mountResultCard(card, type) {
  if (!card || cardRoots.has(card)) return;
  if (type === "chart" && isProUiChartCard(card)) {
    // Historical snapshots can contain a persisted Ant result host. Remove
    // that wrapper and move its canvas back to the legacy chart shell before
    // the runtime remounts it through Pro UI.
    const existingHost = card.querySelector(":scope > .antd-result-card-host");
    const canvas = card.querySelector(":scope .chart-canvas") || existingHost?.querySelector(":scope .chart-canvas");
    if (canvas && canvas.parentElement !== card) card.appendChild(canvas);
    existingHost?.remove();
    const head = card.querySelector(":scope > .chart-head");
    const metaNodes = head ? [...head.querySelectorAll(":scope > .chart-saved, :scope > .chart-insight-btn")] : [];
    if (head) head.remove();
    if (metaNodes.length) {
      const meta = document.createElement("div");
      meta.className = "chart-meta";
      metaNodes.forEach((node) => meta.appendChild(node));
      if (canvas) card.insertBefore(meta, canvas.nextSibling);
      else card.appendChild(meta);
    }
    card.classList.add("pro-ui-chart-card");
    cardRoots.set(card, { proUi: true });
    return;
  }
  // Older snapshots contain a rendered ECharts canvas but no chart option
  // (`data-chart-json`). That canvas already includes its own title; keep it
  // as the single visible title instead of adding a second React header.
  const legacyStaticChart = !card.dataset.chartJson && !!card.querySelector(
    ":scope > .chart-canvas canvas, :scope > .multidim-canvas canvas",
  );
  const moveRestoredSourceToFooter = (host) => {
    const body = host.querySelector(":scope .ant-card-body");
    const titleHost = host.querySelector(":scope .ant-card-head-title");
    const titleRow = titleHost?.querySelector(":scope > .antd-result-title-row");
    const headerSource = titleHost?.querySelector(":scope .antd-result-source");
    const footerSource = body?.querySelector(":scope > .antd-result-source-footer .antd-result-source");
    if (!body || !titleHost) return;

    // Older persisted cards were saved with a type badge and source link in
    // the same row. Normalize that DOM in place so history removes the badge
    // just like a newly rendered result, without remounting the chart.
    if (titleRow) {
      const titleText = titleRow.querySelector(":scope > .antd-result-title-text");
      const typeBadge = titleRow.querySelector(":scope > .antd-result-type");
      // Type labels such as TABLE/CHART are implementation metadata, not
      // user-facing card titles. Remove them from restored cards as well as
      // newly mounted cards so history and live rendering match.
      if (typeBadge) typeBadge.remove();
      if (titleText && titleRow.firstElementChild !== titleText) {
        titleRow.replaceChildren(titleText);
      }
    }
    // Some early persisted cards did not retain the title-row wrapper. They
    // still have the result badge, so normalize that legacy shape as well.
    decorateResultTypeBadge(host.querySelector(":scope .antd-result-type"), type);

    const source = headerSource || footerSource;
    if (!source) return;
    let footer = body.querySelector(":scope > .antd-result-source-footer");
    if (!footer) {
      footer = document.createElement("div");
      footer.className = "antd-result-source-footer";
      body.appendChild(footer);
    }
    if (source.parentElement !== footer) footer.appendChild(source);
  };
  // Saved HTML can already contain the host and rendered Ant Card from a
  // previous session. Reusing it avoids appending a second host during
  // history hydration (which was the source of occasional triple bubbles).
  const existingHost = card.querySelector(":scope > .antd-result-card-host");
  if (existingHost && existingHost.children.length) {
    // Older saved Ant cards used a title-only header. Add the legacy source
    // link back in place without rebuilding the already-hydrated canvas.
    const restoredTitle = existingHost.querySelector(":scope .ant-card-head-title");
    const restoredSource = card.querySelector(`:scope > .${type === "table" ? "table-head" : type === "multi" ? "multidim-head" : "chart-head"} .${type === "chart" ? "chart-saved" : type === "multi" ? "multidim-source" : "table-source"}`);
    const hasRestoredFooter = existingHost.querySelector(":scope .antd-result-source-footer .antd-result-source");
    if (restoredTitle && restoredSource && !hasRestoredFooter && !restoredTitle.querySelector(".antd-result-source")) {
      const sourceClone = restoredSource.cloneNode(true);
      sourceClone.className = "antd-result-source";
      restoredTitle.appendChild(sourceClone);
    }
    moveRestoredSourceToFooter(existingHost);
    existingHost.querySelector(":scope .antd-result-card")?.classList.toggle(
      "antd-result-legacy-static",
      legacyStaticChart,
    );
    cardRoots.set(card, { restored: true });
    return;
  }
  const host = existingHost || document.createElement("div");
  host.className = "antd-result-card-host";
  if (!existingHost) card.appendChild(host);
  const head = card.querySelector(`:scope > .${type === "table" ? "table-head" : type === "multi" ? "multidim-head" : "chart-head"}`);
  const title = head?.querySelector(`.${type === "table" ? "table-title" : type === "multi" ? "multidim-title" : "chart-title"}`)?.textContent?.trim() || "分析结果";
  const typeNode = head?.querySelector(`.${type === "table" ? "table-tag" : type === "multi" ? "multidim-tag" : "chart-type"}`);
  const sourceNode = head?.querySelector(type === "chart"
    ? ".chart-saved"
    : type === "multi" ? ".multidim-source, .multidim-saved" : ".table-source");
  const typeLabel = typeNode?.textContent?.trim() || type.toUpperCase();
  const sourceText = sourceNode?.textContent?.trim() || "";
  const sourceHref = sourceNode?.querySelector("a")?.getAttribute("href") || "";
  const semantic = typeNode?.classList.contains("conclusion") ||
    typeNode?.classList.contains("rootcause") || typeNode?.classList.contains("actions");
  const resultTitle = (
    <span className={`antd-result-title-row${semantic ? " antd-result-semantic-title" : ""}`}>
      {semantic && <span className="antd-result-semantic-label">{cleanResultTypeLabel(typeLabel)}</span>}
      <span className="antd-result-title-text">{title}</span>
    </span>
  );
  const sourceFooter = sourceText && (
    <div className="antd-result-source-footer">
      {sourceHref
        ? <a className="antd-result-source" href={sourceHref} target="_blank" rel="noreferrer">{sourceText}</a>
        : <span className="antd-result-source">{sourceText}</span>}
    </div>
  );
  const nodes = type === "chart"
    ? [card.querySelector(":scope > .chart-canvas")]
    : type === "table"
      ? [card.querySelector(":scope > .table-scroll"), card.querySelector(":scope > .table-summary"), card.querySelector(":scope > .table-footnote")]
      : [card.querySelector(":scope > .multidim-toolbar"), card.querySelector(":scope > .multidim-canvas"), card.querySelector(":scope > .multidim-summary"), card.querySelector(":scope > .multidim-footnote")];
  const root = createRoot(host);
  root.render(<Card size="small" title={resultTitle} className={`antd-result-card antd-result-${type}${legacyStaticChart ? " antd-result-legacy-static" : ""}`}><div ref={(slot) => { if (slot) nodes.filter(Boolean).forEach((node) => slot.appendChild(node)); }} />{sourceFooter}</Card>);
  if (head) head.style.display = "none";
  cardRoots.set(card, root);
}
window.antdResultCardMount = mountResultCard;

function DashboardInnerBubble({ nodes }) {
  return <div
    className="antd-dashboard-inner-bubble"
    ref={(slot) => { if (slot) nodes.forEach((node) => slot.appendChild(node)); }}
  />;
}

function mountDashboardCard(card) {
  if (!card || cardRoots.has(card)) return;
  // User prompts remain available in the chat and task list for navigation,
  // but the read-only dashboard should contain only generated results.
  if (card.classList.contains("dash-question")) {
    card.classList.add("antd-dashboard-question-hidden");
    card.setAttribute("aria-hidden", "true");
    return;
  }
  if (isProUiChartCard(card)) {
    const existingHost = card.querySelector(":scope > .antd-dashboard-card-host");
    const canvas = card.querySelector(":scope .dash-chart-canvas") || existingHost?.querySelector(":scope .dash-chart-canvas");
    if (canvas && canvas.parentElement !== card) card.appendChild(canvas);
    existingHost?.remove();
    // The Pro UI chart owns the title. Keep only saved/insight metadata in a
    // borderless row outside the Pro UI result surface.
    const head = card.querySelector(":scope > .dash-head");
    const metaNodes = head ? [...head.querySelectorAll(":scope > .dash-link, :scope > .chart-insight-btn")] : [];
    if (head) head.remove();
    if (metaNodes.length) {
      const meta = document.createElement("div");
      meta.className = "chart-meta";
      metaNodes.forEach((node) => meta.appendChild(node));
      if (canvas) card.insertBefore(meta, canvas.nextSibling);
      else card.appendChild(meta);
    }
    card.classList.add("pro-ui-chart-card");
    card.classList.add("antd-dashboard-card-mounted");
    cardRoots.set(card, { proUi: true });
    return;
  }
  // Legacy dashboard snapshots also persisted a rendered canvas without the
  // chart option. Their canvas title is still the only recoverable title.
  const legacyStaticChart = !card.dataset.chartJson && !!card.querySelector(
    ":scope > .dash-chart-canvas canvas, :scope > .multidim-canvas canvas",
  );
  // A persisted dashboard snapshot may include the already-rendered host.
  // Do not mount a second React tree on top of it when restoring history.
  const existingHost = card.querySelector(":scope > .antd-dashboard-card-host");
  if (existingHost && existingHost.children.length) {
    const restoredHead = existingHost.querySelector(":scope .antd-dashboard-result-head");
    const restoredTag = restoredHead?.querySelector(":scope > .dash-tag");
    const restoredTitle = restoredHead?.querySelector(":scope > .dash-title");
    if (restoredHead && restoredTag && restoredTitle) {
      const semantic = restoredTag.classList.contains("conclusion") ||
        restoredTag.classList.contains("rootcause") || restoredTag.classList.contains("actions");
      // Keep semantic labels on the left. Remove chart/table implementation
      // labels entirely from restored dashboard cards.
      if (semantic) restoredHead.replaceChildren(restoredTag, restoredTitle);
      else restoredTag.remove();
    }
    if (restoredHead) {
      restoredHead.classList.toggle("antd-dashboard-legacy-static-chart", legacyStaticChart);
      restoredHead.classList.toggle(
        "antd-dashboard-action-head",
        !!restoredHead.querySelector(":scope > .dash-tag.conclusion, :scope > .dash-tag.rootcause, :scope > .dash-tag.actions"),
      );
    }
    card.classList.add("antd-dashboard-card-mounted");
    cardRoots.set(card, { restored: true });
    return;
  }
  const host = existingHost || document.createElement("div");
  host.className = "antd-dashboard-card-host";
  if (!existingHost) card.appendChild(host);
  card.classList.add("antd-dashboard-card-mounted");
  const head = card.querySelector(":scope > .dash-head");
  // Keep the semantic badge and title visible in the board, just like the
  // header of the conversation result cards. Other head metadata (source and
  // turn) stays hidden to avoid duplicating technical information.
  const typeTag = head?.querySelector(":scope > .dash-tag");
  const title = head?.querySelector(":scope > .dash-title");
  decorateResultTypeBadge(
    typeTag,
    typeTag?.classList.contains("table") ? "table"
      : typeTag?.classList.contains("chart") ? "chart" : "",
  );
  decorateSemanticBadge(typeTag);
  const nodes = [...card.children].filter((node) => node !== head && node !== host);
  if (typeTag || title) {
    const resultHead = document.createElement("div");
    resultHead.className = "antd-dashboard-result-head";
    if (typeTag?.classList.contains("conclusion") || typeTag?.classList.contains("rootcause") || typeTag?.classList.contains("actions")) {
      resultHead.classList.add("antd-dashboard-action-head");
    }
    if (legacyStaticChart) resultHead.classList.add("antd-dashboard-legacy-static-chart");
    const semanticTag = typeTag?.classList.contains("conclusion") ||
      typeTag?.classList.contains("rootcause") || typeTag?.classList.contains("actions");
    if (semanticTag && typeTag) resultHead.appendChild(typeTag);
    if (title) resultHead.appendChild(title);
    nodes.unshift(resultHead);
  }
  const root = createRoot(host);
  root.render(<DashboardInnerBubble nodes={nodes} />);
  if (head) head.style.display = "none";
  cardRoots.set(card, root);
}
window.antdDashboardCardMount = mountDashboardCard;

function enhanceWorkbenchTree(container) {
  if (!container) return;
  normalizeStepTimelineTree(container);
  // Remove type-only labels from legacy saved result markup. Semantic labels
  // remain and are handled by the dashboard/result header layout.
  container.querySelectorAll(".chart-head > .chart-type, .table-head > .table-tag, .multidim-head > .multidim-tag, .dash-head > .dash-tag.chart, .dash-head > .dash-tag.table, .dash-head > .dash-tag.multidim, .antd-result-type").forEach((node) => node.remove());
  container.querySelectorAll(".dash-head, .antd-dashboard-result-head").forEach((head) => {
    const semantic = head.querySelector(":scope > .dash-tag.conclusion, :scope > .dash-tag.rootcause, :scope > .dash-tag.actions");
    if (semantic && head.firstElementChild !== semantic) head.prepend(semantic);
    head.querySelectorAll(":scope > .dash-tag:not(.conclusion):not(.rootcause):not(.actions)").forEach((node) => node.remove());
  });
  container.querySelectorAll(".dash-tag.conclusion, .dash-tag.rootcause, .dash-tag.actions").forEach(decorateSemanticBadge);
  container.querySelectorAll(":scope > .msg:not(.antd-message-enhanced)").forEach((node) => {
    mountMessage(node, node.classList.contains("msg-user") ? "user" : "assistant", node.querySelector(".msg-iter")?.textContent?.replace(/[^0-9]/g, ""));
  });
  container.querySelectorAll(".step:not(.antd-step-enhanced)").forEach(mountStep);
  container.querySelectorAll(":scope > .chart-card:not(.antd-result-card-host), :scope > .table-card:not(.antd-result-card-host), :scope > .multidim-card:not(.antd-result-card-host)").forEach((node) => {
    mountResultCard(node, node.classList.contains("table-card") ? "table" : node.classList.contains("multidim-card") ? "multi" : "chart");
  });
  container.querySelectorAll(".dash-card:not(.antd-dashboard-question-hidden)").forEach(mountDashboardCard);
  requestAnimationFrame(() => syncAllThoughtChainRails(container));
}

function observeWorkbenchSurface(id) {
  const container = document.getElementById(id);
  if (!container) return;
  enhanceWorkbenchTree(container);
  const observer = new MutationObserver(() => enhanceWorkbenchTree(container));
  observer.observe(container, { childList: true, subtree: true });
}

const shellMarkup = (shellDocument.match(/<body[^>]*>([\s\S]*?)<\/body>/i)?.[1] || shellDocument)
  .replace(/<script\b[\s\S]*?<\/script>/gi, "")
  .trim();

function WorkbenchApp() {
  const shellRef = useRef(null);

  useLayoutEffect(() => {
    document.body.dataset.mode = "data";
    document.body.classList.add("sidebar-collapsed");
    if (!shellRef.current) return undefined;

    const sidebarRoot = shellRef.current.querySelector("#antd-sidebar-root");
    const workflowRoot = shellRef.current.querySelector("#antd-workflow-root");
    const dashboardWorkflowRoot = shellRef.current.querySelector("#antd-dashboard-workflow-root");
    if (sidebarRoot) createRoot(sidebarRoot).render(<Sidebar />);
    if (workflowRoot) createRoot(workflowRoot).render(<WorkflowPanels />);
    if (dashboardWorkflowRoot) createRoot(dashboardWorkflowRoot).render(<WorkflowPanels />);
    shellRef.current.querySelectorAll(".page-title-icon[data-feature-glyph]").forEach((node) => {
      createRoot(node).render(<FeatureGlyph kind={node.dataset.featureGlyph} />);
    });

    // The former static runtime is now an internal React bundle module. It
    // still owns the API/SSE state machine, while all markup is mounted under
    // this React root and no longer loaded as a separate static script.
    bootWorkbenchRuntime();
    observeWorkbenchSurface("chat-scroll");
    observeWorkbenchSurface("dashboard-list");
    return undefined;
  }, []);

  return <div ref={shellRef} dangerouslySetInnerHTML={{ __html: shellMarkup }} />;
}

const root = document.getElementById("root");
if (root) createRoot(root).render(<WorkbenchApp />);
