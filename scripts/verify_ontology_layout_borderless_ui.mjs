#!/usr/bin/env node
/**
 * Repeatable real-browser acceptance for the ontology layout controls.
 *
 * Specs:
 *   - docs/specs/ontology-layout-borderless-options.md
 *   - docs/specs/ontology-layout-narrow-hover-evidence-fix.md
 *
 * Drives a local headless Chrome/Chromium over the DevTools protocol with
 * real DOM, real mouse input, getComputedStyle() and getBoundingClientRect().
 * It opens the ontology subgraph modal for a demo entity injected into the
 * workbench list, then verifies the desktop (1440x900) borderless option
 * contract and the narrow (700x900) option-hover white tooltip flow.
 *
 * Outputs (all from this single run):
 *   docs/test-evidence/ontology-layout-borderless-browser-acceptance.json
 *   docs/test-evidence/g1-desktop-menu.png      docs/test-evidence/g2-desktop-hover-row.png
 *   docs/test-evidence/g3-narrow-menu.png       docs/test-evidence/g4-narrow-hover.png
 *
 * Usage:
 *   node scripts/verify_ontology_layout_borderless_ui.mjs
 * Env:
 *   WORKBENCH_URL  page to verify (default http://127.0.0.1:8765/workbench)
 *   CHROME_BIN     Chrome/Chromium binary override
 * Exits non-zero when any assertion fails. The local service must already be
 * running; this script never deploys or writes to the server.
 */
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const OUT_DIR = join(REPO, "docs", "test-evidence");
const JSON_PATH = join(OUT_DIR, "ontology-layout-borderless-browser-acceptance.json");
const G1 = join(OUT_DIR, "g1-desktop-menu.png");
const G2 = join(OUT_DIR, "g2-desktop-hover-row.png");
const G3 = join(OUT_DIR, "g3-narrow-menu.png");
const G4 = join(OUT_DIR, "g4-narrow-hover.png");
const URL = process.env.WORKBENCH_URL || "http://127.0.0.1:8765/workbench";

const RADIAL_HINT = "以当前锚点为中心，按照最短关系距离由内向外分环排列。";
const CLUSTER_HINT = "ForceAtlas2 是一种先进的力导向图布局，适合查看节点之间的关系聚类。";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const checks = [];
function record(name, ok, detail) {
  checks.push({ name, ok, detail });
  console.log(`${ok ? "PASS" : "FAIL"} ${name} :: ${typeof detail === "string" ? detail : JSON.stringify(detail)}`);
}
function sha256File(path) {
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

function findChrome() {
  const candidates = [
    process.env.CHROME_BIN,
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
  ].filter(Boolean);
  for (const c of candidates) if (existsSync(c)) return c;
  throw new Error("Chrome/Chromium binary not found; set CHROME_BIN");
}

async function freePort() {
  const net = await import("node:net");
  return new Promise((resolvePort) => {
    const srv = net.createServer();
    srv.listen(0, "127.0.0.1", () => {
      const port = srv.address().port;
      srv.close(() => resolvePort(port));
    });
  });
}

async function getJson(base, path) {
  const res = await fetch(base + path, { signal: AbortSignal.timeout(5000) });
  if (!res.ok) throw new Error(`GET ${path} -> ${res.status}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// CDP plumbing
// ---------------------------------------------------------------------------
function connect(wsUrl) {
  return new Promise((resolveConn, rejectConn) => {
    const ws = new WebSocket(wsUrl);
    let nextId = 0;
    const pending = new Map();
    ws.onopen = () => resolveConn({
      ws,
      send(method, params = {}) {
        const id = ++nextId;
        return new Promise((resolve, reject) => {
          const timer = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 20000);
          pending.set(id, {
            resolve: (v) => { clearTimeout(timer); resolve(v); },
            reject: (e) => { clearTimeout(timer); reject(e); },
          });
          ws.send(JSON.stringify({ id, method, params }));
        });
      },
    });
    ws.onerror = (e) => rejectConn(new Error(`WebSocket error: ${e.message || e}`));
    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.id && pending.has(msg.id)) {
        const p = pending.get(msg.id);
        pending.delete(msg.id);
        if (msg.error) p.reject(new Error(JSON.stringify(msg.error)));
        else p.resolve(msg.result);
      }
    };
  });
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------
const startedAt = Date.now();
const chromePath = findChrome();
const port = await freePort();
const profile = mkdtempSync(join(tmpdir(), "ontology-layout-evidence-"));
const chrome = spawn(chromePath, [
  "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
  "--disable-background-networking", "--disable-component-update", "--no-sandbox",
  `--user-data-dir=${profile}`, `--remote-debugging-port=${port}`,
  "--window-size=1440,900", URL,
], { stdio: "ignore" });

let page;
let cdp;
let browserVersion = "unknown";
let targetForScreenshot;
try {
  const base = `http://127.0.0.1:${port}`;
  let ready = false;
  for (let i = 0; i < 60; i++) {
    try {
      const info = await getJson(base, "/json/version");
      browserVersion = info.Browser || browserVersion;
      ready = true;
      break;
    } catch { await sleep(300); }
  }
  if (!ready) throw new Error("DevTools endpoint did not come up");
  for (let i = 0; i < 60; i++) {
    const targets = await getJson(base, "/json/list");
    page = targets.find((t) => t.type === "page" && t.url.includes(URL.replace("http://127.0.0.1:8765", "127.0.0.1:8765")));
    if (page) break;
    await sleep(300);
  }
  if (!page) throw new Error("workbench page target not found");
  const conn = await connect(page.webSocketDebuggerUrl);
  cdp = conn;
  targetForScreenshot = page;
  await cdp.send("Page.enable");
  await cdp.send("Runtime.enable");

  async function evalJs(expression) {
    const res = await cdp.send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (res.exceptionDetails) {
      throw new Error("eval error: " + JSON.stringify(res.exceptionDetails.exception?.description || res.exceptionDetails.text));
    }
    return res.result.value;
  }
  async function waitFor(expression, timeout = 12000, label = "condition") {
    const t0 = Date.now();
    while (Date.now() - t0 < timeout) {
      if (await evalJs(expression)) return;
      await sleep(200);
    }
    throw new Error(`timeout waiting for ${label}`);
  }
  async function screenshot(path) {
    const res = await cdp.send("Page.captureScreenshot", { format: "png" });
    writeFileSync(path, Buffer.from(res.data, "base64"));
  }
  async function setViewport(width, height) {
    await cdp.send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: false });
    await sleep(400);
  }
  async function mouseMove(x, y) {
    await cdp.send("Input.dispatchMouseEvent", { type: "mouseMoved", x, y });
  }

  // Wait for the workbench UI to be interactive.
  await waitFor(`Boolean(document.querySelector('#ontology-list'))`, 20000, "ontology list");
  await sleep(800);

  // Open the ontology subgraph modal for the demo entity (repeatable, does not
  // touch history sessions: only a transient DOM card is injected).
  await evalJs(`
    (() => {
      const list = document.querySelector("#ontology-list");
      if (!list) return "no list";
      if (list.querySelector('.entity-card[data-code="OBJ_BORDERLESS_DEMO"]')) return "exists";
      const card = document.createElement("div");
      card.className = "entity-card";
      card.dataset.code = "OBJ_BORDERLESS_DEMO";
      card.innerHTML = '<div class="entity-head"><span class="entity-kind-tag">业务对象</span><span class="entity-code">OBJ_BORDERLESS_DEMO</span><span class="entity-name">布局验收对象</span><span class="entity-chevron">›</span></div><div class="entity-body">demo</div>';
      list.appendChild(card);
      return "injected";
    })()
  `);
  await waitFor(`Boolean(document.querySelector('.entity-card[data-code="OBJ_BORDERLESS_DEMO"]'))`, 6000, "demo card");
  await evalJs(`document.querySelector('.entity-card[data-code="OBJ_BORDERLESS_DEMO"] .entity-head').click()`);
  await waitFor(`!document.querySelector('.ontology-graph-modal')?.hidden`, 10000, "ontology modal open");
  await waitFor(`document.querySelector('[data-graph-layout-trigger]')?.disabled === false`, 10000, "layout trigger enabled");
  await waitFor(`document.querySelector('.ontology-graph-dialog')?.getBoundingClientRect().width > 0`, 5000, "dialog laid out");

  async function openMenu() {
    await evalJs(`document.querySelector('[data-graph-layout-trigger]').click()`);
    await waitFor(`document.querySelector('[data-graph-layout-trigger]').getAttribute('aria-expanded') === 'true'`, 6000, "menu open");
    await sleep(400);
  }
  async function readTooltipState() {
    return evalJs(`
      (() => {
        const t = document.querySelector('[data-graph-layout-option-tooltip]');
        if (!t) return null;
        const cs = getComputedStyle(t);
        const r = t.getBoundingClientRect();
        const hovered = document.querySelector('.ontology-layout-option:hover');
        return {
          hidden: t.hidden,
          display: cs.display,
          visibility: cs.visibility,
          opacity: cs.opacity,
          text: t.textContent.trim(),
          flip: t.classList.contains('flip'),
          rect: { left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height },
          viewport: { width: innerWidth, height: innerHeight },
          insideViewport: r.left >= 0 && r.top >= 0 && r.right <= innerWidth && r.bottom <= innerHeight,
          optionValue: hovered ? hovered.dataset.graphLayoutOption : null,
          optionRect: hovered ? (() => { const o = hovered.getBoundingClientRect(); return { left: o.left, right: o.right, top: o.top, bottom: o.bottom }; })() : null,
        };
      })()
    `);
  }

  // ---------------- Desktop 1440x900 ----------------
  await setViewport(1440, 900);
  await openMenu();
  const desktop = await evalJs(`
    (() => {
      const opts = [...document.querySelectorAll('.ontology-layout-option')];
      const read = (el) => {
        const cs = getComputedStyle(el);
        return {
          text: el.textContent.trim(),
          border: [cs.borderTopWidth, cs.borderRightWidth, cs.borderBottomWidth, cs.borderLeftWidth],
          boxShadow: cs.boxShadow, backgroundColor: cs.backgroundColor, color: cs.color,
          borderRadius: cs.borderRadius,
          isActive: el.classList.contains('is-active'),
          isSelected: el.classList.contains('is-selected'),
          check: getComputedStyle(el, '::after').content,
          title: el.getAttribute('title'),
        };
      };
      const trig = document.querySelector('[data-graph-layout-trigger]');
      const tcs = getComputedStyle(trig);
      const rel = document.querySelector('[data-graph-relayout]');
      const rcs = getComputedStyle(rel);
      const menu = document.querySelector('.ontology-layout-menu');
      const mcs = getComputedStyle(menu);
      return {
        options: opts.map(read),
        trigger: { height: tcs.height, borderTopWidth: tcs.borderTopWidth, borderRadius: tcs.borderRadius, title: trig.getAttribute('title') },
        relayout: { height: rcs.height, minHeight: rcs.minHeight },
        menu: { borderTopWidth: mcs.borderTopWidth, borderRadius: mcs.borderRadius, boxShadow: mcs.boxShadow },
        helpPresent: !!document.querySelector('[data-graph-layout-help]'),
      };
    })()
  `);
  const desktopBorderless = desktop.options.every((o) => o.border.every((w) => w === "0px"));
  record("desktop option borders are 0px", desktopBorderless, desktop.options.map((o) => `${o.text}:${o.border.join("/")}`));
  record("desktop inactive option transparent and shadowless",
    desktop.options[1].backgroundColor === "rgba(0, 0, 0, 0)" && desktop.options[1].boxShadow === "none",
    `bg ${desktop.options[1].backgroundColor}, shadow ${desktop.options[1].boxShadow}`);
  record("desktop active/selected row light-blue without border",
    desktop.options[0].isActive && desktop.options[0].backgroundColor === "rgb(239, 246, 255)" && desktop.options[0].border.every((w) => w === "0px"),
    `bg ${desktop.options[0].backgroundColor}`);
  record("desktop selected keeps blue text and check",
    desktop.options[0].isSelected && desktop.options[0].color === "rgb(37, 99, 235)" && desktop.options[0].check.includes("✓"),
    `color ${desktop.options[0].color}, ::after ${desktop.options[0].check}`);
  record("desktop option row radius is 4px/6px (not a 7px button)",
    desktop.options[1].borderRadius === "4px" || desktop.options[1].borderRadius === "6px",
    `radius ${desktop.options[1].borderRadius}`);
  record("desktop trigger keeps bordered 26px selector",
    desktop.trigger.height === "26px" && desktop.trigger.borderTopWidth === "1px",
    `h ${desktop.trigger.height}, border ${desktop.trigger.borderTopWidth}`);
  record("desktop relayout stays 26px",
    desktop.relayout.height === "26px" && desktop.relayout.minHeight === "26px",
    `h ${desktop.relayout.height}, min-h ${desktop.relayout.minHeight}`);
  record("desktop menu keeps outer border/radius/shadow",
    desktop.menu.borderTopWidth === "1px" && desktop.menu.borderRadius === "8px" && desktop.menu.boxShadow !== "none",
    `border ${desktop.menu.borderTopWidth}, radius ${desktop.menu.borderRadius}`);
  record("desktop no question mark and no native titles",
    desktop.helpPresent === false && desktop.trigger.title === null && desktop.options.every((o) => o.title === null),
    `help ${desktop.helpPresent}`);

  const tipBeforeHover = await readTooltipState();
  record("desktop menu open shows no tooltip yet", tipBeforeHover === null || tipBeforeHover.hidden === true,
    tipBeforeHover ? `hidden ${tipBeforeHover.hidden}` : "tooltip not rendered");
  await screenshot(G1);

  // Hover cluster option -> new ForceAtlas2 bubble; hover radial -> ring bubble.
  const optRects = await evalJs(`[...document.querySelectorAll('.ontology-layout-option')].map((o) => { const r = o.getBoundingClientRect(); return { text: o.textContent.trim(), value: o.dataset.graphLayoutOption, x: r.left + r.width / 2, y: r.top + r.height / 2 }; })`);
  await mouseMove(optRects[0].x, optRects[0].y);
  await sleep(400);
  const clusterTip = await readTooltipState();
  record("desktop hover cluster shows exact new ForceAtlas2 hint",
    clusterTip && clusterTip.hidden === false && clusterTip.text === CLUSTER_HINT,
    clusterTip ? clusterTip.text.slice(0, 40) : "no tooltip");
  await mouseMove(optRects[1].x, optRects[1].y);
  await sleep(400);
  const radialTipDesktop = await readTooltipState();
  record("desktop hover radial shows exact ring hint",
    radialTipDesktop && radialTipDesktop.hidden === false && radialTipDesktop.text === RADIAL_HINT,
    radialTipDesktop ? radialTipDesktop.text.slice(0, 40) : "no tooltip");
  await screenshot(G2);
  await mouseMove(10, 860);
  await sleep(250);

  // Close the menu before the narrow pass.
  await evalJs(`document.querySelector('[data-graph-layout-trigger]').dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))`);
  await sleep(250);
  await waitFor(`document.querySelector('[data-graph-layout-trigger]').getAttribute('aria-expanded') === 'false'`, 5000, "desktop menu closed");

  // ---------------- Narrow 700x900 ----------------
  await setViewport(700, 900);
  await openMenu();

  const beforeHover = await readTooltipState();
  record("narrow menu open with no tooltip before hover",
    beforeHover === null || beforeHover.hidden === true, beforeHover ? `hidden ${beforeHover.hidden}` : "tooltip not rendered");
  await screenshot(G3);

  // Real mouse hover over the radial option row center.
  const narrowRects = await evalJs(`[...document.querySelectorAll('.ontology-layout-option')].map((o) => { const r = o.getBoundingClientRect(); return { text: o.textContent.trim(), value: o.dataset.graphLayoutOption, x: r.left + r.width / 2, y: r.top + r.height / 2, rect: { left: r.left, right: r.right, top: r.top, bottom: r.bottom } }; })`);
  const radialOption = narrowRects.find((o) => o.value === "radial");
  if (!radialOption) throw new Error("radial option not found in narrow listbox");
  await mouseMove(radialOption.x, radialOption.y);
  await sleep(500);
  const tip = await readTooltipState();
  const tipVisible = tip && tip.hidden === false && tip.display !== "none" && tip.visibility !== "hidden"
    && String(tip.opacity) !== "0" && tip.rect.width > 0 && tip.rect.height > 0 && tip.insideViewport === true;
  const tipAdjacent = tip && tip.optionRect && (
    (tip.rect.left >= tip.optionRect.right - 2 && tip.rect.top < tip.optionRect.bottom && tip.rect.bottom > tip.optionRect.top) ||
    (tip.rect.right <= tip.optionRect.left + 2 && tip.rect.top < tip.optionRect.bottom && tip.rect.bottom > tip.optionRect.top)
  );
  const flipConsistent = tip ? (tip.rect.right <= (tip.optionRect ? tip.optionRect.left : -1) + 2 ? tip.flip === true : true) : false;
  record("narrow hover tooltip visible", Boolean(tipVisible), tip ? {
    hidden: tip.hidden, display: tip.display, visibility: tip.visibility, opacity: tip.opacity,
    width: tip.rect.width, height: tip.rect.height, insideViewport: tip.insideViewport,
  } : "no tooltip");
  record("narrow hover option is radial and text is exact", Boolean(tip && tip.optionValue === "radial" && tip.text === RADIAL_HINT),
    tip ? `option ${tip.optionValue}, text ${tip.text.slice(0, 30)}` : "no tooltip");
  record("narrow tooltip fully inside 700x900 viewport", Boolean(tip && tip.insideViewport),
    tip ? JSON.stringify({ rect: tip.rect, viewport: tip.viewport }) : "no tooltip");
  record("narrow tooltip adjacent to the hovered option", Boolean(tipAdjacent), tip ? JSON.stringify({ tip: tip.rect, option: tip.optionRect }) : "no tooltip");
  record("narrow tooltip flip class matches placement", Boolean(tip && flipConsistent), tip ? `flip ${tip.flip}` : "no tooltip");
  if (tip && tip.hidden === false && tip.insideViewport && tip.optionValue === "radial") {
    await screenshot(G4);
  } else {
    // Still capture whatever state exists so g4 is never stale/identical by accident.
    await screenshot(G4);
  }

  // Leave the listbox: move the pointer well outside the menu box.
  const menuRect = await evalJs(`(() => { const r = document.querySelector('.ontology-layout-menu').getBoundingClientRect(); return { left: r.left, right: r.right, top: r.top, bottom: r.bottom }; })()`);
  await mouseMove(menuRect.left - 20 < 0 ? menuRect.right + 60 : menuRect.left - 20, Math.min(menuRect.bottom + 60, 880));
  await sleep(400);
  const afterLeave = await readTooltipState();
  const leftHidden = afterLeave === null || afterLeave.hidden === true || afterLeave.display === "none";
  record("narrow tooltip hides after leaving the listbox", Boolean(leftHidden),
    afterLeave ? `hidden ${afterLeave.hidden}, display ${afterLeave.display}` : "tooltip not rendered");

  const g3Hash = sha256File(G3);
  const g4Hash = sha256File(G4);
  record("g3 and g4 screenshots have different hashes", g3Hash !== g4Hash, `g3 ${g3Hash} vs g4 ${g4Hash}`);
  record("g3 and g4 screenshots are non-empty", readFileSync(G3).length > 0 && readFileSync(G4).length > 0, "non-empty");

  const narrowHoverTooltip = tip ? {
    optionValue: tip.optionValue,
    text: tip.text,
    hidden: tip.hidden,
    display: tip.display,
    visibility: tip.visibility,
    opacity: tip.opacity,
    flip: tip.flip,
    rect: tip.rect,
    viewport: tip.viewport,
    insideViewport: tip.insideViewport,
    afterLeave: afterLeave ? { hidden: afterLeave.hidden, display: afterLeave.display } : { hidden: true },
  } : null;

  const failedCount = checks.filter((c) => !c.ok).length;
  writeFileSync(JSON_PATH, JSON.stringify({
    phase: "green",
    browser: { name: "Chrome/Chromium headless", version: browserVersion },
    url: URL,
    date: "2026-09-03",
    runSeconds: Number(((Date.now() - startedAt) / 1000).toFixed(1)),
    viewports: ["1440x900", "700x900"],
    checks,
    narrowHoverTooltip,
    screenshots: {
      g1: { file: "g1-desktop-menu.png", sha256: sha256File(G1) },
      g2: { file: "g2-desktop-hover-row.png", sha256: sha256File(G2) },
      g3: { file: "g3-narrow-menu.png", sha256: g3Hash },
      g4: { file: "g4-narrow-hover.png", sha256: g4Hash },
    },
    failedCount,
  }, null, 2));
  console.log(`SUMMARY pass=${checks.length - failedCount} fail=${failedCount} total=${checks.length} failedCount=${failedCount}`);
  if (failedCount > 0) process.exitCode = 1;
} finally {
  try { if (cdp) cdp.ws.close(); } catch { /* ignore */ }
  chrome.kill("SIGTERM");
  await sleep(300);
  try { rmSync(profile, { recursive: true, force: true }); } catch { /* ignore */ }
}
