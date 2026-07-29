/* =====================================================================
 * BI Analyst Ontology Workbench — frontend logic
 *
 * Two modes share the same UI:
 *   - data:   classic BI-analyst chat against the ontology + SQLite
 *   - report: PDF/Word upload, Q&A over the uploaded report (optionally
 *             crossing into ontology/SQL via the 启用数据库查询 toggle)
 *
 * Each mode keeps its own bucket: chat history, inspector lists, system
 * prompt. Switching modes detaches one bucket's DOM nodes and attaches
 * the other's, so the user keeps each chat intact.
 *
 * SSE event shape is identical across modes; only the endpoints differ.
 * ===================================================================== */

(() => {
  // ------------------------------------------------------------------
  // Per-mode bucket
  // ------------------------------------------------------------------
  function makeBucket() {
    return {
      ontologyByCode: new Map(),       // code -> entity record
      toolCalls: [],                   // tool call records
      llmTurns: [],                    // {iteration, request, response}
      turnCount: 0,
      currentAssistantEl: null,
      currentAssistantText: "",
      systemPrompt: null,
      // Per-turn conclusion tracking — 📌-prefixed sentences extracted from
      // assistant text go to the middle dashboard as conclusion cards.
      conclusionSeen: new Set(),       // dedup within a session
      rootCauseSeen: new Set(),        // dedup 🔍 root-cause cards
      actionsSeen: new Set(),          // dedup 💡 action cards
      currentTurnTag: 0,               // increments per user turn (for card ids)
      // Pinned task list (TodoWrite). Latest full snapshot the agent wrote;
      // re-rendered into #chat-todo on every update and on mode switch.
      todos: [],
      // Every user question in this conversation, used by the pinned
      // question index and by the dashboard's question cards.
      questions: [],
      // Quadrant-assistant: ui-command queue. Commands extracted from each
      // llm_response stage here instead of firing immediately at the cockpit.
      // The user clicks an "执行" button rendered at end-of-turn to flush
      // them in one apply_batch postMessage.
      pendingCommands: [],
      // Detached DOM children (populated on mode switch-out)
      chatNodes: [],
      ontologyNodes: [],
      toolNodes: [],
      llmNodes: [],
      dashboardNodes: [],
      // Whether the mode currently has any chat content
      hasContent: false,
      dashboardHasContent: false,
      // Restorable history: id of the persisted conversation record this
      // bucket maps to (null = unsaved / fresh). Saved/updated in place.
      convId: null,
      // Stable title anchor for restored conversations (no turnQuestions).
      titleHint: null,
    };
  }

  const buckets = { data: makeBucket(), report: makeBucket() };
  let activeRequestController = null;

  // ------------------------------------------------------------------
  // Global state
  // ------------------------------------------------------------------
  const state = {
    meta: null,
    busy: false,
    activeTab: "tools",
    view: "workspace",                 // sidebar page router: which view is shown
    mode: "data",                      // "data" | "report"
    // Quadrant-assistant mode — when workbench is embedded inside the CEO
    // cockpit as a quadrant helper, location.search carries ?quadrant=KEY.
    // Non-null state.quadrant flips a few behaviors: brand badge, prompt
    // prefix injection, and ui-command block extraction on llm_response.
    quadrant: null,                    // "salesflow" | "assetflow" | "command" | "riskmatrix" | "reportmgmt" | null
    quadrantPromptSent: false,         // suppress repeated prefix per turn (we re-send each turn for safety)
    // Report-mode extras
    report: {
      // Multi-report support: `activeReports` is the list, `activeReport`
      // mirrors the first entry for legacy code paths (placeholder text,
      // single-line attach chip etc.).
      activeReports: [],               // [{id, filename, ...}, ...]
      activeReport: null,              // alias for activeReports[0] or null
      withDb: false,
      history: [],                     // list of records from /api/report/list
      sessionActivated: false,
      // History popover multi-select state — populated when the popover
      // is opened, cleared when it closes.
      historySelectedIds: new Set(),
    },
  };

  function B() { return buckets[state.mode]; }

  // ------------------------------------------------------------------
  // Elements
  // ------------------------------------------------------------------
  const el = {
    chatScroll:     document.getElementById("chat-scroll"),
    chatTodo:       document.getElementById("chat-todo"),
    chatTodoHead:   document.getElementById("chat-todo-head"),
    chatTodoCaret:  document.getElementById("chat-todo-caret"),
    chatTodoCount:  document.getElementById("chat-todo-count"),
    chatTodoList:   document.getElementById("chat-todo-list"),
    chatEmpty:      document.getElementById("chat-empty"),
    emptyGlyph:     document.getElementById("empty-glyph"),
    emptyTitle:     document.getElementById("empty-title"),
    emptyWelcome:   document.getElementById("empty-welcome"),
    emptyHints:     document.getElementById("empty-hints"),
    paneLabel:      document.getElementById("pane-label"),
    chatInput:      document.getElementById("chat-input"),
    btnSend:        document.getElementById("btn-send"),
    btnReset:       document.getElementById("btn-reset"),
    btnSettings:    document.getElementById("btn-settings"),
    modeSwitch:     document.getElementById("mode-switch"),
    modeBtns:       document.querySelectorAll(".mode-btn"),
    // Inspector collapse
    btnToggleInspector: document.getElementById("btn-toggle-inspector"),
    inspectorCollapseBtn: document.getElementById("inspector-collapse"),
    inspectorReopen:    document.getElementById("inspector-reopen"),
    // Composer (claude.ai-style)
    chatInputWrap:  document.getElementById("chat-input-wrap"),
    attachRow:      document.getElementById("attach-row"),
    attachChipName: document.getElementById("attach-chip-name"),
    attachChipMeta: document.getElementById("attach-chip-meta"),
    attachChipChange: document.getElementById("attach-chip-change"),
    attachChipRemove: document.getElementById("attach-chip-remove"),
    btnAttach:      document.getElementById("btn-attach"),
    fileInput:      document.getElementById("file-input"),
    withDb:         document.getElementById("with-db"),
    btnHistory:     document.getElementById("btn-history"),
    historyCount:   document.getElementById("history-count"),
    historyPopover: document.getElementById("history-popover"),
    historyClose:   document.getElementById("history-close"),
    historyList:    document.getElementById("history-list"),
    historySelectedCount: document.getElementById("history-selected-count"),
    historySelectAll:     document.getElementById("history-select-all"),
    historyClearSel:      document.getElementById("history-clear-sel"),
    historyActivateSel:   document.getElementById("history-activate-sel"),
    uploadStatus:   document.getElementById("upload-status"),
    // Settings modal
    settingsOverlay:    document.getElementById("settings-overlay"),
    settingsClose:      document.getElementById("settings-close"),
    settingsModel:      document.getElementById("settings-model"),
    settingsModelHint:  document.getElementById("settings-model-hint"),
    settingsMaxTokens:  document.getElementById("settings-max-tokens"),
    settingsTemp:       document.getElementById("settings-temperature"),
    settingsTempVal:    document.getElementById("settings-temp-val"),
    settingsStatus:     document.getElementById("settings-status"),
    settingsSave:       document.getElementById("settings-save"),
    settingsResetDefaults: document.getElementById("settings-reset-defaults"),
    settingsKeyAnthropic:       document.getElementById("settings-key-anthropic"),
    settingsKeyAnthropicStatus: document.getElementById("settings-key-anthropic-status"),
    settingsKeyAnthropicClear:  document.getElementById("settings-key-anthropic-clear"),
    settingsKeyQwen:            document.getElementById("settings-key-qwen"),
    settingsKeyQwenStatus:      document.getElementById("settings-key-qwen-status"),
    settingsKeyQwenClear:       document.getElementById("settings-key-qwen-clear"),
    settingsKeyDeepseek:        document.getElementById("settings-key-deepseek"),
    settingsKeyDeepseekStatus:  document.getElementById("settings-key-deepseek-status"),
    settingsKeyDeepseekClear:   document.getElementById("settings-key-deepseek-clear"),
    settingsThinkingField:      document.getElementById("settings-thinking-field"),
    settingsThinking:           document.getElementById("settings-thinking"),
    settingsThinkingStatus:     document.getElementById("settings-thinking-status"),
    settingsThinkingHint:       document.getElementById("settings-thinking-hint"),
    // Report-generation wizard
    btnReportgen:       document.getElementById("btn-reportgen"),
    reportgenOverlay:   document.getElementById("reportgen-overlay"),
    reportgenClose:     document.getElementById("reportgen-close"),
    rgStepper:          document.getElementById("rg-stepper"),
    rgBody:             document.getElementById("rg-body"),
    rgReview:           document.getElementById("rg-review"),
    rgPrev:             document.getElementById("rg-prev"),
    rgNext:             document.getElementById("rg-next"),
    rgConfirm:          document.getElementById("rg-confirm"),
    rgSavePlan:         document.getElementById("rg-save-plan"),
    // Data-source settings
    btnSources:         document.getElementById("btn-sources"),
    sourcesOverlay:     document.getElementById("sources-overlay"),
    sourcesClose:       document.getElementById("sources-close"),
    sourcesCancel:      document.getElementById("sources-cancel"),
    sourcesSave:        document.getElementById("sources-save"),
    sourcesRetrievalMode: document.getElementById("sources-retrieval-mode"),
    sourcesGraphField:  document.getElementById("sources-graph-field"),
    sourcesGraph:       document.getElementById("sources-graph"),
    sourcesBuildGraphRow:  document.getElementById("sources-build-graph-row"),
    sourcesBuildGraph:     document.getElementById("sources-build-graph"),
    sourcesBuildGraphHint: document.getElementById("sources-build-graph-hint"),
    sourcesOntology:    document.getElementById("sources-ontology"),
    sourcesDatabase:    document.getElementById("sources-database"),
    sourcesDorisField:  document.getElementById("sources-doris-field"),
    sourcesDorisJdbc:   document.getElementById("sources-doris-jdbc"),
    sourcesDorisDatabase: document.getElementById("sources-doris-database"),
    sourcesReadOntologyDb: document.getElementById("sources-read-ontology-db"),
    sourcesDorisDriver: document.getElementById("sources-doris-driver"),
    sourcesDorisUser:   document.getElementById("sources-doris-user"),
    sourcesDorisPass:   document.getElementById("sources-doris-pass"),
    sourcesStatus:      document.getElementById("sources-status"),
    // 本体适配 page (检索模式 / 本体源 / 图库源 — shares the /api/sources fields above)
    ontoAdaptCancel:    document.getElementById("onto-adapt-cancel"),
    ontoAdaptSave:      document.getElementById("onto-adapt-save"),
    ontoAdaptStatus:    document.getElementById("onto-adapt-status"),
    // Topbar
    agentName:      document.getElementById("agent-name"),
    topbarMeta:     document.getElementById("topbar-meta"),
    turnCounter:    document.getElementById("turn-counter"),
    tabs:           document.querySelectorAll(".tab"),
    panels:         document.querySelectorAll(".inspector-panel"),
    // Inspector containers
    ontologyList:   document.getElementById("ontology-list"),
    toolList:       document.getElementById("tool-list"),
    llmList:        document.getElementById("llm-list"),
    systemContent:  document.getElementById("system-content"),
    countOntology:  document.getElementById("count-ontology"),
    countTools:     document.getElementById("count-tools"),
    countLlm:       document.getElementById("count-llm"),
    // Middle dashboard pane
    dashboardPane:  document.getElementById("dashboard-pane"),
    dashboardList:  document.getElementById("dashboard-list"),
    dashboardEmpty: document.getElementById("dashboard-empty"),
    dashboardCount: document.getElementById("dashboard-count"),
    dashboardClear: document.getElementById("dashboard-clear"),
    dashboardCollapseBtn: document.getElementById("dashboard-collapse"),
    dashboardReopen: document.getElementById("dashboard-reopen"),
    btnToggleDashboard: document.getElementById("btn-toggle-dashboard"),
    sidebarCollapse: document.getElementById("sidebar-collapse"),
    sidebarReopen: document.getElementById("sidebar-reopen"),
  };

  // ------------------------------------------------------------------
  // Resizable layout (navigation + chat/dashboard split)
  // ------------------------------------------------------------------
  const layoutPrefs = {
    sidebar: "bi.layout.sidebarWidth",
    chat: "bi.layout.chatWidth",
  };

  function applyLayoutPrefs() {
    const sidebar = Number(localStorage.getItem(layoutPrefs.sidebar));
    if (Number.isFinite(sidebar) && sidebar >= 150 && sidebar <= 360) {
      document.documentElement.style.setProperty("--sidebar-width", `${sidebar}px`);
    }
    const chat = Number(localStorage.getItem(layoutPrefs.chat));
    if (Number.isFinite(chat) && chat >= 380) {
      document.documentElement.style.setProperty("--chat-width", `${chat}px`);
    }
  }

  function setupResizer(id, onMove, min, maxFn) {
    const handle = document.getElementById(id);
    if (!handle) return;
    handle.addEventListener("pointerdown", (ev) => {
      ev.preventDefault();
      handle.setPointerCapture(ev.pointerId);
      handle.classList.add("dragging");
      const move = (e) => onMove(Math.max(min, Math.min(maxFn(), e.clientX)));
      const end = () => {
        handle.classList.remove("dragging");
        handle.releasePointerCapture(ev.pointerId);
        handle.removeEventListener("pointermove", move);
        handle.removeEventListener("pointerup", end);
        handle.removeEventListener("pointercancel", end);
      };
      handle.addEventListener("pointermove", move);
      handle.addEventListener("pointerup", end);
      handle.addEventListener("pointercancel", end);
    });
  }

  applyLayoutPrefs();
  setupResizer(
    "sidebar-resizer",
    (x) => {
      const width = Math.round(x);
      document.documentElement.style.setProperty("--sidebar-width", `${width}px`);
      localStorage.setItem(layoutPrefs.sidebar, String(width));
    },
    150,
    () => Math.min(360, window.innerWidth * 0.35),
  );
  setupResizer(
    "workspace-resizer",
    (x) => {
      const split = document.querySelector(".split");
      if (!split) return;
      const width = Math.round(x - split.getBoundingClientRect().left);
      if (width < 380) return;
      document.documentElement.style.setProperty("--chat-width", `${width}px`);
      localStorage.setItem(layoutPrefs.chat, String(width));
    },
    380,
    () => window.innerWidth - 360,
  );

  // Default empty-state strings per mode
  const EMPTY_STATES = {
    data: {
      glyph: "◇",
      title: "硕磐财务 BI 智能分析",
      hints: [
        "管报收入总金额是多少?",
        "列出本体里所有业务对象",
        "应收账款账龄分布如何?",
      ],
    },
    report: {
      glyph: "📄",
      title: "智能报表分析",
      hints: [
        "请先上传一份 PDF / Word 报表",
        "勾选「启用数据库查询」可对账本体与 SQLite",
        "示例: 这份报表 Q3 收入同比变化多少?",
      ],
    },
  };

  // ------------------------------------------------------------------
  // Utilities
  // ------------------------------------------------------------------
  const KIND_LABELS = {
    term: "术语",
    business_object: "业务对象",
    logical_entity: "逻辑实体",
    attribute: "属性",
    relation: "关系",
    metric: "指标",
    activity: "活动",
    rule: "规则",
  };

  const ENTITY_CODE_RE = /\b(?:T\d{6}|BO\d{4}|LE\d{5}|AT\d{5}|ER\d{3}|M\d{3}|A\d{3}|R\d{3})\b/g;

  function esc(s) {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function highlightEntities(text) {
    return esc(text).replace(ENTITY_CODE_RE, (code) => {
      return `<span class="entity-ref" data-code="${code}">${code}</span>`;
    });
  }

  // Per-clause action menu for 根因分析 / 行动建议 cards. Each concrete
  // clause (a bullet / numbered point) gets one 行动 button that opens a
  // small dropdown of choices — actions bind to that specific clause.
  const ITEM_ACTIONS = {
    rootcause: [["ask", "追问"], ["verify", "验证"]],
    actions:   [["supervise", "转督办"], ["execute", "转执行"],
                ["simulate", "转模拟"], ["risk", "转风险分析"]],
  };

  function actionControlHTML(kind) {
    const acts = ITEM_ACTIONS[kind] || [];
    const choices = acts.map(([a, l]) =>
      `<button type="button" class="dash-act-choice" data-act="${a}">${esc(l)}</button>`
    ).join("");
    return (
      '<div class="dash-item-actions">' +
      '<button type="button" class="dash-act-btn" aria-haspopup="true" aria-expanded="false">行动 ▾</button>' +
      `<div class="dash-act-menu" hidden role="menu">${choices}</div>` +
      '</div>'
    );
  }

  // Parse a multi-line block into:
  //   · sub-headers   — bold-only headings (**第 N 层…**) / emoji section
  //                     lines → shown as context, NOT actionable
  //   · clauses       — bullet / numbered lines → each gets its own 行动 btn
  // Continuation lines fold into the open clause; text before the first
  // clause/header is a plain preamble.
  function buildActionableBody(text, kind) {
    const acts = ITEM_ACTIONS[kind];
    const raw = String(text == null ? "" : text).replace(/\r/g, "");
    if (!acts) return `<div class="dash-body">${highlightEntities(raw)}</div>`;

    const lines = raw.split("\n");
    const itemRe = /^\s*(?:\d+[.、)]|[（(]\s*\d+\s*[）)]|[-*•·]|[一二三四五六七八九十]+[、.)])\s+/;
    const emojiHeadRe = /^\s*(?:🔍|💡|📌|📊|📈|📄|🧩|🧠|✅|⚠️)/;
    const boldHeadRe = /^\s*\*\*[^*].*?\*\*\s*[:：]?\s*$/;

    const segs = [];               // {type:'head'|'pre', text} | {type:'item', lines:[]}
    let cur = null;                // open item line buffer
    const flush = () => { if (cur) { segs.push({ type: "item", lines: cur }); cur = null; } };

    for (const ln of lines) {
      if (itemRe.test(ln)) { flush(); cur = [ln]; }
      else if (emojiHeadRe.test(ln) || boldHeadRe.test(ln)) {
        flush();
        segs.push({ type: "head", text: ln });
      } else if (cur) { cur.push(ln); }
      else if (ln.trim()) { segs.push({ type: "pre", text: ln }); }
    }
    flush();

    // Strip the leading bullet/number marker (display only) — the structure
    // was already captured by the parser above.
    const stripMarker = (s) => s.replace(itemRe, "").replace(/^\s*[-*•·]\s+/, "");
    const stripBold = (s) => s.replace(/\*\*/g, "");
    const clean = (s) => stripBold(s).trim();

    const ctrl = () => actionControlHTML(kind);
    const hasItem = segs.some(s => s.type === "item");
    let html = "";
    if (!hasItem) {
      // No list structure — treat the whole block as a single clause.
      const body = clean(raw);
      if (body) {
        html = `<div class="dash-item"><div class="dash-item-text">${highlightEntities(body)}</div>${ctrl()}</div>`;
      }
      return `<div class="dash-body has-items">${html || highlightEntities(raw)}</div>`;
    }
    for (const s of segs) {
      if (s.type === "head") {
        html += `<div class="dash-seg-head">${highlightEntities(clean(s.text))}</div>`;
      } else if (s.type === "pre") {
        const p = clean(s.text);
        if (p) html += `<div class="dash-pre">${highlightEntities(p)}</div>`;
      } else {
        let t = s.lines.join("\n").replace(/\s+$/, "");
        // Drop the marker from the first line, bold markers everywhere.
        const nl = t.indexOf("\n");
        if (nl < 0) t = stripMarker(t);
        else t = stripMarker(t.slice(0, nl)) + t.slice(nl);
        t = stripBold(t).trim();
        if (!t) continue;
        html += `<div class="dash-item"><div class="dash-item-text">${highlightEntities(t)}</div>${ctrl()}</div>`;
      }
    }
    return `<div class="dash-body has-items">${html}</div>`;
  }

  // Place the fixed-position menu under (or above) its 行动 button,
  // right-aligned and clamped to the viewport.
  function positionActMenu(btn, menu) {
    const r = btn.getBoundingClientRect();
    const mw = menu.offsetWidth || 120;
    const mh = menu.offsetHeight || 120;
    let left = Math.max(8, Math.min(r.right - mw, window.innerWidth - mw - 8));
    let top = r.bottom + 4;
    if (top + mh > window.innerHeight - 8) {
      const above = r.top - mh - 4;
      top = above >= 8 ? above : Math.max(8, window.innerHeight - mh - 8);
    }
    menu.style.left = `${Math.round(left)}px`;
    menu.style.top = `${Math.round(top)}px`;
  }

  // Single delegated controller for every 行动 dropdown on the page.
  function closeAllActMenus(except) {
    document.querySelectorAll(".dash-act-menu:not([hidden])").forEach(m => {
      if (m === except) return;
      m.hidden = true;
      const b = m.parentElement && m.parentElement.querySelector(".dash-act-btn");
      if (b) b.setAttribute("aria-expanded", "false");
    });
  }
  document.addEventListener("click", (e) => {
    const btn = e.target.closest && e.target.closest(".dash-act-btn");
    if (btn) {
      e.preventDefault();
      e.stopPropagation();
      const menu = btn.parentElement.querySelector(".dash-act-menu");
      const wasOpen = menu && !menu.hidden;
      closeAllActMenus(menu);
      if (menu && !wasOpen) {
        menu.hidden = false;
        btn.setAttribute("aria-expanded", "true");
        positionActMenu(btn, menu);
      } else if (menu) {
        menu.hidden = true;
        btn.setAttribute("aria-expanded", "false");
      }
      return;
    }
    const choice = e.target.closest && e.target.closest(".dash-act-choice");
    if (choice) {
      e.preventDefault();
      e.stopPropagation();
      const act = choice.getAttribute("data-act");
      const item = choice.closest(".dash-item");
      closeAllActMenus();
      // 转督办 is wired end-to-end: send to the responsible owner and auto
      // create a task order (任务令).
      if (act === "supervise" && item) dispatchSupervise(item);
      // 追问 → 把该条根因拷贝到对话框(不发送,交用户补充)。
      else if (act === "ask" && item) copyClauseToInput(item);
      return;
    }
    closeAllActMenus();
  });

  // ── 转督办 → 发送督办 + 自动生成任务令 ──────────────────────────────
  function localTaskSeq() {
    let n = parseInt(localStorage.getItem("wbTaskOrderSeq") || "0", 10);
    n = (isNaN(n) ? 0 : n) + 1;
    try { localStorage.setItem("wbTaskOrderSeq", String(n)); } catch (_) {}
    return 1000 + n;
  }
  function flashItem(item, msg, isErr) {
    let f = item.querySelector(":scope > .dash-item-flash");
    if (!f) {
      f = document.createElement("div");
      f.className = "dash-item-flash";
      item.appendChild(f);
    }
    f.textContent = msg;
    f.style.color = isErr ? "var(--danger,#8d6e63)" : "var(--ok,#00c853)";
  }
  function dispatchSupervise(item) {
    if (item.dataset.supervised === "1") {
      flashItem(item, "✅ 该条已督办,任务令已生成", false);
      return;
    }
    const txt = ((item.querySelector(".dash-item-text") || {}).textContent || "").trim();
    if (!txt) return;
    const card = item.closest(".dash-card");
    const turnTag = (card && card.dataset.turn) || (B().currentTurnTag || 1);
    const quad = state.quadrant || null;
    const source = quad
      ? ((typeof QUADRANT_PROMPT_META !== "undefined" && QUADRANT_PROMPT_META[quad] &&
          QUADRANT_PROMPT_META[quad].label) || "象限分析")
      : "通用AI助手";
    item.dataset.supervised = "1";
    item.classList.add("is-supervised");
    flashItem(item, "✅ 已发送给负责人督办 · 正在生成任务令…", false);

    const target = (window.parent && window.parent !== window) ? window.parent : null;
    if (!target) {
      flashItem(item, `✅ 已发送给负责人督办 · 已自动生成任务令 #${localTaskSeq()}`, false);
      return;
    }
    const reqId = "task-" + Date.now() + "-" + Math.floor(Math.random() * 1000);
    function ackHandler(ev) {
      const m = ev.data;
      if (!m || m.channel !== "cockpit-task-order-ack" || m.req !== reqId) return;
      window.removeEventListener("message", ackHandler);
      clearTimeout(timer);
      const idTxt = m.taskId ? ` #${m.taskId}` : "";
      const owner = m.owner ? `,责任人:${m.owner}` : "";
      flashItem(item, `✅ 已发送给负责人督办 · 已自动生成任务令${idTxt}${owner}`, false);
    }
    const timer = setTimeout(() => {
      window.removeEventListener("message", ackHandler);
      flashItem(item, `✅ 已发送给负责人督办 · 已自动生成任务令 #${localTaskSeq()}`, false);
    }, 4000);
    window.addEventListener("message", ackHandler);
    try {
      target.postMessage({
        channel: "cockpit-task-order",
        quadrant: quad,
        source: source,
        turn: String(turnTag),
        clause: txt,
        ts: new Date().toISOString(),
        req: reqId,
      }, "*");
    } catch (err) {
      window.removeEventListener("message", ackHandler);
      clearTimeout(timer);
      flashItem(item, "督办发送失败:" + String((err && err.message) || err), true);
    }
  }
  // ── 追问 → 复用对话框 ──────────────────────────────────────────────
  function clauseText(item) {
    return ((item.querySelector(".dash-item-text") || {}).textContent || "").trim();
  }
  function autosizeInput() {
    if (!el.chatInput) return;
    el.chatInput.style.height = "auto";
    el.chatInput.style.height = Math.min(el.chatInput.scrollHeight, 140) + "px";
  }
  // 追问:把该条根因原文拷贝进对话框,聚焦但不发送,等用户继续补充。
  function copyClauseToInput(item) {
    const txt = clauseText(item);
    if (!txt || !el.chatInput) return;
    const cur = el.chatInput.value.trim();
    el.chatInput.value = cur ? cur + "\n" + txt : txt;
    autosizeInput();
    el.chatInput.focus();
    try {
      el.chatInput.setSelectionRange(el.chatInput.value.length, el.chatInput.value.length);
    } catch (_) {}
    flashItem(item, "✅ 已填入对话框,可补充后发送", false);
  }

  // A fixed menu can't follow its anchor through scroll/resize — just close.
  window.addEventListener("scroll", () => closeAllActMenus(), true);
  window.addEventListener("resize", () => closeAllActMenus());
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeAllActMenus();
  });

  function el_h(tag, cls, html) {
    const x = document.createElement(tag);
    if (cls) x.className = cls;
    if (html !== undefined) x.innerHTML = html;
    return x;
  }

  // Pixel threshold below which we consider the user "pinned" to the bottom.
  // While pinned, new content auto-scrolls; once they scroll up further than
  // this, auto-scroll backs off and they keep manual control of the wheel.
  const SCROLL_PIN_PX = 120;

  function isChatPinnedToBottom() {
    const sc = el.chatScroll;
    if (!sc) return true;
    return sc.scrollHeight - sc.scrollTop - sc.clientHeight < SCROLL_PIN_PX;
  }

  // Soft scroll — only follows the bottom when the user is already there.
  // Use this for streamed assistant deltas, tool steps, charts, tables, etc.
  function scrollChatBottom() {
    if (!el.chatScroll) return;
    if (isChatPinnedToBottom()) {
      el.chatScroll.scrollTop = el.chatScroll.scrollHeight;
    }
  }

  // Hard scroll — always jumps to the bottom regardless of user position.
  // Reserve for explicit user actions (sending a new message) where the user
  // expects to see their own input land at the bottom.
  function scrollChatBottomForce() {
    if (!el.chatScroll) return;
    el.chatScroll.scrollTop = el.chatScroll.scrollHeight;
  }

  // ------------------------------------------------------------------
  // Wheel forwarding for chat-scroll
  // ------------------------------------------------------------------
  // The chat content embeds nested scroll containers (`.step pre`,
  // `.table-scroll`) and ECharts <canvas> elements. Browsers' default
  // scroll-chaining is unreliable around these — the user reports that
  // wheeling over chat content does nothing while only the visible
  // scrollbar works. We explicitly forward wheel deltas to chat-scroll
  // unless the wheel target is *inside an inner scroll that still has
  // capacity in that direction*. In that case the inner scroll handles
  // it (so users can still read long tool-step output by wheeling).
  function setupChatWheelForwarding() {
    const chat = el.chatScroll;
    if (!chat) return;
    chat.addEventListener("wheel", (e) => {
      const dy = e.deltaY;
      if (!dy) return;
      let node = e.target;
      while (node && node !== chat) {
        if (node instanceof HTMLElement) {
          const cs = getComputedStyle(node);
          const ovy = cs.overflowY;
          const scrollable = (ovy === "auto" || ovy === "scroll") &&
                             node.scrollHeight > node.clientHeight;
          if (scrollable) {
            const atTop = node.scrollTop <= 0;
            const atBottom = node.scrollTop + node.clientHeight >= node.scrollHeight - 1;
            if ((dy < 0 && !atTop) || (dy > 0 && !atBottom)) {
              return;  // inner has room — let the browser scroll it
            }
          }
        }
        node = node.parentElement;
      }
      // No inner container can absorb this wheel — drive chat-scroll
      // directly. Without this, ECharts canvas / boundary-saturated <pre>
      // would silently swallow the wheel without scrolling anything.
      chat.scrollTop += dy;
      e.preventDefault();
    }, { passive: false });
  }

  function fmtDuration(ms) {
    if (ms < 1000) return ms + "ms";
    return (ms / 1000).toFixed(2) + "s";
  }

  function fmtBytes(n) {
    if (!n) return "0 B";
    if (n < 1024) return n + " B";
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
    return (n / 1024 / 1024).toFixed(1) + " MB";
  }

  function fmtDate(iso) {
    if (!iso) return "";
    try {
      const d = new Date(iso);
      return d.toLocaleString("zh-CN", { hour12: false });
    } catch (e) { return iso; }
  }

  function shorten(s, n) {
    if (!s) return "";
    s = String(s).replace(/\n/g, " ");
    return s.length > n ? s.slice(0, n) + "…" : s;
  }

  function toolPreview(name, input) {
    if (!input) return "";
    if (input.query)  return `"${shorten(input.query, 80)}"`;
    if (input.term)   return `"${shorten(input.term, 80)}"`;
    if (input.metric) return `"${shorten(input.metric, 80)}"`;
    if (input.entity) return `"${shorten(input.entity, 80)}"`;
    if (input.table)  return `"${shorten(input.table, 80)}"`;
    if (input.sql)    return shorten(input.sql, 100);
    const keys = Object.keys(input);
    if (keys.length === 0) return "(no args)";
    return shorten(JSON.stringify(input), 100);
  }

  // ------------------------------------------------------------------
  // Tabs
  // ------------------------------------------------------------------
  el.tabs.forEach((t) => {
    t.addEventListener("click", () => {
      const tab = t.dataset.tab;
      state.activeTab = tab;
      el.tabs.forEach((x) => x.classList.toggle("active", x === t));
      el.panels.forEach((p) => p.classList.toggle("active", p.dataset.panel === tab));
      if (tab === "system") loadSystemPrompt();
    });
  });

  // ------------------------------------------------------------------
  // Sidebar page router — workspace(chat+dashboard) is shared by
  // 智能分析/报表分析; 本体内容 / 系统调用记录 / 数据源 / 模型参数 /
  // 记忆管理 are standalone full-area pages.
  // ------------------------------------------------------------------
  const viewSections = document.querySelectorAll(".app-main .view");
  const navItems = document.querySelectorAll(".sidebar .nav-item");

  function setActiveNav() {
    const view = state.view || "workspace";
    navItems.forEach((b) => {
      const on = b.dataset.mode
        ? (view === "workspace" && b.dataset.mode === state.mode)  // mode buttons
        : (b.dataset.view === view);
      b.classList.toggle("active", on);
    });
  }

  function showView(view) {
    state.view = view;
    viewSections.forEach((s) => s.classList.toggle("active", s.dataset.view === view));
    setActiveNav();
    if (view === "syslog" && state.activeTab === "system") loadSystemPrompt();
  }

  navItems.forEach((b) => {
    b.addEventListener("click", () => {
      const view = b.dataset.view;
      if (b.dataset.mode) { showView("workspace"); return; }  // switchMode wired separately
      if (view === "sources") { openSources(); }      // fetch + populate, then show
      else if (view === "ontology-adapt") { openOntologyAdapt(); }  // shares /api/sources
      else if (view === "model") { openSettings(); }  // clear status, then show
      else if (view === "roles") { openRoles(); }     // fetch current roles, then show
      else { showView(view); }
    });
  });

  // ------------------------------------------------------------------
  // Restorable conversation history (sidebar 「最近」)
  // Each conversation persists server-side (messages + rendered chat/dashboard
  // HTML). The 最近 list is filtered to the current mode, so restoring is
  // always same-mode (no cross-mode context clobbering).
  // ------------------------------------------------------------------
  const recentListEl = document.getElementById("recent-list");

  function conversationTitle() {
    const b = B();
    const tq = b.turnQuestions || {};
    // First question identifies the conversation; titleHint preserves it for
    // restored conversations (whose turnQuestions map isn't repopulated).
    const q = tq[1] || tq[Object.keys(tq)[0]] || b.titleHint || "";
    return (q || "未命名对话").slice(0, 60);
  }

  function collectHtml(container, emptyEl) {
    if (!container) return "";
    let html = "";
    container.childNodes.forEach((n) => {
      if (n === emptyEl) return;
      if (n.nodeType === 1) html += n.outerHTML;
    });
    return html;
  }

  async function saveCurrentConversation() {
    const b = B();
    if (!b.hasContent) return;  // nothing worth saving yet
    try {
      const r = await fetch("/api/conversations/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mode: state.mode,
          cid: b.convId,
          title: conversationTitle(),
          chat_html: collectHtml(el.chatScroll, el.chatEmpty),
          dashboard_html: collectHtml(el.dashboardList, el.dashboardEmpty),
          ontology_html: collectHtml(el.ontologyList),
          tools_html: collectHtml(el.toolList),
          llm_html: collectHtml(el.llmList),
        }),
      });
      if (r.ok) { const d = await r.json(); if (d && d.id) b.convId = d.id; }
    } catch (e) { /* history is best-effort */ }
    loadRecent();
  }

  async function loadRecent() {
    if (!recentListEl) return;
    try {
      const r = await fetch("/api/conversations?mode=" + encodeURIComponent(state.mode));
      const d = await r.json();
      renderRecent(d.conversations || []);
    } catch (e) { /* ignore */ }
  }

  function renderRecent(items) {
    if (!recentListEl) return;
    recentListEl.innerHTML = "";
    if (!items.length) {
      const e = document.createElement("div");
      e.className = "recent-empty";
      e.textContent = "暂无历史会话";
      recentListEl.appendChild(e);
      return;
    }
    const activeId = B().convId;
    items.forEach((it) => {
      const row = document.createElement("div");
      row.className = "recent-item" + (it.id === activeId ? " active" : "");
      row.title = it.title || "未命名对话";
      const t = document.createElement("span");
      t.className = "recent-title";
      t.textContent = it.title || "未命名对话";
      row.appendChild(t);
      const del = document.createElement("button");
      del.className = "recent-del";
      del.textContent = "✕";
      del.title = "删除该会话";
      del.addEventListener("click", (ev) => { ev.stopPropagation(); deleteRecent(it.id); });
      row.appendChild(del);
      row.addEventListener("click", () => restoreConversation(it.id));
      recentListEl.appendChild(row);
    });
  }

  async function deleteRecent(id) {
    try { await fetch("/api/conversations/" + id, { method: "DELETE" }); } catch (e) {}
    ["data", "report"].forEach((m) => { if (buckets[m].convId === id) buckets[m].convId = null; });
    loadRecent();
  }

  async function restoreConversation(id) {
    if (state.busy) {
      if (activeRequestController) activeRequestController.abort();
      const resetUrl = state.mode === "report" ? "/api/report/session/reset" : "/api/session/reset";
      try { await fetch(resetUrl, { method: "POST" }); } catch (e) {}
      setBusy(false);
    }
    // Restoring is read-only. Never snapshot the currently visible draft here:
    // doing so creates a new conversation and moves it to the top merely by
    // clicking history. A conversation is persisted/ordered only at turn end.
    let rec;
    try {
      const r = await fetch("/api/conversations/restore", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id }),
      });
      if (!r.ok) return;
      rec = await r.json();
    } catch (e) { return; }
    if (rec.mode && rec.mode !== state.mode) switchMode(rec.mode);
    const b = B();
    // Swap in the saved transcript + dashboard snapshot.
    el.chatScroll.innerHTML = rec.chat_html || "";
    el.dashboardList.innerHTML = rec.dashboard_html || "";
    moveRestoredInteractiveCardsToChat();
    el.ontologyList.innerHTML = rec.ontology_html || "";
    el.toolList.innerHTML = rec.tools_html || "";
    el.llmList.innerHTML = rec.llm_html || "";
    hydrateRestoredChat();
    indexQuestionsFromChat();
    ensureRestoredDashboardQuestions();
    hydrateRestoredInspector();
    hydrateRestoredDashboard();
    b.hasContent = !!(rec.chat_html && rec.chat_html.trim());
    b.dashboardHasContent = !!el.dashboardList.querySelector(".dash-card");
    updateDashboardCount();
    // TodoWrite progress is intentionally not part of the persisted
    // conversation snapshot; never leave the previous conversation's tasks
    // visible when opening another history record.
    b.todos = [];
    renderTodoPanel();
    b.turnCount = b.questions.length;
    updateTurnCounter();
    el.countOntology.textContent = String(el.ontologyList.querySelectorAll(".entity-card").length);
    el.countTools.textContent = String(el.toolList.querySelectorAll(".tool-card").length);
    el.countLlm.textContent = String(el.llmList.querySelectorAll(".llm-card").length);
    if (el.chatEmpty && !b.hasContent) {
      if (!el.chatEmpty.parentNode) el.chatScroll.appendChild(el.chatEmpty);
      el.chatEmpty.style.display = "";
    }
    if (el.dashboardEmpty && !b.dashboardHasContent) {
      if (!el.dashboardEmpty.parentNode) el.dashboardList.appendChild(el.dashboardEmpty);
      el.dashboardEmpty.style.display = "";
    } else if (el.dashboardEmpty) {
      el.dashboardEmpty.style.display = "none";
    }
    b.convId = rec.id;
    // Restored transcripts carry no turnQuestions, so anchor the title here;
    // otherwise a later save would relabel it 「未命名对话」.
    b.titleHint = rec.title || "";
    showView("workspace");
    loadRecent();
    if (typeof scrollChatBottom === "function") scrollChatBottom();
  }

  // ------------------------------------------------------------------
  // Personal account settings (username + theme) — browser-local prefs
  // ------------------------------------------------------------------
  const ACCT_NAME_KEY = "bi.userName";
  const ACCT_THEME_KEY = "bi.theme";

  function applyTheme(theme) {
    document.documentElement.classList.toggle("theme-light", theme === "light");
  }

  function readPref(key, fallback) {
    try { return localStorage.getItem(key) || fallback; } catch (e) { return fallback; }
  }

  function renderAccountChip() {
    const name = readPref(ACCT_NAME_KEY, "分析员") || "分析员";
    const nameEl = document.getElementById("account-name");
    const avEl = document.getElementById("account-avatar");
    if (nameEl) nameEl.textContent = name;
    if (avEl) avEl.textContent = name.slice(0, 1);
  }

  function openAccount() {
    const nameInput = document.getElementById("account-name-input");
    const themeToggle = document.getElementById("account-theme-light");
    if (nameInput) nameInput.value = readPref(ACCT_NAME_KEY, "") || "";
    if (themeToggle) themeToggle.checked = readPref(ACCT_THEME_KEY, "dark") === "light";
    const st = document.getElementById("account-status");
    if (st) st.textContent = "";
    showView("account");
  }

  function saveAccount() {
    const nameInput = document.getElementById("account-name-input");
    const themeToggle = document.getElementById("account-theme-light");
    const name = ((nameInput && nameInput.value) || "").trim() || "分析员";
    const theme = (themeToggle && themeToggle.checked) ? "light" : "dark";
    try {
      localStorage.setItem(ACCT_NAME_KEY, name);
      localStorage.setItem(ACCT_THEME_KEY, theme);
    } catch (e) {}
    applyTheme(theme);
    renderAccountChip();
    const st = document.getElementById("account-status");
    if (st) {
      st.textContent = "✓ 已保存";
      st.className = "settings-status success";
      setTimeout(() => { if (st) st.textContent = ""; }, 2000);
    }
  }

  (function bootAccount() {
    // URL ?theme=light still wins (embedding); else use the saved preference.
    let urlTheme = null;
    try { urlTheme = new URLSearchParams(location.search).get("theme"); } catch (e) {}
    if (urlTheme !== "light") applyTheme(readPref(ACCT_THEME_KEY, "dark"));
    renderAccountChip();
    const acctBtn = document.getElementById("sidebar-account");
    if (acctBtn) acctBtn.addEventListener("click", openAccount);
    const acctSave = document.getElementById("account-save");
    if (acctSave) acctSave.addEventListener("click", saveAccount);
  })();

  // ------------------------------------------------------------------
  // 角色选择(自身角色 + Agent 回答风格)— 注入系统提示,真正影响回答
  // ------------------------------------------------------------------
  const rolesState = { user_role: "", agent_pref: "", userOptions: [], agentOptions: [] };

  function renderRoleGroup(containerId, options, selectedKey, onPick) {
    const box = document.getElementById(containerId);
    if (!box) return;
    box.innerHTML = "";
    // Leading 「不指定」(key "") lets the user clear the slot.
    const all = [{ key: "", label: "不指定", desc: "不设置该项偏好,使用 Agent 默认行为。" }]
      .concat(options || []);
    all.forEach((opt) => {
      const card = el_h("div", "role-option" + (opt.key === selectedKey ? " selected" : ""));
      card.innerHTML = `<span class="role-opt-label">${esc(opt.label)}</span>` +
        (opt.desc ? `<span class="role-opt-desc">${esc(opt.desc)}</span>` : "");
      card.addEventListener("click", () => onPick(opt.key));
      box.appendChild(card);
    });
  }

  function renderRoles() {
    renderRoleGroup("roles-user", rolesState.userOptions, rolesState.user_role, (k) => {
      rolesState.user_role = k; renderRoles();
    });
    renderRoleGroup("roles-agent", rolesState.agentOptions, rolesState.agent_pref, (k) => {
      rolesState.agent_pref = k; renderRoles();
    });
  }

  async function openRoles() {
    const st = document.getElementById("roles-status");
    if (st) { st.textContent = ""; st.className = "settings-status"; }
    try {
      const r = await fetch("/api/roles");
      if (r.ok) {
        const d = await r.json();
        rolesState.user_role = d.user_role || "";
        rolesState.agent_pref = d.agent_pref || "";
        rolesState.userOptions = d.user_role_options || [];
        rolesState.agentOptions = d.agent_pref_options || [];
      }
    } catch (e) {}
    renderRoles();
    showView("roles");
  }

  async function saveRoles() {
    const st = document.getElementById("roles-status");
    if (st) { st.textContent = "保存中…"; st.className = "settings-status pending"; }
    try {
      const r = await fetch("/api/roles", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_role: rolesState.user_role, agent_pref: rolesState.agent_pref }),
      });
      if (!r.ok) throw new Error("HTTP " + r.status);
      if (st) {
        st.textContent = "✓ 已保存,自下一条提问起生效";
        st.className = "settings-status success";
        setTimeout(() => { if (st) st.textContent = ""; }, 2500);
      }
    } catch (e) {
      if (st) { st.textContent = "保存失败: " + (e.message || e); st.className = "settings-status error"; }
    }
  }

  (function bootRoles() {
    const saveBtn = document.getElementById("roles-save");
    if (saveBtn) saveBtn.addEventListener("click", saveRoles);
    const cancelBtn = document.getElementById("roles-cancel");
    if (cancelBtn) cancelBtn.addEventListener("click", () => showView("workspace"));
  })();

  // ------------------------------------------------------------------
  // Meta / bootstrap
  // ------------------------------------------------------------------
  async function loadMeta() {
    try {
      const r = await fetch("/api/meta");
      const data = await r.json();
      state.meta = data;
      renderTopbarMeta();
      renderEmptyState();
      if (data.llm) hydrateSettings(data.llm);
      // Restore any server-side report-mode state (survives page reload)
      await refreshReportStatus();
      await refreshReportHistory();
    } catch (e) {
      console.error("meta load failed", e);
    }
  }

  function currentAgentMeta() {
    if (!state.meta) return null;
    if (state.mode === "report") return state.meta.report_agent || state.meta.agent;
    return state.meta.agent;
  }

  function renderTopbarMeta() {
    if (!state.meta) return;
    const data = state.meta;
    const agent = currentAgentMeta();
    if (agent && el.agentName) el.agentName.textContent = agent.name;
    // Model/DB/ontology stats panel was removed from the sidebar — keep the
    // brand-name update above, skip the (now absent) meta strip.
    if (!el.topbarMeta) return;
    const s = data.ontology_stats;
    const cur = (data.llm && data.llm.current) || null;
    const modelLabel = (() => {
      if (!cur) return esc((agent && agent.model) || "default");
      const m = (data.llm.models || []).find(x => x.key === cur.model_key);
      return esc(m ? m.label : cur.model_key);
    })();
    const metaParts = [
      `<span class="kv"><span class="kv-k">MODEL</span><span class="kv-v">${modelLabel}</span></span>`,
    ];
    if (cur) {
      metaParts.push(
        `<span class="kv"><span class="kv-k">MAX_T</span><span class="kv-v">${cur.max_tokens}</span></span>`,
        `<span class="kv"><span class="kv-k">TEMP</span><span class="kv-v">${Number(cur.temperature).toFixed(2)}</span></span>`,
      );
      const m = (data.llm.models || []).find(x => x.key === cur.model_key);
      const supportsThinking = !!(m && m.supports_thinking);
      const thinkingActive = !!cur.thinking && supportsThinking;
      if (thinkingActive) {
        metaParts.push(
          `<span class="kv"><span class="kv-k">THINK</span><span class="kv-v">on</span></span>`,
        );
      }
    }
    metaParts.push(
      `<span class="kv"><span class="kv-k">DB</span><span class="kv-v">${esc(data.db_path)}</span></span>`,
      `<span class="kv"><span class="kv-k">BO</span><span class="kv-v">${s.business_objects}</span></span>`,
      `<span class="kv"><span class="kv-k">LE</span><span class="kv-v">${s.logical_entities}</span></span>`,
      `<span class="kv"><span class="kv-k">METRICS</span><span class="kv-v">${s.metrics}</span></span>`,
      `<span class="kv"><span class="kv-k">TERMS</span><span class="kv-v">${s.terms}</span></span>`,
    );
    el.topbarMeta.innerHTML = metaParts.join("");
  }

  function renderEmptyState() {
    const cfg = EMPTY_STATES[state.mode];
    // In quadrant-assistant mode each quadrant has its own title / greeting /
    // example questions so the workbench reads as that quadrant's助手.
    const qMeta = (state.quadrant &&
      typeof QUADRANT_PROMPT_META !== "undefined" &&
      QUADRANT_PROMPT_META[state.quadrant]) || null;
    el.emptyGlyph.textContent = cfg.glyph;
    el.emptyTitle.textContent = qMeta ? (qMeta.emptyTitle || qMeta.label) : cfg.title;
    if (qMeta) {
      el.emptyWelcome.textContent = qMeta.welcome || "";
    } else {
      const agent = currentAgentMeta();
      el.emptyWelcome.textContent =
        (agent && (agent.welcome_message || agent.description)) || "";
    }
    const hints = (qMeta && Array.isArray(qMeta.hints) && qMeta.hints.length)
      ? qMeta.hints : cfg.hints;
    el.emptyHints.innerHTML = hints.map(h =>
      `<div class="hint-row"><span class="hint-key">试试</span><span class="hint-val">${esc(h)}</span></div>`
    ).join("");
    // Re-bind hint click (delegation gets us one click handler below)
  }

  // Prefill input from hint rows (delegation survives re-renders)
  el.emptyHints.addEventListener("click", (e) => {
    const row = e.target.closest(".hint-row");
    if (!row) return;
    const val = row.querySelector(".hint-val");
    if (val) {
      el.chatInput.value = val.textContent;
      el.chatInput.focus();
    }
  });

  // ------------------------------------------------------------------
  // Settings modal
  // ------------------------------------------------------------------
  function hydrateSettings(llm) {
    if (!state.meta) return;
    state.meta.llm = llm;
    el.settingsModel.innerHTML = "";
    (llm.models || []).forEach(m => {
      const opt = document.createElement("option");
      opt.value = m.key;
      opt.textContent = `${m.label}  [${m.provider}]`;
      opt.dataset.provider = m.provider;
      opt.dataset.defaultMaxTokens = m.default_max_tokens;
      opt.dataset.defaultTemperature = m.default_temperature;
      opt.dataset.maxOutputTokens = m.max_output_tokens;
      opt.dataset.supportsThinking = m.supports_thinking ? "1" : "0";
      el.settingsModel.appendChild(opt);
    });
    const cur = llm.current || {};
    el.settingsModel.value = cur.model_key || "";
    el.settingsMaxTokens.value = cur.max_tokens ?? 8192;
    el.settingsTemp.value = cur.temperature ?? 1.0;
    el.settingsTempVal.textContent = Number(el.settingsTemp.value).toFixed(2);
    if (el.settingsThinking) el.settingsThinking.checked = !!cur.thinking;
    updateModelHint();
    renderKeyStatus(llm.api_keys || {});
    el.settingsKeyAnthropic.value = "";
    el.settingsKeyQwen.value = "";
    if (el.settingsKeyDeepseek) el.settingsKeyDeepseek.value = "";
  }

  function renderKeyStatus(keys) {
    const render = (target, info) => {
      if (!target) return;
      if (!info || !info.present) {
        target.textContent = "未配置";
        target.className = "settings-keystatus missing";
        return;
      }
      const src = info.source === "env" ? "env" : "file";
      target.textContent = `已配置 · ${info.masked} · ${src}`;
      target.className = "settings-keystatus set";
    };
    render(el.settingsKeyAnthropicStatus, keys.anthropic);
    render(el.settingsKeyQwenStatus, keys.qwen);
    render(el.settingsKeyDeepseekStatus, keys.deepseek);
  }

  function updateModelHint() {
    const opt = el.settingsModel.options[el.settingsModel.selectedIndex];
    if (!opt) { el.settingsModelHint.textContent = ""; return; }
    const provider = opt.dataset.provider;
    const maxOut = opt.dataset.maxOutputTokens;
    const supportsThinking = opt.dataset.supportsThinking === "1";
    let hint = `provider: ${provider} · max_output: ${maxOut}`;
    if (provider === "qwen") hint += " · 需要环境变量 DASHSCOPE_API_KEY";
    else if (provider === "deepseek") hint += " · 需要环境变量 DEEPSEEK_API_KEY";
    else hint += " · 需要环境变量 ANTHROPIC_API_KEY";
    if (supportsThinking) hint += " · 支持思考模式";
    el.settingsModelHint.textContent = hint;
    el.settingsMaxTokens.max = maxOut;
    // Keep the row visible at all times — disabling (rather than hiding)
    // the checkbox makes the capability difference discoverable across
    // model swaps without the row jumping in/out.
    if (el.settingsThinking) {
      el.settingsThinking.disabled = !supportsThinking;
      if (!supportsThinking) el.settingsThinking.checked = false;
    }
    if (el.settingsThinkingField) {
      el.settingsThinkingField.classList.toggle("disabled", !supportsThinking);
    }
    if (el.settingsThinkingStatus) {
      el.settingsThinkingStatus.textContent = supportsThinking ? "可用" : "本模型不支持";
      el.settingsThinkingStatus.className = supportsThinking
        ? "settings-keystatus set"
        : "settings-keystatus missing";
    }
    if (el.settingsThinkingHint) {
      el.settingsThinkingHint.style.opacity = supportsThinking ? "" : "0.55";
    }
  }

  function openSettings() {
    if (el.settingsStatus) el.settingsStatus.textContent = "";
    showView("model");
  }

  function closeSettings() {
    showView("workspace");
  }

  async function saveSettings() {
    const payload = {
      model_key: el.settingsModel.value,
      max_tokens: parseInt(el.settingsMaxTokens.value, 10),
      temperature: parseFloat(el.settingsTemp.value),
      thinking: !!(el.settingsThinking && el.settingsThinking.checked),
    };
    const aKey = el.settingsKeyAnthropic.value.trim();
    if (aKey) payload.anthropic_api_key = aKey;
    const qKey = el.settingsKeyQwen.value.trim();
    if (qKey) payload.qwen_api_key = qKey;
    const dsKey = el.settingsKeyDeepseek && el.settingsKeyDeepseek.value.trim();
    if (dsKey) payload.deepseek_api_key = dsKey;

    el.settingsStatus.textContent = "保存中…";
    el.settingsStatus.className = "settings-status pending";
    try {
      const r = await fetch("/api/config", {
        method: "PUT",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({detail: r.statusText}));
        throw new Error(err.detail || "save failed");
      }
      const data = await r.json();
      state.meta.llm = data;
      renderTopbarMeta();
      renderKeyStatus(data.api_keys || {});
      el.settingsKeyAnthropic.value = "";
      el.settingsKeyQwen.value = "";
      if (el.settingsKeyDeepseek) el.settingsKeyDeepseek.value = "";
      el.settingsStatus.textContent = "已保存 · 下一轮对话立即生效";
      el.settingsStatus.className = "settings-status success";
      setTimeout(closeSettings, 900);
    } catch (e) {
      el.settingsStatus.textContent = "保存失败: " + (e.message || e);
      el.settingsStatus.className = "settings-status error";
    }
  }

  async function clearApiKey(provider) {
    if (!confirm(`确定清除 ${provider} 的 API key?(仅清除配置文件中的值;环境变量不受影响)`)) return;
    const fieldByProvider = {
      anthropic: "anthropic_api_key",
      qwen:      "qwen_api_key",
      deepseek:  "deepseek_api_key",
    };
    const field = fieldByProvider[provider];
    if (!field) return;
    const payload = { [field]: "" };
    try {
      const r = await fetch("/api/config", {
        method: "PUT",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload),
      });
      if (!r.ok) throw new Error((await r.json()).detail || "clear failed");
      const data = await r.json();
      state.meta.llm = data;
      renderKeyStatus(data.api_keys || {});
      el.settingsStatus.textContent = `${provider} key 已清除`;
      el.settingsStatus.className = "settings-status success";
    } catch (e) {
      el.settingsStatus.textContent = "清除失败: " + (e.message || e);
      el.settingsStatus.className = "settings-status error";
    }
  }

  function resetSettingsToDefaults() {
    const opt = el.settingsModel.options[el.settingsModel.selectedIndex];
    if (!opt) return;
    el.settingsMaxTokens.value = opt.dataset.defaultMaxTokens;
    el.settingsTemp.value = opt.dataset.defaultTemperature;
    el.settingsTempVal.textContent = Number(el.settingsTemp.value).toFixed(2);
  }

  if (el.btnSettings) el.btnSettings.addEventListener("click", openSettings);
  if (el.settingsClose) el.settingsClose.addEventListener("click", closeSettings);
  if (el.settingsOverlay) el.settingsOverlay.addEventListener("click", (e) => {
    if (e.target === el.settingsOverlay) closeSettings();
  });
  if (el.settingsModel) el.settingsModel.addEventListener("change", updateModelHint);
  if (el.settingsTemp) el.settingsTemp.addEventListener("input", () => {
    el.settingsTempVal.textContent = Number(el.settingsTemp.value).toFixed(2);
  });
  if (el.settingsSave) el.settingsSave.addEventListener("click", saveSettings);
  if (el.settingsResetDefaults) el.settingsResetDefaults.addEventListener("click", resetSettingsToDefaults);
  if (el.settingsKeyAnthropicClear) el.settingsKeyAnthropicClear.addEventListener("click", () => clearApiKey("anthropic"));
  if (el.settingsKeyQwenClear) el.settingsKeyQwenClear.addEventListener("click", () => clearApiKey("qwen"));
  if (el.settingsKeyDeepseekClear) el.settingsKeyDeepseekClear.addEventListener("click", () => clearApiKey("deepseek"));
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && el.settingsOverlay && !el.settingsOverlay.hidden) {
      closeSettings();
    }
  });

  // ------------------------------------------------------------------
  // Report-generation wizard
  //
  // A 7-step config wizard. On final confirm it composes a report-
  // generation request and runs it IN the 报表分析 page (report mode)
  // on the report-generator agent — which searches data and assembles
  // an actual structured report. The agent's取数 steps appear in the
  // conversation, the report renders into the dashboard, and the
  // per-turn 导出 buttons (HTML / Word) handle export.
  // ------------------------------------------------------------------
  const RG_TOTAL_STEPS = 7;
  let rgStep = 1;

  function rgGoto(step) {
    rgStep = Math.max(1, Math.min(RG_TOTAL_STEPS, step));
    el.reportgenOverlay.querySelectorAll(".rg-panel").forEach((p) => {
      p.classList.toggle("active", Number(p.dataset.panel) === rgStep);
    });
    el.reportgenOverlay.querySelectorAll(".rg-step").forEach((s) => {
      const n = Number(s.dataset.step);
      s.classList.toggle("active", n === rgStep);
      s.classList.toggle("done", n < rgStep);
    });
    el.rgPrev.hidden = rgStep === 1;
    el.rgNext.hidden = rgStep === RG_TOTAL_STEPS;
    el.rgConfirm.hidden = rgStep !== RG_TOTAL_STEPS;
    if (rgStep === RG_TOTAL_STEPS) rgRenderReview();
  }

  // Read every .rg-field across the 6 input panels into a flat list of
  // {key, label, value} — select → string, radio → checked label,
  // checkbox group → array of checked labels.
  function rgCollectPlan() {
    const fields = [];
    el.reportgenOverlay
      .querySelectorAll('.rg-panel[data-panel] .rg-field')
      .forEach((f) => {
        if (f.hidden) return;   // skip the toggled-off field (e.g. 规则明细 ↔ 自定义规则)
        const key = f.dataset.key;
        const label = f.dataset.label || key;
        const sel = f.querySelector("select");
        const ta = f.querySelector("textarea");
        const radios = f.querySelectorAll('input[type="radio"]');
        const checks = f.querySelectorAll('input[type="checkbox"]');
        let value;
        if (sel) {
          value = sel.value;
        } else if (ta) {
          value = ta.value.trim();
        } else if (radios.length) {
          const r = Array.from(radios).find((x) => x.checked);
          value = r ? r.closest("label").textContent.trim() : "";
        } else if (checks.length) {
          value = Array.from(checks)
            .filter((x) => x.checked)
            .map((x) => x.closest("label").textContent.trim());
        }
        fields.push({ key, label, value });
      });
    return fields;
  }

  // Compose the natural-language report-generation request the agent
  // receives. Each wizard field becomes a labelled line; the closing
  // block tells the agent how to find data and render the report.
  function rgBuildPrompt(fields) {
    const cfg = fields
      .map((f) => {
        const v = Array.isArray(f.value) ? f.value.join("、") : f.value;
        return v ? "· " + f.label + ":" + v : "";
      })
      .filter(Boolean)
      .join("\n");
    return (
      "【标准报表生成任务】\n" +
      "请按以下配置生成一份标准管理报表。你拥有业务本体与数据库的访问权限," +
      "请逐步取数,并把报表内容以表格和图表输出到看板。\n\n" +
      "[报表配置]\n" + cfg + "\n\n" +
      "[执行要求]\n" +
      "① 先用本体(MetricLookup / TermDisambiguate)核对指标口径,再用 SQL 逐项取数," +
      "并展示关键取数步骤;\n" +
      "② 按「报表模板」用 TableGenerate 输出报表主体表格(含对比基期);\n" +
      "③ 按「配图」清单用 ChartGenerate 逐张输出对应图表;\n" +
      "④ 最后给出一段管理层评述,点出关键结论与异常。"
    );
  }

  function rgRenderReview() {
    const fields = rgCollectPlan();
    el.rgReview.innerHTML = fields
      .map((f) => {
        const v = Array.isArray(f.value)
          ? f.value.join("、") || "—"
          : f.value || "—";
        return (
          '<div class="rg-review-row">' +
          '<span class="rg-review-key">' + esc(f.label) + "</span>" +
          '<span class="rg-review-val">' + esc(v) + "</span></div>"
        );
      })
      .join("");
  }

  // ③ 经营规则:选「自定义规则方案」时,把「规则明细」选择框换成自定义
  // 规则文本框;选预设方案时换回。两个 .rg-field 互斥显示。
  function rgToggleCustomRule() {
    const ov = el.reportgenOverlay;
    if (!ov) return;
    const sel = ov.querySelector('.rg-field[data-key="rulePlan"] select');
    const itemsField = ov.querySelector('.rg-field[data-key="ruleItems"]');
    const customField = ov.querySelector('.rg-field[data-key="customRule"]');
    if (!sel || !itemsField || !customField) return;
    const isCustom = sel.value.indexOf("自定义") !== -1;
    itemsField.hidden = isCustom;
    customField.hidden = !isCustom;
  }

  function openReportgen() {
    el.rgStepper.hidden = false;
    el.rgConfirm.hidden = true;
    el.rgSavePlan.hidden = false;
    el.rgNext.hidden = false;
    rgToggleCustomRule();
    rgGoto(1);
    el.reportgenOverlay.hidden = false;
    setTimeout(() => el.reportgenOverlay.classList.add("visible"), 10);
  }

  function closeReportgen() {
    el.reportgenOverlay.classList.remove("visible");
    setTimeout(() => {
      el.reportgenOverlay.hidden = true;
    }, 150);
  }

  // Final confirm — run report generation IN the 报表分析 page.
  // POST /api/report/generate spins up a report-generator session
  // (ontology + DB tools, no uploaded report needed); the agent then
  // searches data and assembles an actual report into the dashboard,
  // where the per-turn 导出 buttons (HTML / Word) appear.
  async function rgRunGeneration() {
    if (state.busy) {
      alert("当前有对话进行中,请等待结束后再生成报表。");
      return;
    }
    const prompt = rgBuildPrompt(rgCollectPlan());
    closeReportgen();
    try {
      const r = await fetch("/api/report/generate", { method: "POST" });
      if (!r.ok) {
        const err = await r.json().catch(() => ({ detail: r.statusText }));
        throw new Error(err.detail || "create session failed");
      }
    } catch (e) {
      alert("报表生成会话创建失败:" + (e.message || e));
      return;
    }
    // Mark the report-mode session active (no uploaded report) so the
    // chat send-gate passes; then dispatch the generation task.
    state.report.activeReports = [];
    state.report.activeReport = null;
    state.report.withDb = true;
    state.report.sessionActivated = true;
    updateChatInputAvailability();
    updateSendPlaceholder();
    sendMessage(prompt);
  }

  if (el.btnReportgen)
    el.btnReportgen.addEventListener("click", openReportgen);
  if (el.reportgenClose)
    el.reportgenClose.addEventListener("click", closeReportgen);
  if (el.reportgenOverlay)
    el.reportgenOverlay.addEventListener("click", (e) => {
      if (e.target === el.reportgenOverlay) closeReportgen();
    });
  if (el.rgStepper)
    el.rgStepper.addEventListener("click", (e) => {
      const s = e.target.closest(".rg-step");
      if (s) rgGoto(Number(s.dataset.step));
    });
  if (el.rgPrev) el.rgPrev.addEventListener("click", () => rgGoto(rgStep - 1));
  if (el.rgNext) el.rgNext.addEventListener("click", () => rgGoto(rgStep + 1));
  if (el.rgConfirm) el.rgConfirm.addEventListener("click", rgRunGeneration);
  const rgRulePlanSel = el.reportgenOverlay &&
    el.reportgenOverlay.querySelector('.rg-field[data-key="rulePlan"] select');
  if (rgRulePlanSel)
    rgRulePlanSel.addEventListener("change", rgToggleCustomRule);
  if (el.rgSavePlan)
    el.rgSavePlan.addEventListener("click", () => {
      el.rgSavePlan.textContent = "✓ 方案已保存";
      setTimeout(() => {
        el.rgSavePlan.textContent = "⭐ 存为方案";
      }, 1600);
    });
  document.addEventListener("keydown", (e) => {
    if (
      e.key === "Escape" &&
      el.reportgenOverlay &&
      !el.reportgenOverlay.hidden
    ) {
      closeReportgen();
    }
  });

  // ------------------------------------------------------------------
  // Data-source settings — switch the active ontology / database the
  // Agent runs against. GET /api/sources lists available files;
  // PUT /api/sources re-binds the BI tools and resets sessions.
  // ------------------------------------------------------------------
  // Sentinel value for the Doris read-only API pseudo-source (mirrors the
  // backend DORIS_SOURCE_VALUE). Selecting it routes SQLRun/ListTables/
  // DescribeTable through POST {base}/agent/doris/query.
  const DORIS_SOURCE_VALUE = "__doris_api__";
  const PRODUCTION_ONTOLOGY_VALUE = "__metaerp_ontology__";

  function sourceOptionLabel(name, active, remoteRepositories) {
    if (name === PRODUCTION_ONTOLOGY_VALUE) return "MetaERP";
    const repo = (remoteRepositories || []).find((item) => String(item.value) === String(name));
    if (repo) return repo.name + (name === active ? "  · 当前生效" : "");
    const base = name === DORIS_SOURCE_VALUE ? "API · Doris 实时查询" : name;
    return base + (name === active ? "  · 当前生效" : "");
  }

  function fillSourceSelect(sel, info) {
    const opts = (info && info.options) || [];
    const active = info && info.active;
    sel.innerHTML = "";
    opts.forEach((name) => {
      const o = document.createElement("option");
      o.value = name;
      o.textContent = sourceOptionLabel(name, active, info && info.remote_repositories);
      sel.appendChild(o);
    });
    if (active && opts.indexOf(active) !== -1) sel.value = active;
  }

  // Show the Doris API base-URL field only when the API source is selected.
  function syncDorisField() {
    if (!el.sourcesDorisField) return;
    const on = el.sourcesDatabase && el.sourcesDatabase.value === DORIS_SOURCE_VALUE;
    el.sourcesDorisField.hidden = !on;
  }

  // Show the 图库源 selector + 建立图库 button only in graph-retrieval mode.
  // Semantic mode uses the Excel ontology alone; graph mode additionally needs
  // a graph library (which can be built from the selected Excel).
  function syncRetrievalMode() {
    const graph = el.sourcesRetrievalMode && el.sourcesRetrievalMode.value === "graph";
    if (el.sourcesGraphField) el.sourcesGraphField.hidden = !graph;
    const usingProduction = el.sourcesOntology && el.sourcesOntology.value === PRODUCTION_ONTOLOGY_VALUE;
    if (el.sourcesBuildGraphRow) el.sourcesBuildGraphRow.hidden = !graph || usingProduction;
    if (el.sourcesGraphField && usingProduction) {
      const hint = el.sourcesGraphField.querySelector(".settings-hint");
      if (hint) hint.textContent = "生产本体关系由团队本体服务实时提供，不需要本地图文件。";
    }
  }

  // Build a NetworkX graph library (.graphml) from the currently-selected
  // 本体源 Excel, then refresh the 图库源 dropdown and select the result.
  async function buildGraphFromExcel() {
    const setHint = (msg, cls) => {
      if (!el.sourcesBuildGraphHint) return;
      el.sourcesBuildGraphHint.textContent = msg;
      el.sourcesBuildGraphHint.className = "settings-hint" + (cls ? " " + cls : "");
    };
    const xlsx = el.sourcesOntology && el.sourcesOntology.value;
    if (xlsx === PRODUCTION_ONTOLOGY_VALUE) {
      setHint("生产本体库不需要生成本地 GraphML 图文件。", "error");
      return;
    }
    if (!xlsx) { setHint("请先在「本体源」选择一个 Excel。", "error"); return; }
    if (el.sourcesBuildGraph) el.sourcesBuildGraph.disabled = true;
    setHint("构建中…（抽取 ER + 元模型关系）", "pending");
    try {
      const r = await fetch("/api/graph/build", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ontology: xlsx }),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data.detail || "build failed");
      const s = data.stats || {};
      setHint(
        `✓ 已生成 ${data.graph} · 节点 ${s.nodes} / 边 ${s.edges}` +
        `(层级 ${s.tree_edges} + ER ${s.er_edges} + 规则 ${s.rule_edges})`, "success");
      // Refresh the 图库源 list and select the freshly-built graph.
      const sr = await fetch("/api/sources");
      const sd = await sr.json().catch(() => ({}));
      if (sd.retrieval && el.sourcesGraph) {
        fillSourceSelect(el.sourcesGraph, sd.retrieval.graph || {});
        el.sourcesGraph.value = data.graph;
      }
    } catch (e) {
      setHint("构建失败: " + (e.message || e), "error");
    } finally {
      if (el.sourcesBuildGraph) el.sourcesBuildGraph.disabled = false;
    }
  }

  // Shared loader for both 数据源 and 本体适配 pages — they read/write the same
  // /api/sources payload, just split across two screens. `statusEl` is the
  // status line of whichever page is being opened.
  async function loadSourcesInto(statusEl) {
    if (statusEl) { statusEl.textContent = ""; statusEl.className = "settings-status"; }
    try {
      const r = await fetch("/api/sources");
      if (!r.ok) throw new Error("HTTP " + r.status);
      const data = await r.json();
      fillSourceSelect(el.sourcesOntology, data.ontology);
      fillSourceSelect(el.sourcesDatabase, data.database);
      if (data.retrieval) {
        if (el.sourcesRetrievalMode) el.sourcesRetrievalMode.value = data.retrieval.mode || "semantic";
        if (el.sourcesGraph) fillSourceSelect(el.sourcesGraph, data.retrieval.graph || {});
      }
      if (data.doris) {
        if (el.sourcesDorisJdbc) el.sourcesDorisJdbc.value = data.doris.api_url || "";
        if (el.sourcesDorisDatabase) el.sourcesDorisDatabase.value = data.doris.database || "";
        if (el.sourcesDorisDriver) el.sourcesDorisDriver.value = data.doris.driver || "";
        if (el.sourcesDorisUser) el.sourcesDorisUser.value = data.doris.username || "";
        if (el.sourcesDorisPass) el.sourcesDorisPass.value = data.doris.password || "";
      }
      syncDorisField();
      syncRetrievalMode();
    } catch (e) {
      if (statusEl) {
        statusEl.textContent = "加载数据源列表失败: " + (e.message || e);
        statusEl.className = "settings-status error";
      }
    }
  }

  async function openSources() {
    await loadSourcesInto(el.sourcesStatus);
    showView("sources");
  }

  function closeSources() {
    showView("workspace");
  }

  async function openOntologyAdapt() {
    await loadSourcesInto(el.ontoAdaptStatus);
    showView("ontology-adapt");
  }

  // Both 数据源 and 本体适配 save the full /api/sources payload (the backend
  // re-binds atomically); `statusEl` directs feedback to the active page.
  async function saveSources(statusEl) {
    statusEl = statusEl || el.sourcesStatus;
    if (state.busy) {
      statusEl.textContent = "对话进行中,请等当前回合结束后再切换数据源。";
      statusEl.className = "settings-status error";
      return;
    }
    const dbValue = el.sourcesDatabase.value || null;
    const retrievalMode = (el.sourcesRetrievalMode && el.sourcesRetrievalMode.value) || "semantic";
    const payload = {
      ontology: el.sourcesOntology.value || null,
      database: dbValue,
      retrieval_mode: retrievalMode,
      // Graph library is only meaningful in graph-retrieval mode.
      graph: retrievalMode === "graph"
        ? ((el.sourcesGraph && el.sourcesGraph.value) || null)
        : null,
    };
    if (dbValue === DORIS_SOURCE_VALUE) {
      const apiUrl = (el.sourcesDorisJdbc && el.sourcesDorisJdbc.value || "").trim();
      if (!apiUrl || !/^https?:\/\//i.test(apiUrl)) {
        statusEl.textContent = "请填写 Doris HTTP API 地址(例如 http://host:30834/agent/doris/query)。";
        statusEl.className = "settings-status error";
        return;
      }
      payload.doris_api_url = apiUrl;
      payload.doris_database = (el.sourcesDorisDatabase && el.sourcesDorisDatabase.value || "").trim();
      payload.doris_driver = (el.sourcesDorisDriver && el.sourcesDorisDriver.value || "").trim();
      payload.doris_username = (el.sourcesDorisUser && el.sourcesDorisUser.value || "").trim();
      // Password may legitimately be empty (current Doris has no password).
      payload.doris_password = (el.sourcesDorisPass && el.sourcesDorisPass.value) || "";
    }
    statusEl.textContent = "切换中…";
    statusEl.className = "settings-status pending";
    try {
      const r = await fetch("/api/sources", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({ detail: r.statusText }));
        throw new Error(err.detail || "switch failed");
      }
      statusEl.textContent = "✓ 数据源已切换 · 正在重新加载…";
      statusEl.className = "settings-status success";
      setTimeout(() => location.reload(), 700);
    } catch (e) {
      statusEl.textContent = "切换失败: " + (e.message || e);
      statusEl.className = "settings-status error";
    }
  }

  async function readCurrentOntologyDatabase() {
    const button = el.sourcesReadOntologyDb;
    if (button) { button.disabled = true; button.textContent = "读取中…"; }
    try {
      const r = await fetch("/api/sources");
      const data = await r.json();
      const ontology = data.ontology || {};
      const active = ontology.active;
      const repo = (ontology.remote_repositories || []).find((item) => String(item.value) === String(active));
      if (!repo || !repo.dorisDatabase) {
        throw new Error("当前本体源没有可用的 dorisDatabase（本地 Excel 不提供该字段）");
      }
      el.sourcesDorisDatabase.value = repo.dorisDatabase;
      if (el.sourcesStatus) {
        el.sourcesStatus.textContent = `✓ 已读取 ${repo.name}：${repo.dorisDatabase}`;
        el.sourcesStatus.className = "settings-status success";
      }
    } catch (e) {
      if (el.sourcesStatus) {
        el.sourcesStatus.textContent = "读取失败: " + (e.message || e);
        el.sourcesStatus.className = "settings-status error";
      }
    } finally {
      if (button) { button.disabled = false; button.textContent = "读取当前数据源"; }
    }
  }

  if (el.btnSources) el.btnSources.addEventListener("click", openSources);
  if (el.sourcesDatabase) el.sourcesDatabase.addEventListener("change", syncDorisField);
  if (el.sourcesReadOntologyDb) el.sourcesReadOntologyDb.addEventListener("click", readCurrentOntologyDatabase);
  if (el.sourcesOntology) el.sourcesOntology.addEventListener("change", () => {
    syncRetrievalMode();
    if (el.ontoAdaptStatus) {
      el.ontoAdaptStatus.textContent = "本体源选择尚未保存，请点击“保存并切换”。";
      el.ontoAdaptStatus.className = "settings-status pending";
    }
  });
  if (el.sourcesRetrievalMode) el.sourcesRetrievalMode.addEventListener("change", syncRetrievalMode);
  if (el.sourcesBuildGraph) el.sourcesBuildGraph.addEventListener("click", buildGraphFromExcel);
  if (el.sourcesClose) el.sourcesClose.addEventListener("click", closeSources);
  if (el.sourcesCancel)
    el.sourcesCancel.addEventListener("click", closeSources);
  if (el.sourcesSave) el.sourcesSave.addEventListener("click", () => saveSources(el.sourcesStatus));
  // 本体适配 page reuses the same loader + save (full /api/sources payload).
  if (el.ontoAdaptCancel) el.ontoAdaptCancel.addEventListener("click", closeSources);
  if (el.ontoAdaptSave) el.ontoAdaptSave.addEventListener("click", () => saveSources(el.ontoAdaptStatus));
  if (el.sourcesOverlay)
    el.sourcesOverlay.addEventListener("click", (e) => {
      if (e.target === el.sourcesOverlay) closeSources();
    });
  document.addEventListener("keydown", (e) => {
    if (
      e.key === "Escape" &&
      el.sourcesOverlay &&
      !el.sourcesOverlay.hidden
    ) {
      closeSources();
    }
  });

  // ------------------------------------------------------------------
  // System prompt (per-mode)
  // ------------------------------------------------------------------
  async function loadSystemPrompt() {
    el.systemContent.innerHTML = '<div class="sys-section"><div class="sys-title">加载中…</div></div>';
    try {
      const r = await fetch(`/api/system-prompt?mode=${state.mode}`);
      const data = await r.json();
      B().systemPrompt = data.system_prompt;
      renderSystem();
    } catch (e) {
      el.systemContent.innerHTML = `<div class="sys-section"><div class="sys-title">错误</div><div class="sys-body">${esc(e.message || String(e))}</div></div>`;
    }
  }

  function renderSystem() {
    if (!state.meta) return;
    const a = currentAgentMeta();
    if (!a) return;
    const toolsList = state.mode === "report"
      ? (state.report.withDb
          ? ["OntologyQuery", "TermDisambiguate", "MetricLookup", "RelationLookup",
             "EntityDescribe", "ListBusinessObjects", "SQLRun", "ListTables",
             "DescribeTable", "ChartGenerate", "TableGenerate", "AskUser"]
          : ["ChartGenerate", "TableGenerate", "AskUser"])
      : (a.tools || []);
    const tools = toolsList.map(t => `<span class="tool-pill">${esc(t)}</span>`).join("") || '<span class="kv-v">(全部)</span>';
    const modeLabel = state.mode === "report" ? "报表分析" : "智能分析";
    el.systemContent.innerHTML = `
      <div class="sys-section">
        <div class="sys-title">Agent 定义(${esc(modeLabel)}模式)</div>
        <div class="sys-body">名称: ${esc(a.name)}
模型: ${esc(a.model || "默认")}
描述: ${esc(a.description || "")}
欢迎语: ${esc(a.welcome_message || "")}</div>
      </div>
      <div class="sys-section">
        <div class="sys-title">工具白名单</div>
        <div style="padding: 4px 0;">${tools}</div>
      </div>
      <div class="sys-section">
        <div class="sys-title">完整系统提示词</div>
        <div class="sys-body">${esc(B().systemPrompt || "")}</div>
      </div>`;
  }

  // ------------------------------------------------------------------
  // Chat rendering
  // ------------------------------------------------------------------
  function hideEmpty() {
    if (el.chatEmpty) el.chatEmpty.style.display = "none";
    B().hasContent = true;
  }

  function showEmptyIfIdle() {
    if (!B().hasContent && el.chatEmpty) el.chatEmpty.style.display = "";
  }

  function updateTurnCounter() {
    const n = B().turnCount;
    el.turnCounter.textContent = n + " 回合";
  }

  function addUserMessage(text) {
    hideEmpty();
    B().turnCount += 1;
    updateTurnCounter();
    const msg = el_h("div", "msg msg-user");
    msg.dataset.turn = String(B().turnCount);
    msg.innerHTML = `
      <div class="msg-header">
        <span class="msg-role user">用户</span>
      </div>
      <div class="msg-body">${esc(text)}</div>`;
    el.chatScroll.appendChild(msg);
    B().questions.push({ turn: B().turnCount, text: String(text || "") });
    renderTodoPanel();
    scrollChatBottomForce();  // user just sent — always reveal their input
  }

  function indexQuestionsFromChat() {
    const bucket = B();
    const messages = Array.from(el.chatScroll.querySelectorAll(".msg-user"));
    bucket.questions = messages.map((msg, i) => {
      const turn = i + 1;
      msg.dataset.turn = String(turn);
      const body = msg.querySelector(".msg-body");
      return { turn, text: body ? body.textContent.trim() : "" };
    }).filter((q) => q.text);
    bucket.turnCount = bucket.questions.length;
  }

  function scrollToQuestion(turn) {
    const turnText = String(turn);
    const chatSelector = `.msg-user[data-turn="${CSS.escape(turnText)}"]`;
    const dashboardSelector = `.dash-question[data-question-turn="${CSS.escape(turnText)}"]`;
    const msg = el.chatScroll && el.chatScroll.querySelector(chatSelector);
    const dashboardCard = el.dashboardList && el.dashboardList.querySelector(dashboardSelector);
    if (!msg && !dashboardCard) return;
    showView("workspace");
    // Task-list and dashboard links are cross-pane navigation: keep the chat
    // and resident dashboard at the same user-turn anchor.
    if (dashboardCard && document.body.dataset.dashboard === "collapsed") {
      applyDashboardState(false);
    }
    if (msg) {
      msg.scrollIntoView({ behavior: "smooth", block: "start" });
      msg.classList.add("question-focus");
      setTimeout(() => msg.classList.remove("question-focus"), 900);
    }
    if (dashboardCard) {
      dashboardCard.scrollIntoView({ behavior: "smooth", block: "start" });
      dashboardCard.classList.add("question-focus");
      setTimeout(() => dashboardCard.classList.remove("question-focus"), 900);
    }
  }

  function assistantRoleLabel() {
    const agent = currentAgentMeta();
    return (agent && agent.name ? agent.name : "助手").toUpperCase();
  }

  function startAssistantMessage(iteration) {
    const msg = el_h("div", "msg msg-assistant");
    msg.innerHTML = `
      <div class="msg-header">
        <span class="msg-role assistant">${esc(assistantRoleLabel())}</span>
        <span class="msg-iter">迭代 ${iteration}</span>
      </div>
      <div class="msg-body"><span class="thinking-line"><span class="thinking-dot"></span><span class="thinking-dot"></span><span class="thinking-dot"></span>思考中…</span></div>`;
    el.chatScroll.appendChild(msg);
    B().currentAssistantEl = msg.querySelector(".msg-body");
    B().currentAssistantText = "";
    hideEmpty();
    scrollChatBottom();
  }

  function appendAssistantDelta(text) {
    const bucket = B();
    if (!bucket.currentAssistantEl) return;
    if (bucket.currentAssistantText === "") {
      bucket.currentAssistantEl.innerHTML = "";
    }
    bucket.currentAssistantText += text;
    const display = bucket.currentAssistantText.replace(/\s+$/, "");
    bucket.currentAssistantEl.innerHTML = highlightEntities(display) +
      '<span class="cursor"></span>';
    scrollChatBottom();
  }

  function finalizeAssistantText() {
    const bucket = B();
    if (!bucket.currentAssistantEl) return;
    const trimmed = (bucket.currentAssistantText || "").replace(/\s+$/, "");
    if (trimmed) {
      bucket.currentAssistantEl.innerHTML = highlightEntities(trimmed);
    } else {
      bucket.currentAssistantEl.innerHTML = "";
    }
  }

  function attachChatStep(stepEl) {
    const bucket = B();
    const container = bucket.currentAssistantEl
      ? bucket.currentAssistantEl.parentElement
      : el.chatScroll;
    container.appendChild(stepEl);
    scrollChatBottom();
  }

  // ------------------------------------------------------------------
  // User-choice card (AskUser pause point)
  // ------------------------------------------------------------------
  function attachChoiceCard(evt) {
    const bucket = B();
    const container = bucket.currentAssistantEl
      ? bucket.currentAssistantEl.parentElement
      : el.chatScroll;
    // Defensive: if the backend re-emits user_choice_requested for the same
    // tool_use_id (retry/reconnect), remove the stale card so we don't end up
    // with two — the old (disabled) one would intercept clicks ahead of the
    // new one.
    if (evt.tool_use_id) {
      const stale = el.chatScroll.querySelectorAll(`.choice-card[data-tool-use-id="${CSS.escape(evt.tool_use_id)}"]`);
      stale.forEach(n => n.remove());
    }
    const card = el_h("div", "choice-card");
    card.dataset.toolUseId = evt.tool_use_id;
    const presetOptions = evt.options || [];
    const optionsHtml = presetOptions.map((opt, idx) => {
      const inputId = `choice-${evt.tool_use_id}-${idx}`;
      // NOTE: We deliberately use <div role="checkbox"> instead of <label
      // for=…>. The for-attribute label/input pairing has subtle browser
      // behaviour (re-toggling on click, focus stealing, native synthesized
      // click events) that has caused a "third option won't respond" symptom
      // when the option list is rendered inside the cockpit's iframe modal.
      // Toggling is now driven entirely by an explicit click delegate.
      return `
      <div class="choice-option" data-id="${esc(opt.id)}" data-label="${esc(opt.label)}" role="checkbox" aria-checked="false" tabindex="0">
        <input type="checkbox" class="choice-check" id="${esc(inputId)}"
               value="${esc(opt.id)}" data-label="${esc(opt.label)}" tabindex="-1" />
        <span class="choice-idx">${idx + 1}</span>
        <span class="choice-body">
          <span class="choice-label">${esc(opt.label)}</span>
          ${opt.detail ? `<span class="choice-detail">${esc(opt.detail)}</span>` : ""}
        </span>
      </div>`;
    }).join("");
    // Trailing row: a manual-input option. The hidden checkbox auto-toggles
    // as the user types; its data-label & value follow the input contents,
    // so the existing selection / submit pipeline doesn't need to special-case
    // it beyond ignoring text-input click events.
    const manualIdx = presetOptions.length;
    const manualInputId = `choice-${evt.tool_use_id}-manual`;
    const manualHtml = `
      <div class="choice-option choice-option-manual" data-manual="1">
        <input type="checkbox" class="choice-check choice-check-manual" id="${esc(manualInputId)}-check"
               value="" data-label="" tabindex="-1" />
        <span class="choice-idx">${manualIdx + 1}</span>
        <span class="choice-body">
          <input type="text" class="choice-manual-input" id="${esc(manualInputId)}"
                 placeholder="或手动输入答案 (按 Enter 提交)…" autocomplete="off" />
        </span>
      </div>`;
    card.innerHTML = `
      <div class="choice-head">
        <span class="choice-tag">需要您选择</span>
        <span class="choice-question">${esc(evt.question || "")}</span>
        <span class="choice-hint">支持多选 / 手动输入</span>
      </div>
      ${evt.context ? `<div class="choice-context">${esc(evt.context)}</div>` : ""}
      <div class="choice-options">${optionsHtml}${manualHtml}</div>
      <div class="choice-actions">
        <span class="choice-summary">未选择</span>
        <button type="button" class="choice-confirm" disabled>确定</button>
      </div>
      <div class="choice-status"></div>`;
    container.appendChild(card);
    scrollChatBottom();

    const checks = card.querySelectorAll(".choice-check");
    const confirmBtn = card.querySelector(".choice-confirm");
    const summary = card.querySelector(".choice-summary");
    const manualInput = card.querySelector(".choice-manual-input");
    const manualCheck = card.querySelector(".choice-check-manual");

    function refreshSelection() {
      const selected = Array.from(checks).filter(c => c.checked);
      checks.forEach(c => {
        const opt = c.closest(".choice-option");
        if (opt) {
          opt.classList.toggle("selected", c.checked);
          opt.setAttribute("aria-checked", String(c.checked));
        }
      });
      const lockedBySubmitting = card.classList.contains("submitting");
      const lockedByResolved = card.classList.contains("resolved");
      const newDisabled = selected.length === 0 || lockedBySubmitting || lockedByResolved;
      if (confirmBtn.disabled !== newDisabled) {
        console.debug("[choice] confirm.disabled", newDisabled, {
          selected: selected.length, lockedBySubmitting, lockedByResolved,
        });
      }
      confirmBtn.disabled = newDisabled;
      if (selected.length === 0) {
        summary.textContent = "未选择";
      } else if (selected.length === 1) {
        summary.textContent = `已选 1 项: ${selected[0].dataset.label}`;
      } else {
        summary.textContent = `已选 ${selected.length} 项: ` +
          selected.map(c => c.dataset.label).join("、");
      }
    }

    function toggleOption(opt) {
      if (!opt) return;
      // Manual rows aren't toggled by clicks anywhere except the text input;
      // the hidden check follows the input value.
      if (opt.dataset.manual === "1") return;
      const input = opt.querySelector(".choice-check");
      if (!input || input.disabled) return;
      if (card.classList.contains("submitting") || card.classList.contains("resolved")) return;
      input.checked = !input.checked;
      refreshSelection();
    }

    // Manual-input wiring: typing toggles the hidden checkbox + sets its
    // value/label so the rest of the pipeline treats it as a normal entry.
    if (manualInput && manualCheck) {
      manualInput.addEventListener("input", () => {
        const text = manualInput.value.trim();
        manualCheck.checked = !!text;
        manualCheck.value = text ? `manual:${text}` : "";
        manualCheck.dataset.label = text;
        const opt = manualCheck.closest(".choice-option");
        if (opt) opt.classList.toggle("has-input", !!text);
        refreshSelection();
      });
      manualInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          // Trigger the confirm path if at least one selection (preset or manual) exists.
          refreshSelection();
          if (!confirmBtn.disabled) confirmBtn.click();
        }
      });
    }

    // Single delegated click handler covers BOTH options and the confirm
    // button. No reliance on <label for=…> native pairing.
    card.addEventListener("click", (e) => {
      // 1) Confirm button path
      const btn = e.target.closest(".choice-confirm");
      if (btn && btn === confirmBtn) {
        e.preventDefault();
        e.stopPropagation();
        refreshSelection();
        if (confirmBtn.disabled) {
          console.warn("[choice] confirm clicked but still disabled — selection empty or card locked");
          return;
        }
        const selected = Array.from(checks).filter(c => c.checked);
        if (!selected.length) return;
        const ids = selected.map(c => c.value);
        const labels = selected.map(c => c.dataset.label);
        submitChoice(card, ids, labels);
        return;
      }
      // 2) Manual text input — let the browser handle focus/typing.
      if (e.target.classList.contains("choice-manual-input")) {
        return;
      }
      // 3) Option toggle path
      const opt = e.target.closest(".choice-option");
      if (!opt) return;
      // Click on the manual row's empty area: focus the text input instead.
      if (opt.dataset.manual === "1") {
        const inp = opt.querySelector(".choice-manual-input");
        if (inp) inp.focus();
        return;
      }
      // If the user clicked the <input> directly the browser has already
      // toggled .checked for us — don't flip it back.
      if (e.target.classList.contains("choice-check")) {
        refreshSelection();
        return;
      }
      e.preventDefault();
      e.stopPropagation();
      toggleOption(opt);
    });

    // Keyboard a11y: Space / Enter on a focused option toggles it.
    card.addEventListener("keydown", (e) => {
      if (e.key !== " " && e.key !== "Enter") return;
      const opt = e.target.closest(".choice-option");
      if (!opt) return;
      e.preventDefault();
      toggleOption(opt);
    });

    refreshSelection();
  }

  function markChoiceResolved(toolUseId, labels) {
    const card = el.chatScroll.querySelector(`.choice-card[data-tool-use-id="${CSS.escape(toolUseId)}"]`);
    if (!card) return;
    card.classList.add("resolved");
    const list = Array.isArray(labels) ? labels : [labels];
    const status = card.querySelector(".choice-status");
    if (status) status.textContent = `已选择: ${list.join("、")}`;
    card.querySelectorAll(".choice-check").forEach(c => { c.disabled = true; });
    const confirmBtn = card.querySelector(".choice-confirm");
    if (confirmBtn) confirmBtn.disabled = true;
  }

  async function submitChoice(card, ids, labels) {
    if (card.classList.contains("resolved") || card.classList.contains("submitting")) return;
    card.classList.add("submitting");
    card.querySelectorAll(".choice-check").forEach(c => { c.disabled = true; });
    const confirmBtn = card.querySelector(".choice-confirm");
    if (confirmBtn) { confirmBtn.disabled = true; confirmBtn.textContent = "提交中…"; }
    const status = card.querySelector(".choice-status");
    if (status) status.textContent = `正在提交: ${labels.join("、")}…`;
    setBusy(true);

    const url = state.mode === "report" ? "/api/report/choice" : "/api/choice";
    let resp;
    try {
      resp = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ choice_ids: ids, choice_labels: labels }),
      });
    } catch (err) {
      onEvent({ type: "error", message: `choice request failed: ${err.message || err}` });
      card.classList.remove("submitting");
      card.querySelectorAll(".choice-check").forEach(c => { c.disabled = false; });
      if (confirmBtn) { confirmBtn.disabled = false; confirmBtn.textContent = "确定"; }
      if (status) status.textContent = `提交失败,请重试`;
      setBusy(false);
      return;
    }
    if (!resp.ok || !resp.body) {
      const errText = await resp.text().catch(() => resp.statusText);
      onEvent({ type: "error", message: `HTTP ${resp.status}: ${errText}` });
      card.classList.remove("submitting");
      card.querySelectorAll(".choice-check").forEach(c => { c.disabled = false; });
      if (confirmBtn) { confirmBtn.disabled = false; confirmBtn.textContent = "确定"; }
      if (status) status.textContent = `提交失败 (HTTP ${resp.status}),请重试`;
      setBusy(false);
      return;
    }
    await streamResponse(resp);
  }

  function attachChatChart(chart) {
    const bucket = B();
    const container = bucket.currentAssistantEl
      ? bucket.currentAssistantEl.parentElement
      : el.chatScroll;
    const card = buildChartCard(chart);
    container.appendChild(card);
    scrollChatBottom();
    requestAnimationFrame(() => mountChart(card, chart));
  }

  function buildChartCard(chart) {
    const card = el_h("div", "chart-card");
    card.dataset.chartJson = encodeURIComponent(JSON.stringify(chart || {}));
    const savedLink = chart.saved_path
      ? `<span class="chart-saved">saved: <a href="/charts/${esc(chart.saved_path.split(/[\\/]/).pop())}" target="_blank" title="${esc(chart.saved_path)}">${esc(chart.saved_path.split(/[\\/]/).pop())}</a></span>`
      : "";
    const insightBtn = buildInsightButtonHTML(chart);
    card.innerHTML = `
      <div class="chart-head">
        <span class="chart-type">${esc(chart.chart_type || "chart")}</span>
        <span class="chart-title">${esc(chart.title || "")}</span>
        ${savedLink}
        ${insightBtn}
      </div>
      <div class="chart-canvas"></div>`;
    wireInsightButton(card, chart);
    return card;
  }

  // ------------------------------------------------------------------
  // Deep-Insight (深入洞察) — drill-down trigger on chart cards
  // ------------------------------------------------------------------
  function extractMetricCode(sourceNote) {
    if (!sourceNote) return null;
    const m = String(sourceNote).match(/M\d{3}/);
    return m ? m[0] : null;
  }

  function isInsightAvailable(chart) {
    // Need a metric code in the source_note to anchor the drill-down.
    if (!chart || !extractMetricCode(chart.source_note)) return false;
    // Pure report mode has no DB tools — drill-down can't run there.
    if (state.mode === "report" && state.report && state.report.withDb === false) {
      return false;
    }
    return true;
  }

  function buildInsightButtonHTML(chart) {
    if (!isInsightAvailable(chart)) return "";
    const src = esc(chart.source_note || "");
    const ttl = esc(chart.title || "");
    return `<button type="button" class="chart-insight-btn"
              data-source="${src}" data-title="${ttl}"
              title="基于本体维度对该图表进行深入洞察">深入洞察 ⤵</button>`;
  }

  function wireInsightButton(card, chart) {
    const btn = card.querySelector(".chart-insight-btn");
    if (!btn) return;
    btn.addEventListener("click", () => triggerDeepInsight(chart));
  }

  function markInsightTriggered(sourceNote) {
    if (!sourceNote) return;
    const sel = `.chart-insight-btn[data-source="${cssAttr(sourceNote)}"]`;
    document.querySelectorAll(sel).forEach((b) => {
      b.disabled = true;
      b.textContent = "已触发洞察";
      b.classList.add("triggered");
    });
  }

  function cssAttr(s) {
    // Escape for use inside an attribute selector value.
    return String(s).replace(/(["\\])/g, "\\$1");
  }

  function triggerDeepInsight(chart) {
    if (state.busy) return;
    const metric = extractMetricCode(chart.source_note);
    if (!metric) return;
    const title = chart.title || "(未命名)";
    const source = chart.source_note || "";
    const prompt = `[深入洞察] 图表标题:"${title}";指标:${metric};来源口径:${source}`;
    markInsightTriggered(source);
    sendMessage(prompt);
  }

  function mountChart(card, chart) {
    const canvas = card.querySelector(".chart-canvas");
    if (!canvas) return;
    if (!chart.option) return;
    if (typeof echarts === "undefined") {
      canvas.innerHTML = '<div style="padding:14px;color:var(--accent-red);font-family:var(--font-mono);font-size:12px;">ECharts 未加载</div>';
      return;
    }
    try {
      const inst = echarts.init(canvas);
      inst.setOption(chart.option, true);
      requestAnimationFrame(() => inst.resize());
      window.addEventListener("resize", () => inst.resize());
      wireInsightButton(card, chart);
    } catch (e) {
      canvas.innerHTML = `<div style="padding:14px;color:var(--accent-red);font-family:var(--font-mono);font-size:12px;">Chart render failed: ${esc(e.message || String(e))}</div>`;
    }
  }

  // ------------------------------------------------------------------
  // Table card (TableGenerate output)
  // ------------------------------------------------------------------
  function attachChatTable(table) {
    const bucket = B();
    const container = bucket.currentAssistantEl
      ? bucket.currentAssistantEl.parentElement
      : el.chatScroll;
    const card = buildTableCard(table);
    container.appendChild(card);
    scrollChatBottom();
  }

  function formatCellValue(value, col) {
    if (value === null || value === undefined) return '<span class="tbl-null">—</span>';
    const fmt = col && col.format;
    const unit = col && col.unit;
    if (fmt === "number" || fmt === "money") {
      const num = Number(value);
      if (!isFinite(num)) return esc(String(value));
      const abs = Math.abs(num);
      const digits = abs >= 100 ? 0 : abs >= 10 ? 1 : 2;
      const formatted = num.toLocaleString("zh-CN", { maximumFractionDigits: digits });
      return esc(formatted + (unit ? ` ${unit}` : ""));
    }
    if (fmt === "percent") {
      const num = Number(value);
      if (!isFinite(num)) return esc(String(value));
      return esc(num.toFixed(2) + "%");
    }
    return esc(String(value));
  }

  function defaultAlign(col) {
    if (!col) return "left";
    if (col.align) return col.align;
    if (col.format === "number" || col.format === "money" || col.format === "percent") return "right";
    return "left";
  }

  function buildTableCard(tbl) {
    const card = el_h("div", "table-card");
    const cols = Array.isArray(tbl.columns) ? tbl.columns : [];
    const rows = Array.isArray(tbl.rows) ? tbl.rows : [];
    const hi = new Set((tbl.highlight_rows || []).map(Number));

    const colgroup = cols.map((c) =>
      `<col${c.width ? ` style="width:${esc(String(c.width))}"` : ""}/>`
    ).join("");

    const head = cols.map((c) =>
      `<th data-align="${esc(defaultAlign(c))}">${esc(c.label || c.key || "")}</th>`
    ).join("");

    const body = rows.map((row, rIdx) => {
      const cells = cols.map((c, cIdx) => {
        const v = Array.isArray(row) ? row[cIdx] : row[c.key];
        return `<td data-align="${esc(defaultAlign(c))}">${formatCellValue(v, c)}</td>`;
      }).join("");
      return `<tr class="${hi.has(rIdx) ? "row-highlight" : ""}">${cells}</tr>`;
    }).join("");

    const subtitle = tbl.subtitle ? `<span class="table-subtitle">${esc(tbl.subtitle)}</span>` : "";
    const source = tbl.source_note ? `<span class="table-source">Source · ${esc(tbl.source_note)}</span>` : "";
    const summary = tbl.summary ? `<div class="table-summary">📌 ${esc(tbl.summary)}</div>` : "";
    const footnote = tbl.footnote ? `<div class="table-footnote">${esc(tbl.footnote)}</div>` : "";
    const metaLine = `<span class="table-shape">${rows.length} 行 × ${cols.length} 列</span>`;

    card.innerHTML = `
      <div class="table-head">
        <span class="table-tag">TABLE</span>
        <span class="table-title">${esc(tbl.title || "")}</span>
        ${subtitle}
        ${metaLine}
        ${source}
      </div>
      <div class="table-scroll">
        <table class="data-grid">
          <colgroup>${colgroup}</colgroup>
          <thead><tr>${head}</tr></thead>
          <tbody>${body}</tbody>
        </table>
      </div>
      ${summary}
      ${footnote}`;
    return card;
  }

  // ------------------------------------------------------------------
  // Dashboard pane (middle) — conclusion + chart + table cards
  // ------------------------------------------------------------------
  // Markers that indicate the start of the next section in the L1/L2 templates.
  // Used as a *secondary* boundary in case the model omits the ## heading.
  const NEXT_SECTION_RE = /[📊🔍💡📎📈📄]/u;

  // Every section name across the L1 / L2·L3 / 报表生成 delivery templates.
  // Drives the name-based fallback in extractSection() — when the model
  // drops the canonical emoji (e.g. writes `**结论**:` or `## 根因分析`
  // instead of `📌 结论` / `🔍 根因分析`), we still recognise the section
  // so 结论 / 根因 / 建议 reliably reach the dashboard.
  const SECTION_NAMES = [
    "关键结论", "结论",
    "根因分析", "根因证据链", "根因",
    "行动建议", "管理建议", "建议",
    "关键数据", "口径说明", "附图", "分析提醒", "跨维洞察",
  ];

  // Strip leading list / quote / heading / bold decoration from a line so
  // the first *semantic* token is exposed. Shared by header detection.
  function stripLineDecor(s) {
    return String(s == null ? "" : s)
      .replace(/^[#>*\-\s]+/, "")
      .replace(/^\d+\.\s*/, "")
      .replace(/^\*+/, "")
      .replace(/^\s+/, "");
  }

  // Is `line` a *name-based* section header (canonical emoji omitted)?
  // Returns the matched name, or null. Header-like = after decoration strip
  // the line begins with a section name AND that name is immediately
  // followed by a separator (`:`、`——`、`*`bold-close、`(`…) or end-of-line
  // — so a body sentence that merely starts with the word ("建议各部门加强…")
  // is not mistaken for a header. `names` restricts which names count.
  function nameHeaderOf(line, names) {
    const h = stripLineDecor(line);
    for (const name of names) {
      if (!h.startsWith(name)) continue;
      const rest = h.slice(name.length);
      if (rest === "" || /^[*：:—\-（(、\s]/.test(rest)) return name;
    }
    return null;
  }

  function cleanLeadingDecoration(raw) {
    // Preserve list structure (`- `, `* `, numbered, CJK numerals) and
    // `**bold**` markers so the dashboard can split a section into its
    // individual clauses (each `-` line) and detect `**…**` sub-headers.
    // Marker / bold cleanup for *display* happens later, per clause, inside
    // buildActionableBody(). Here we only drop blockquote markers and
    // trailing whitespace. Leading `#` is still left for boundary detection.
    return raw
      .replace(/^\s*>+\s?/, "")
      .replace(/\s+$/, "");
  }

  // Generic section extractor. Two-pass header detection:
  //   Pass 1 — emoji header: a line whose first non-decoration character is
  //     one of `markers` (the canonical, template-mandated form). Inline
  //     mentions of the same emoji in body text won't falsely anchor it.
  //   Pass 2 — name fallback: ONLY when no emoji header exists anywhere in
  //     the text, accept a *name-based* header (`**结论**:`, `## 根因分析`).
  //     Gating pass 2 on the emoji being entirely absent guarantees a
  //     well-formed answer is never affected by the looser matching.
  // Body runs to the next `## ` heading, the next NEXT_SECTION_RE section
  // emoji, or the next name-based header of a *different* section — so
  // 结论 / 根因 / 建议 reliably reach the dashboard even when the model
  // drifts from the canonical emoji template.
  //
  // `markers` is a list — first element is the canonical emoji, subsequent
  // entries are accepted variants (e.g. 🔎 for 🔍).
  function extractSection(text, markers, namePrefixes /* string[] */) {
    if (!text || typeof text !== "string") return null;
    if (typeof markers === "string") markers = [markers];
    namePrefixes = namePrefixes || [];
    const lines = text.split(/\n/);
    const stripDecor = stripLineDecor;

    // Pass 1 — canonical emoji header.
    let startIdx = -1;
    let usedMarker = null;
    for (let i = 0; i < lines.length; i++) {
      const head = stripDecor(lines[i]);
      const m = markers.find((mk) => head.startsWith(mk));
      if (m) { startIdx = i; usedMarker = m; break; }
    }
    // Pass 2 — name fallback (only when the emoji is entirely absent).
    if (startIdx < 0 && namePrefixes.length) {
      for (let i = 0; i < lines.length; i++) {
        if (nameHeaderOf(lines[i], namePrefixes)) { startIdx = i; break; }
      }
    }
    if (startIdx < 0) return null;

    const out = [];

    let head = stripDecor(lines[startIdx])
      .replace(/\*\*/g, "")
      .trim();
    if (usedMarker) head = head.replace(new RegExp("^" + usedMarker + "\\s*"), "");
    for (const name of namePrefixes) {
      head = head.replace(new RegExp("^" + name + "\\s*(?:[\\(（][^\\)）]*[\\)）])?\\s*"), "");
    }
    head = head.replace(/^[—\-:：]+\s*/, "").trim();
    if (head) out.push(head);

    // Names of OTHER sections — a name-based header for any of them bounds
    // this section (covers the "emoji dropped on the next section too" case).
    const otherNames = SECTION_NAMES.filter((n) => !namePrefixes.includes(n));

    for (let j = startIdx + 1; j < lines.length; j++) {
      const raw = lines[j];
      const nt = raw.trim();

      if (/^#{1,6}\s/.test(nt)) break;

      // Stop only on a *section header* line for some OTHER section emoji —
      // i.e. after decoration strip the line begins with one of the section
      // emojis and is NOT one of our own accepted markers (inline mentions
      // of section emojis inside body text don't terminate the section).
      const headProbe = stripDecor(nt).replace(/\*\*/g, "");
      const isOwnMarker = markers.some((mk) => headProbe.startsWith(mk));
      const probeFirst = headProbe.slice(0, 4);
      if (!isOwnMarker && NEXT_SECTION_RE.test(probeFirst)) break;

      // Stop on a name-based header for a different section (emoji omitted).
      if (nt && nameHeaderOf(nt, otherNames)) break;

      if (!nt) {
        if (out.length > 0) out.push("");
        continue;
      }

      out.push(cleanLeadingDecoration(raw));
    }

    while (out.length > 0 && !out[out.length - 1]) out.pop();
    const result = out.length ? out.join("\n") : null;
    // Guard: when the model echoes the SOP/delivery template into the chat as a
    // plan (e.g. "1. 📌 结论:一句话复述查询结果  2. 📊 数据/图表 ……"), the marker
    // line is a *placeholder*, not a real answer — extracting it produces an
    // awkward "结论:一句话复述查询结果" card. Drop sections whose body is just
    // the template's own descriptive wording.
    if (result && isTemplatePlaceholder(result)) return null;
    return result;
  }

  // True if `content` is SOP-template boilerplate rather than a real answer.
  // The template's section descriptions begin with stems no genuine answer
  // ever opens with ("一句话…", "分层展开…", "用 TableGenerate…"), so a strict
  // first-line prefix test catches plan-dumps without touching valid output.
  const TEMPLATE_PLACEHOLDER_RE =
    /^(一句话|分层展开|基于证据链|用\s*`?TableGenerate|用\s*`?ChartGenerate|多行多列|列出当期值|点出|含量化|指标编码|末尾用一句话)/;
  function isTemplatePlaceholder(content) {
    const first = String(content || "").split(/\n/).map(s => s.trim()).find(Boolean);
    if (!first) return false;
    return TEMPLATE_PLACEHOLDER_RE.test(first);
  }

  function extractConclusion(text) {
    // bi-analyst / report-analyst: "结论"; report-generator: "关键结论".
    return extractSection(text, ["📌"], ["关键结论", "结论"]);
  }

  function extractRootCause(text) {
    // bi-analyst calls it "根因分析(证据链)"; report-analyst calls it "根因证据链".
    // Accept 🔎 as a tolerated variant of 🔍.
    return extractSection(text, ["🔍", "🔎"], ["根因分析", "根因证据链", "根因"]);
  }

  function extractActions(text) {
    // bi-analyst / report-analyst: "行动建议"; report-generator: "管理建议".
    return extractSection(text, ["💡"], ["行动建议", "管理建议", "建议"]);
  }

  // Analysis-level turns (L2 问题寻找 / L3 根因 / L4 决策 / L5 执行) carry one of
  // the deep-analysis section markers below and must keep their tables on the
  // dashboard. L1 取数查询 responses end with a 🧭 引导 and have none of them.
  //   🔍/🔎 根因  💡 建议  🧮 方案对比  🗂️ 行动计划  📟 监控盘  🔁 复盘
  const ANALYSIS_MARKERS = ["🔍", "🔎", "💡", "🧮", "🗂️", "🗂", "📟", "🔁"];
  function detectIntentLevel(text) {
    if (!text || typeof text !== "string") return "L1";
    return ANALYSIS_MARKERS.some((m) => text.includes(m)) ? "L2L3" : "L1";
  }

  function ensureDashboardEmptyHidden() {
    const bucket = B();
    if (!bucket.dashboardHasContent) {
      bucket.dashboardHasContent = true;
      if (el.dashboardEmpty) el.dashboardEmpty.style.display = "none";
    }
  }

  function updateDashboardCount() {
    const bucket = B();
    const n = bucket.dashboardHasContent ? el.dashboardList.querySelectorAll(".dash-card").length : 0;
    if (el.dashboardCount) el.dashboardCount.textContent = n;
  }

  function appendDashboardCard(card) {
    ensureDashboardEmptyHidden();
    el.dashboardList.appendChild(card);
    updateDashboardCount();
    // Keep user at the bottom when new cards arrive — but only if they are
    // already close to the bottom. Don't yank them if they scrolled up.
    const list = el.dashboardList;
    const nearBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 120;
    if (nearBottom) list.scrollTop = list.scrollHeight;
  }

  // Actionable controls belong to the conversation column. Keep the same
  // card markup so export/report logic can consume it, but mount it directly
  // after the current assistant message instead of in the read-only board.
  function appendChatActionCard(card) {
    if (!card || !el.chatScroll) return;
    card.classList.add("chat-action-card");
    const assistantEl = B().currentAssistantEl;
    const container = assistantEl && el.chatScroll.contains(assistantEl)
      ? B().currentAssistantEl.parentElement
      : el.chatScroll;
    container.appendChild(card);
    scrollChatBottom();
  }

  function moveRestoredInteractiveCardsToChat() {
    if (!el.dashboardList || !el.chatScroll) return;
    el.dashboardList
      .querySelectorAll(".dash-rootcause, .dash-actions, .dash-export")
      .forEach((card) => appendChatActionCard(card));
    updateDashboardCount();
  }

  function dashboardConclusionCard(text, turnTag) {
    const card = el_h("div", "dash-card dash-conclusion");
    card.dataset.turn = turnTag;
    card.innerHTML = `
      <div class="dash-head">
        <span class="dash-tag conclusion">📌 结论</span>
        <span class="dash-turn">Turn ${turnTag}</span>
      </div>
      <div class="dash-body">${highlightEntities(text)}</div>`;
    return card;
  }

  function dashboardQuestionCard(text, turnTag) {
    const card = el_h("div", "dash-card dash-question");
    card.dataset.turn = turnTag;
    card.dataset.questionTurn = turnTag;
    card.tabIndex = 0;
    card.setAttribute("role", "button");
    card.title = "点击定位到对话中的这条提问";
    card.innerHTML = `
      <div class="dash-head">
        <span class="dash-tag question">用户</span>
        <span class="dash-turn">Turn ${turnTag}</span>
      </div>
      <div class="dash-body">${esc(text || "")}</div>`;
    return card;
  }

  function ensureRestoredDashboardQuestions() {
    if (!el.dashboardList) return;
    for (const q of (B().questions || [])) {
      const selector = `.dash-question[data-question-turn="${CSS.escape(String(q.turn))}"]`;
      if (el.dashboardList.querySelector(selector)) continue;
      const card = dashboardQuestionCard(q.text, q.turn);
      const firstTurnCard = el.dashboardList.querySelector(
        `.dash-card[data-turn="${CSS.escape(String(q.turn))}"]`
      );
      if (firstTurnCard) el.dashboardList.insertBefore(card, firstTurnCard);
      else el.dashboardList.appendChild(card);
    }
  }

  function bindDashboardQuestionLinks() {
    if (!el.dashboardList || el.dashboardList.dataset.questionLinksBound) return;
    el.dashboardList.dataset.questionLinksBound = "1";
    el.dashboardList.addEventListener("click", (ev) => {
      const card = ev.target.closest(".dash-question[data-question-turn]");
      if (card) scrollToQuestion(card.dataset.questionTurn);
    });
    el.dashboardList.addEventListener("keydown", (ev) => {
      if (ev.key !== "Enter" && ev.key !== " ") return;
      const card = ev.target.closest(".dash-question[data-question-turn]");
      if (!card) return;
      ev.preventDefault();
      scrollToQuestion(card.dataset.questionTurn);
    });
  }

  function dashboardRootCauseCard(text, turnTag) {
    const card = el_h("div", "dash-card dash-rootcause");
    card.dataset.turn = turnTag;
    card.innerHTML = `
      <div class="dash-head">
        <span class="dash-tag rootcause">🔍 根因分析</span>
        <span class="dash-turn">Turn ${turnTag}</span>
      </div>
      ${buildActionableBody(text, "rootcause")}`;
    return card;
  }

  function dashboardActionsCard(text, turnTag) {
    const card = el_h("div", "dash-card dash-actions");
    card.dataset.turn = turnTag;
    card.innerHTML = `
      <div class="dash-head">
        <span class="dash-tag actions">💡 行动建议</span>
        <span class="dash-turn">Turn ${turnTag}</span>
      </div>
      ${buildActionableBody(text, "actions")}`;
    return card;
  }

  function dashboardChartCard(chart, turnTag) {
    const card = el_h("div", "dash-card dash-chart");
    card.dataset.turn = turnTag;
    card.dataset.chartJson = encodeURIComponent(JSON.stringify(chart || {}));
    const title = esc(chart.title || "(未命名)");
    const type = esc(chart.chart_type || "chart");
    const source = chart.saved_path
      ? `<a class="dash-link" href="/charts/${esc(chart.saved_path.split(/[\\/]/).pop())}" target="_blank">open ↗</a>`
      : "";
    const insightBtn = buildInsightButtonHTML(chart);
    card.innerHTML = `
      <div class="dash-head">
        <span class="dash-tag chart">📊 ${type}</span>
        <span class="dash-title">${title}</span>
        <span class="dash-turn">Turn ${turnTag}</span>
        ${source}
        ${insightBtn}
      </div>
      <div class="dash-chart-canvas"></div>`;
    wireInsightButton(card, chart);
    requestAnimationFrame(() => mountDashboardChart(card, chart));
    return card;
  }

  function mountDashboardChart(card, chart) {
    const canvas = card && card.querySelector(".dash-chart-canvas");
    if (!canvas || !chart || !chart.option || typeof echarts === "undefined") return;
    try {
      const inst = echarts.init(canvas);
      inst.setOption(chart.option, true);
      requestAnimationFrame(() => inst.resize());
      const ro = new ResizeObserver(() => inst.resize());
      ro.observe(canvas);
      wireInsightButton(card, chart);
    } catch (e) {
      canvas.innerHTML = `<div class="dash-chart-err">render failed: ${esc(e.message || String(e))}</div>`;
    }
  }

  // ------------------------------------------------------------------
  // Multi-dim chart (ChartGenerateMultiDim) — chat + dashboard cards
  // ------------------------------------------------------------------
  function attachChatMultiChart(spec) {
    const bucket = B();
    const container = bucket.currentAssistantEl
      ? bucket.currentAssistantEl.parentElement
      : el.chatScroll;
    const card = buildMultiChartCard(spec);
    container.appendChild(card);
    scrollChatBottom();
    requestAnimationFrame(() => mountMultiChart(card, spec));
  }

  function buildMultiChartCard(spec) {
    const card = el_h("div", "multidim-card");
    card.dataset.chartJson = encodeURIComponent(JSON.stringify(spec || {}));
    const title = esc(spec.title || "(未命名)");
    const subtitle = spec.subtitle ? `<span class="multidim-subtitle">${esc(spec.subtitle)}</span>` : "";
    const metric = spec.metric_code ? `<span class="multidim-metric">${esc(spec.metric_code)}</span>` : "";
    const source = spec.source_note ? `<span class="multidim-source">Source · ${esc(spec.source_note)}</span>` : "";
    const savedLink = spec.saved_path
      ? `<a class="multidim-saved" href="/charts/${esc(String(spec.saved_path).split(/[\\/]/).pop())}" target="_blank">open ↗</a>`
      : "";
    const dims = Array.isArray(spec.dimensions) ? spec.dimensions : [];
    const options = dims.map((d) =>
      `<option value="${esc(d.key)}"${d.key === spec.default_dim ? " selected" : ""}>${esc(d.label || d.key)}</option>`
    ).join("");
    const summary = spec.summary ? `<div class="multidim-summary">📌 ${esc(spec.summary)}</div>` : "";
    const footnote = spec.footnote ? `<div class="multidim-footnote">${esc(spec.footnote)}</div>` : "";

    card.innerHTML = `
      <div class="multidim-head">
        <span class="multidim-tag">📊 多维洞察</span>
        <span class="multidim-title">${title}</span>
        ${metric}
        ${subtitle}
        ${source}
        ${savedLink}
      </div>
      <div class="multidim-toolbar">
        <label class="multidim-label">维度</label>
        <select class="multidim-select">${options}</select>
        <span class="multidim-dim-summary"></span>
      </div>
      <div class="multidim-canvas"></div>
      ${summary}
      ${footnote}`;
    return card;
  }

  function mountMultiChart(card, spec) {
    const canvas = card.querySelector(".multidim-canvas");
    const select = card.querySelector(".multidim-select");
    const dimSummaryEl = card.querySelector(".multidim-dim-summary");
    if (!canvas) return;
    if (typeof echarts === "undefined") {
      canvas.innerHTML = '<div class="multidim-err">ECharts 未加载</div>';
      return;
    }
    const dims = Array.isArray(spec.dimensions) ? spec.dimensions : [];
    if (dims.length === 0) {
      canvas.innerHTML = '<div class="multidim-err">无维度数据</div>';
      return;
    }
    const dimMap = new Map(dims.map((d) => [d.key, d]));
    let inst;
    try {
      inst = echarts.init(canvas);
    } catch (e) {
      canvas.innerHTML = `<div class="multidim-err">init failed: ${esc(e.message || String(e))}</div>`;
      return;
    }
    function show(key) {
      const d = dimMap.get(key) || dims[0];
      try {
        if (d && d.option) inst.setOption(d.option, true);
      } catch (e) {
        canvas.innerHTML = `<div class="multidim-err">render failed: ${esc(e.message || String(e))}</div>`;
        return;
      }
      if (dimSummaryEl) dimSummaryEl.textContent = (d && d.summary) || "";
    }
    show(spec.default_dim || (dims[0] && dims[0].key));
    if (select) select.addEventListener("change", (e) => show(e.target.value));
    requestAnimationFrame(() => inst.resize());
    try {
      const ro = new ResizeObserver(() => inst.resize());
      ro.observe(canvas);
    } catch (_) { /* ResizeObserver unsupported, ignore */ }
  }

  function dashboardMultiChartCard(spec, turnTag) {
    const card = el_h("div", "dash-card dash-multidim");
    card.dataset.turn = turnTag;
    card.dataset.chartJson = encodeURIComponent(JSON.stringify(spec || {}));
    const title = esc(spec.title || "(未命名)");
    const metric = spec.metric_code ? `<span class="dash-metric">${esc(spec.metric_code)}</span>` : "";
    const source = spec.saved_path
      ? `<a class="dash-link" href="/charts/${esc(String(spec.saved_path).split(/[\\/]/).pop())}" target="_blank">open ↗</a>`
      : "";
    const dims = Array.isArray(spec.dimensions) ? spec.dimensions : [];
    const options = dims.map((d) =>
      `<option value="${esc(d.key)}"${d.key === spec.default_dim ? " selected" : ""}>${esc(d.label || d.key)}</option>`
    ).join("");
    card.innerHTML = `
      <div class="dash-head">
        <span class="dash-tag multidim">📊 多维</span>
        <span class="dash-title">${title}</span>
        ${metric}
        <span class="dash-turn">Turn ${turnTag}</span>
        ${source}
      </div>
      <div class="multidim-toolbar dash-toolbar">
        <label class="multidim-label">维度</label>
        <select class="multidim-select">${options}</select>
        <span class="multidim-dim-summary"></span>
      </div>
      <div class="dash-chart-canvas"></div>`;
    requestAnimationFrame(() => {
      const canvas = card.querySelector(".dash-chart-canvas");
      const select = card.querySelector(".multidim-select");
      const dimSummaryEl = card.querySelector(".multidim-dim-summary");
      if (!canvas || typeof echarts === "undefined" || dims.length === 0) return;
      const dimMap = new Map(dims.map((d) => [d.key, d]));
      let inst;
      try {
        inst = echarts.init(canvas);
      } catch (e) {
        canvas.innerHTML = `<div class="dash-chart-err">init failed: ${esc(e.message || String(e))}</div>`;
        return;
      }
      function show(key) {
        const d = dimMap.get(key) || dims[0];
        try {
          if (d && d.option) inst.setOption(d.option, true);
        } catch (e) {
          canvas.innerHTML = `<div class="dash-chart-err">render failed: ${esc(e.message || String(e))}</div>`;
          return;
        }
        if (dimSummaryEl) dimSummaryEl.textContent = (d && d.summary) || "";
      }
      show(spec.default_dim || (dims[0] && dims[0].key));
      if (select) select.addEventListener("change", (e) => show(e.target.value));
      requestAnimationFrame(() => inst.resize());
      try {
        const ro = new ResizeObserver(() => inst.resize());
        ro.observe(canvas);
      } catch (_) { /* ResizeObserver unsupported */ }
    });
    return card;
  }

  function hydrateRestoredDashboard() {
    if (!el.dashboardList) return;
    el.dashboardList.querySelectorAll(".dash-export[data-turn]").forEach((card) => {
      bindExportCard(card, card.dataset.turn);
    });
    el.dashboardList.querySelectorAll(".dash-card[data-chart-json]").forEach((card) => {
      try {
        const data = JSON.parse(decodeURIComponent(card.dataset.chartJson));
        if (card.classList.contains("dash-multidim")) {
          // Recreate the dimension selector listeners and chart instance.
          mountRestoredMultiDashboardChart(card, data);
        } else {
          mountDashboardChart(card, data);
        }
      } catch (e) {
        console.warn("历史图表恢复失败", e);
      }
    });
  }

  function hydrateRestoredChat() {
    if (!el.chatScroll) return;
    // Restored chat is inserted with innerHTML, so the click handlers that
    // buildChatStep normally attaches are not present. Rebind them here.
    el.chatScroll.querySelectorAll(".step").forEach((step) => {
      const head = step.querySelector(".step-header");
      if (head && !head.dataset.clickBound) {
        head.dataset.clickBound = "1";
        head.addEventListener("click", () => step.classList.toggle("open"));
      }
      step.querySelectorAll(".chip").forEach((ch) => {
        if (ch.dataset.clickBound) return;
        ch.dataset.clickBound = "1";
        ch.addEventListener("click", (ev) => {
          ev.stopPropagation();
          flashOntologyEntity(ch.dataset.code);
        });
      });
    });
    el.chatScroll.querySelectorAll(".chart-card[data-chart-json]").forEach((card) => {
      try { mountChart(card, JSON.parse(decodeURIComponent(card.dataset.chartJson))); }
      catch (e) { console.warn("历史聊天图表恢复失败", e); }
    });
    el.chatScroll.querySelectorAll(".multidim-card[data-chart-json]").forEach((card) => {
      try { mountMultiChart(card, JSON.parse(decodeURIComponent(card.dataset.chartJson))); }
      catch (e) { console.warn("历史多维图表恢复失败", e); }
    });
    el.chatScroll.querySelectorAll(".dash-export[data-turn]").forEach((card) => {
      bindExportCard(card, card.dataset.turn);
    });
  }

  function hydrateRestoredInspector() {
    const bind = (root, selector, event, handler) => {
      if (!root) return;
      root.querySelectorAll(selector).forEach((node) => {
        if (node.dataset.clickBound) return;
        node.dataset.clickBound = "1";
        node.addEventListener(event, handler.bind(null, node));
      });
    };
    bind(el.ontologyList, ".entity-card .entity-head", "click", (head) => {
      head.closest(".entity-card").classList.toggle("open");
    });
    bind(el.toolList, ".tool-card .tool-head", "click", (head) => {
      head.closest(".tool-card").classList.toggle("open");
    });
    bind(el.toolList, ".tool-card .chip", "click", (chip, ev) => {
      ev.stopPropagation();
      flashOntologyEntity(chip.dataset.code);
    });
    bind(el.llmList, ".llm-card .llm-head", "click", (head) => {
      head.closest(".llm-card").classList.toggle("open");
    });
  }

  function mountRestoredMultiDashboardChart(card, spec) {
    const canvas = card.querySelector(".dash-chart-canvas");
    const select = card.querySelector(".multidim-select");
    const summary = card.querySelector(".multidim-dim-summary");
    const dims = Array.isArray(spec && spec.dimensions) ? spec.dimensions : [];
    if (!canvas || !dims.length || typeof echarts === "undefined") return;
    try {
      const inst = echarts.init(canvas);
      const dimMap = new Map(dims.map((d) => [d.key, d]));
      const show = (key) => {
        const d = dimMap.get(key) || dims[0];
        if (d && d.option) inst.setOption(d.option, true);
        if (summary) summary.textContent = (d && d.summary) || "";
      };
      show(spec.default_dim || dims[0].key);
      if (select) select.addEventListener("change", (e) => show(e.target.value));
      requestAnimationFrame(() => inst.resize());
      const ro = new ResizeObserver(() => inst.resize());
      ro.observe(canvas);
    } catch (e) {
      canvas.innerHTML = `<div class="dash-chart-err">render failed: ${esc(e.message || String(e))}</div>`;
    }
  }

  function pushMultiChartToDashboard(spec) {
    const bucket = B();
    appendDashboardCard(dashboardMultiChartCard(spec, bucket.currentTurnTag || 1));
  }

  function dashboardTableCard(tbl, turnTag) {
    const card = el_h("div", "dash-card dash-table");
    card.dataset.turn = turnTag;
    const title = esc(tbl.title || "(未命名)");
    const source = tbl.source_note ? `<span class="dash-source">Source · ${esc(tbl.source_note)}</span>` : "";
    card.innerHTML = `
      <div class="dash-head">
        <span class="dash-tag table">📋 TABLE</span>
        <span class="dash-title">${title}</span>
        <span class="dash-turn">Turn ${turnTag}</span>
        ${source}
      </div>
      <div class="dash-table-wrap"></div>`;
    // Reuse the same grid builder as the inline chat table; strip redundant
    // head so the dashboard card's own head is the only one visible.
    const inner = buildTableCard(tbl);
    const scroll = inner.querySelector(".table-scroll");
    const summary = inner.querySelector(".table-summary");
    const wrap = card.querySelector(".dash-table-wrap");
    if (scroll) wrap.appendChild(scroll);
    if (summary) wrap.appendChild(summary);
    return card;
  }

  function pushConclusionIfAny(text) {
    const bucket = B();
    const content = extractConclusion(text);
    if (!content) return;
    // Dedup within session — identical text not useful twice
    const key = content.trim().toLowerCase();
    if (bucket.conclusionSeen.has(key)) return;
    bucket.conclusionSeen.add(key);
    appendDashboardCard(dashboardConclusionCard(content, bucket.currentTurnTag || 1));
  }

  // Returns true iff a 根因 card was actually appended (used to decide
  // L1-vs-L2/L3 for the turn — see the llm_response / done handlers).
  function pushRootCauseIfAny(text) {
    const bucket = B();
    const content = extractRootCause(text);
    if (!content) return false;
    bucket.rootCauseSeen = bucket.rootCauseSeen || new Set();
    const key = content.trim().toLowerCase();
    if (bucket.rootCauseSeen.has(key)) return true;
    bucket.rootCauseSeen.add(key);
    appendChatActionCard(dashboardRootCauseCard(content, bucket.currentTurnTag || 1));
    return true;
  }

  function pushActionsIfAny(text) {
    const bucket = B();
    const content = extractActions(text);
    if (!content) return false;
    bucket.actionsSeen = bucket.actionsSeen || new Set();
    const key = content.trim().toLowerCase();
    if (bucket.actionsSeen.has(key)) return true;
    bucket.actionsSeen.add(key);
    appendChatActionCard(dashboardActionsCard(content, bucket.currentTurnTag || 1));
    return true;
  }

  // ------------------------------------------------------------------
  // Pinned task list — pinned above the chat scroll (#chat-todo). Driven
  // automatically from the six-step SOP (not from the model), so it always
  // reflects real progress even when the model never calls a todo tool:
  //   ① 识别意图 → ② 准备口径/上下文 → ③ 规划取数 → ④ 执行取数 →
  //   ⑤ 深度分析 → ⑥ 汇总交付(结论+图表)
  // A forward-only `sopStep` cursor advances on tool/marker signals; all
  // steps before it read completed, the cursor reads in_progress, the rest
  // pending. The whole list is seeded fresh at the start of each user turn.
  // ------------------------------------------------------------------
  const TODO_BOX = { pending: "○", in_progress: "◔", completed: "✔" };
  const SOP_STEPS = [
    "识别意图",
    "准备口径与上下文",
    "规划取数方案",
    "执行查询取数",
    "深度分析",
    "汇总交付(结论 + 图表)",
  ];
  // Tool → the SOP step it proves we've reached (forward-fill marks earlier
  // steps done). Planning (idx 2) has no tool — SQLRun jumps to idx 3 and
  // forward-fill completes it.
  const SOP_TOOL_STEP = {
    OntologyQuery: 1, TermDisambiguate: 1, MetricLookup: 1, RelationLookup: 1,
    EntityDescribe: 1, ListBusinessObjects: 1, ListTables: 1, DescribeTable: 1,
    SQLRun: 3,
    TableGenerate: 5, ChartGenerate: 5, ChartGenerateMultiDim: 5,
  };

  // Seed a fresh SOP checklist at the start of a user turn (data mode only).
  function initSopTodos() {
    const bucket = B();
    bucket.sopStep = 0;
    bucket.todos = SOP_STEPS.map((label, i) => ({
      content: label, status: i === 0 ? "in_progress" : "pending",
    }));
    renderTodoPanel();
  }
  function applySopStatuses() {
    const bucket = B();
    const cur = bucket.sopStep || 0;
    bucket.todos = (bucket.todos || []).map((t, i) => ({
      content: t.content,
      status: i < cur ? "completed" : (i === cur ? "in_progress" : "pending"),
    }));
  }
  // Move the cursor forward to `stepIdx` (never backwards), re-render if moved.
  function advanceSop(stepIdx) {
    const bucket = B();
    if (!bucket.todos || !bucket.todos.length) return;  // no active SOP list
    if (typeof bucket.sopStep !== "number") bucket.sopStep = 0;
    if (!(stepIdx > bucket.sopStep)) return;
    bucket.sopStep = stepIdx;
    applySopStatuses();
    renderTodoPanel();
  }
  function advanceSopForTool(name) {
    const step = SOP_TOOL_STEP[name];
    if (step != null) advanceSop(step);
  }
  function advanceSopForText(text) {
    if (!text) return;
    if (ANALYSIS_MARKERS.some(m => text.includes(m))) advanceSop(4);  // 深度分析
    if (text.includes("📌")) advanceSop(5);                            // 交付
  }

  // Render the active bucket's task list into the shared #chat-todo element.
  function renderTodoPanel() {
    if (!el.chatTodo) return;
    const questions = (B().questions || []).filter((q) => q && q.text);
    const todos = (B().todos) || [];
    if (!todos.length && !questions.length) { el.chatTodo.hidden = true; return; }
    el.chatTodo.hidden = false;
    const done = todos.filter(t => t && t.status === "completed").length;
    if (el.chatTodoCount) {
      const progress = todos.length ? `${done}/${todos.length}` : "";
      el.chatTodoCount.textContent = progress + (questions.length ? `${progress ? " · " : ""}${questions.length} 个问题` : "");
    }
    const questionSection = questions.length ?
      `<li class="chat-todo-section">用户提问</li>` + questions.map((q, i) =>
        `<li class="chat-question-item" data-question-turn="${esc(q.turn)}" tabindex="0" role="button" title="点击定位到这条提问">` +
        `<span class="chat-question-turn">${i + 1}</span>` +
        `<span class="chat-question-text">${esc(q.text)}</span></li>`).join("") : "";
    const todoSection = todos.length ? `<li class="chat-todo-section">分析进度</li>` + todos.map((t) => {
      const status = (t && t.status) || "pending";
      const box = TODO_BOX[status] || "○";
      return `<li class="chat-todo-item is-${esc(status)}">` +
             `<span class="chat-todo-box">${box}</span>` +
             `<span class="chat-todo-text">${esc((t && t.content) || "")}</span></li>`;
    }).join("") : "";
    el.chatTodoList.innerHTML = questionSection + todoSection;
  }
  if (el.chatTodoHead) {
    el.chatTodoHead.addEventListener("click", () => {
      el.chatTodo.classList.toggle("collapsed");
    });
  }
  if (el.chatTodoList) {
    el.chatTodoList.addEventListener("click", (ev) => {
      const item = ev.target.closest("[data-question-turn]");
      if (item) scrollToQuestion(item.dataset.questionTurn);
    });
    el.chatTodoList.addEventListener("keydown", (ev) => {
      if (ev.key !== "Enter" && ev.key !== " ") return;
      const item = ev.target.closest("[data-question-turn]");
      if (!item) return;
      ev.preventDefault();
      scrollToQuestion(item.dataset.questionTurn);
    });
  }
  // Safety net: a turn that delivered a 📌 结论 is a finished deliverable, so
  // the checklist should read 100% — flip any leftover in_progress/pending to
  // completed (e.g. an L1 query that never hits 深度分析). Only runs when a
  // conclusion was actually delivered; interrupted/errored turns keep their
  // honest partial state.
  function reconcileTodosOnConclusion() {
    const bucket = B();
    const todos = bucket.todos || [];
    if (!todos.length) return;
    let changed = false;
    bucket.todos = todos.map((t) => {
      if (t && t.status !== "completed") { changed = true; return { ...t, status: "completed" }; }
      return t;
    });
    if (changed) { bucket.sopStep = SOP_STEPS.length; renderTodoPanel(); }
  }

  function pushChartToDashboard(chart) {
    const bucket = B();
    appendDashboardCard(dashboardChartCard(chart, bucket.currentTurnTag || 1));
  }

  function pushTableToDashboard(table) {
    const bucket = B();
    appendDashboardCard(dashboardTableCard(table, bucket.currentTurnTag || 1));
  }

  // ------------------------------------------------------------------
  // Per-turn HTML report export
  // ------------------------------------------------------------------
  function appendTurnExportButton(turnTag) {
    const tagStr = String(turnTag);
    // Export controls are useful when the turn has board cards or actionable
    // root-cause/recommendation cards mounted in the chat column.
    const dataCards = turnCards(tagStr).filter((card) => !card.classList.contains("dash-question"));
    if (!dataCards.length) return;
    // Avoid duplicate export buttons in either pane.
    if (document.querySelector(".dash-export[data-turn=\"" + tagStr + "\"]")) return;

    const card = el_h("div", "dash-card dash-export");
    card.dataset.turn = tagStr;
    card.innerHTML =
      '<button type="button" class="dash-export-btn" data-turn="' + tagStr + '">' +
      '📤 导出本轮报告 (HTML)</button>' +
      '<button type="button" class="dash-export-btn dash-word-btn" data-turn="' + tagStr + '">' +
      '📄 导出 Word</button>' +
      '<button type="button" class="dash-export-btn dash-sync-btn" data-turn="' + tagStr + '">' +
      '🏠 同步到主页</button>' +
      '<button type="button" class="dash-export-btn dash-feishu-btn" data-turn="' + tagStr + '">' +
      '🐦 分享到飞书</button>' +
      '<div class="dash-export-status" data-turn="' + tagStr + '"></div>';
    bindExportCard(card, turnTag);
    appendChatActionCard(card);
  }

  function bindExportCard(card, turnTag) {
    if (!card || card.dataset.exportBound === "1") return;
    card.dataset.exportBound = "1";
    card.querySelector(
      ".dash-export-btn:not(.dash-word-btn):not(.dash-sync-btn):not(.dash-feishu-btn)")
      ?.addEventListener("click", () => exportTurnReport(turnTag));
    card.querySelector(".dash-word-btn")
      ?.addEventListener("click", (ev) => handleWordButton(turnTag, ev.currentTarget));
    card.querySelector(".dash-sync-btn")?.addEventListener("click", () => {
      syncTurnReportToHome(turnTag, card);
    });
    card.querySelector(".dash-feishu-btn")?.addEventListener("click", () => {
      shareTurnReportToFeishu(turnTag, card);
    });
  }

  function renderTextCardForExport(card) {
    const tagEl = card.querySelector(".dash-tag");
    const body = card.querySelector(".dash-body");
    const tag = tagEl ? tagEl.textContent.trim() : "";
    const cls = !tagEl ? ""
      : (tagEl.classList.contains("conclusion") ? "conclusion"
       : tagEl.classList.contains("rootcause")  ? "rootcause"
       : tagEl.classList.contains("actions")    ? "actions" : "");
    let bodyHTML = "";
    if (body) {
      const clone = body.cloneNode(true);
      // Per-item action buttons are UI-only — keep them out of exports.
      clone.querySelectorAll(".dash-item-actions").forEach(n => n.remove());
      bodyHTML = clone.innerHTML;
    }
    return (
      '<section class="report-section report-' + cls + '">' +
      '  <header><span class="report-tag ' + cls + '">' + esc(tag) + '</span></header>' +
      '  <div class="report-body">' + bodyHTML + '</div>' +
      '</section>'
    );
  }

  function renderChartCardForExport(card) {
    const title = (card.querySelector(".dash-title") || {}).textContent || "图表";
    const tag = (card.querySelector(".dash-tag") || {}).textContent || "📊 CHART";
    const source = (card.querySelector(".dash-source") || {}).textContent || "";
    let imgTag = "";
    const canvas = card.querySelector(".dash-chart-canvas, .dash-multidim-canvas");
    if (canvas && typeof echarts !== "undefined") {
      try {
        const inst = echarts.getInstanceByDom(canvas);
        if (inst) {
          const dataUrl = inst.getDataURL({
            type: "png", pixelRatio: 2, backgroundColor: "#ffffff",
          });
          imgTag = '<img src="' + dataUrl + '" alt="' + esc(title) + '" />';
        }
      } catch (_) { /* echarts may not have hydrated for some reason */ }
    }
    return (
      '<section class="report-section report-chart">' +
      '  <header>' +
      '    <span class="report-tag chart">' + esc(tag.trim()) + '</span>' +
      '    <span class="report-title">' + esc(title.trim()) + '</span>' +
      '  </header>' +
      (imgTag || '<div class="report-empty">(图表未渲染)</div>') +
      (source ? '<div class="report-source">' + esc(source.trim()) + '</div>' : "") +
      '</section>'
    );
  }

  function renderTableCardForExport(card) {
    const title = (card.querySelector(".dash-title") || {}).textContent || "数据表";
    const tag = (card.querySelector(".dash-tag") || {}).textContent || "📋 TABLE";
    const wrap = card.querySelector(".dash-table-wrap");
    const inner = wrap ? wrap.innerHTML : "";
    return (
      '<section class="report-section report-table">' +
      '  <header>' +
      '    <span class="report-tag table">' + esc(tag.trim()) + '</span>' +
      '    <span class="report-title">' + esc(title.trim()) + '</span>' +
      '  </header>' +
      '  <div class="report-table-wrap">' + inner + '</div>' +
      '</section>'
    );
  }

  function buildReportHTML(turnTag, sectionsHTML, opts) {
    opts = opts || {};
    const dateStr = new Date().toLocaleString("zh-CN", { hour12: false });
    const modeName = state.mode === "report" ? "报表分析" : "智能分析";
    const docTitle = opts.title || ("硕磐智能 · " + modeName + " 报告");
    const docMeta = opts.metaText || ("Turn " + turnTag + " · " + esc(dateStr));
    const leadHTML = opts.leadHTML || "";
    return [
      '<!doctype html>',
      '<html lang="zh-CN">',
      '<head>',
      '<meta charset="utf-8">',
      '<title>硕磐智能 · ' + modeName + ' · Turn ' + turnTag + '</title>',
      '<style>',
      '* { box-sizing: border-box; }',
      'body { font-family: "PingFang SC", "Microsoft YaHei", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #1f2937; background: #f7f9fc; margin: 0; padding: 28px; }',
      '.report { max-width: 960px; margin: 0 auto; background: #fff; border-radius: 8px; padding: 32px 40px; box-shadow: 0 2px 12px rgba(0,0,0,.06); }',
      '.report-head { border-bottom: 2px solid #0b7ff3; padding-bottom: 14px; margin-bottom: 22px; display: flex; justify-content: space-between; align-items: flex-end; gap: 12px; }',
      '.report-head h1 { margin: 0 0 4px; font-size: 20px; color: #111827; font-weight: 700; }',
      '.report-meta { font-size: 12px; color: #6b7280; }',
      '.report-section { margin: 20px 0; }',
      '.report-section header { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }',
      '.report-tag { font-size: 11px; font-weight: 700; letter-spacing: 1px; padding: 3px 8px; border-radius: 3px; text-transform: uppercase; }',
      '.report-tag.conclusion { color: #b45309; border: 1px solid #f5a524; }',
      '.report-tag.rootcause  { color: #b91c1c; border: 1px solid #f87171; }',
      '.report-tag.actions    { color: #4d7c0f; border: 1px solid #a3e635; }',
      '.report-tag.chart      { color: #0e7490; border: 1px solid #22d3ee; }',
      '.report-tag.table      { color: #6d28d9; border: 1px solid #a78bfa; }',
      '.report-title { font-size: 14px; font-weight: 600; color: #111827; }',
      '.report-source { font-size: 11px; color: #6b7280; margin-top: 6px; }',
      '.report-body { white-space: pre-wrap; line-height: 1.7; font-size: 14px; color: #1f2937; }',
      '.report-chart img { width: 100%; height: auto; border: 1px solid #e5e7eb; border-radius: 4px; }',
      '.report-empty { padding: 24px; text-align: center; color: #9ca3af; font-size: 12px; border: 1px dashed #e5e7eb; border-radius: 4px; }',
      '.report-table-wrap { overflow-x: auto; }',
      '.report-table-wrap table { width: 100%; border-collapse: collapse; font-size: 13px; }',
      '.report-table-wrap th, .report-table-wrap td { border: 1px solid #e5e7eb; padding: 6px 10px; text-align: left; }',
      '.report-table-wrap thead th { background: #f3f4f6; font-weight: 600; }',
      '.report-toolbar { padding: 14px 18px; border: 1px solid #e5e7eb; border-radius: 6px; background: #fafafa; text-align: right; margin-top: 24px; }',
      '.btn { display: inline-block; padding: 7px 14px; margin-left: 8px; font-size: 13px; border-radius: 4px; cursor: pointer; border: 1px solid #0b7ff3; background: #0b7ff3; color: #fff; }',
      '.btn:hover { background: #0a6cd1; }',
      '.btn-ghost { background: #fff; color: #0b7ff3; }',
      '.btn-ghost:hover { background: #eaf3ff; }',
      '.report-toc { background: #f8fafc; border: 1px solid #e5e7eb; border-radius: 6px; padding: 14px 20px; margin: 18px 0; }',
      '.report-summary { background: #f0f7ff; border: 1px solid #cfe3fb; border-radius: 6px; padding: 14px 20px; margin: 18px 0; }',
      '.report-lead-title { font-size: 13px; font-weight: 700; color: #0b7ff3; margin-bottom: 8px; }',
      '.report-toc ol { margin: 0; padding-left: 22px; font-size: 13px; color: #374151; line-height: 1.95; }',
      '.report-summary p { margin: 0; font-size: 13px; line-height: 1.85; color: #1f2937; }',
      '.doc-section { margin: 24px 0; }',
      '.doc-section-head { font-size: 16px; font-weight: 700; color: #111827; border-left: 4px solid #0b7ff3; padding-left: 10px; margin: 24px 0 8px; }',
      '.doc-section-intro { font-size: 13px; line-height: 1.85; color: #4b5563; margin: 0 0 12px; }',
      '@media print { body { padding: 0; background: #fff; } .report { box-shadow: none; padding: 0; max-width: none; } .report-toolbar { display: none; } }',
      '</style>',
      '</head>',
      '<body>',
      '<div class="report">',
      '  <div class="report-head">',
      '    <div>',
      '      <h1>' + esc(docTitle) + '</h1>',
      '      <div class="report-meta">' + docMeta + '</div>',
      '    </div>',
      '  </div>',
      leadHTML,
      sectionsHTML,
      '  <div class="report-toolbar">',
      '    <button class="btn btn-ghost" onclick="window.print()">打印 / 保存为 PDF</button>',
      '    <button class="btn" onclick="(function(){var b=new Blob([document.documentElement.outerHTML],{type:\'text/html;charset=utf-8\'});var a=document.createElement(\'a\');a.href=URL.createObjectURL(b);a.download=\'report-turn' + turnTag + '.html\';a.click();})()">下载 HTML</button>',
      '  </div>',
      '</div>',
      '</body>',
      '</html>',
    ].join("\n");
  }

  // Render one dashboard card to its export <section> HTML.
  function renderCardForExport(card) {
    if (card.classList.contains("dash-chart") ||
        card.classList.contains("dash-multidim")) {
      return renderChartCardForExport(card);
    }
    if (card.classList.contains("dash-table")) {
      return renderTableCardForExport(card);
    }
    if (card.classList.contains("dash-conclusion") ||
        card.classList.contains("dash-rootcause")  ||
        card.classList.contains("dash-actions")) {
      return renderTextCardForExport(card);
    }
    return "";
  }

  function turnCards(turnTag) {
    const tag = String(turnTag);
    const dashboardCards = el.dashboardList
      ? Array.from(el.dashboardList.querySelectorAll(".dash-card[data-turn=\"" + tag + "\"]"))
      : [];
    const chatCards = el.chatScroll
      ? Array.from(el.chatScroll.querySelectorAll(".chat-action-card[data-turn=\"" + tag + "\"]"))
      : [];
    return dashboardCards.concat(chatCards)
      .filter((c) => !c.classList.contains("dash-export"));
  }

  // Collect this turn's dashboard cards into a standalone report HTML.
  // Returns { html, cardCount } or null when the turn has no content.
  function collectTurnReportHTML(turnTag) {
    const cards = turnCards(turnTag);
    if (cards.length === 0) return null;
    const sections = cards.map(renderCardForExport).join("\n");
    return { html: buildReportHTML(turnTag, sections), cardCount: cards.length };
  }

  // A short summary of the turn for the homepage 问题清单 entry:
  // prefer the user's question, fall back to the first conclusion text.
  function turnSummaryText(turnTag) {
    const q = (B().turnQuestions || {})[turnTag];
    if (q && q.trim()) return q.trim().slice(0, 80);
    const concl = el.dashboardList.querySelector(
      ".dash-card.dash-conclusion[data-turn=\"" + String(turnTag) + "\"] .dash-body"
    );
    if (concl && concl.textContent.trim()) return concl.textContent.trim().slice(0, 80);
    return "智能分析报告 · Turn " + turnTag;
  }

  function setExportStatus(card, text, isErr) {
    const s = card && card.querySelector(".dash-export-status");
    if (!s) return;
    s.textContent = text || "";
    s.style.color = isErr ? "var(--danger,#8d6e63)" : "var(--text-2,#9e9e9e)";
  }

  function syncTurnReportToHome(turnTag, card) {
    const r = collectTurnReportHTML(turnTag);
    if (!r) { setExportStatus(card, "本轮没有可同步的内容", true); return; }
    const target = (window.parent && window.parent !== window) ? window.parent : null;
    if (!target) { setExportStatus(card, "未检测到主页(workbench 未嵌入驾驶舱)", true); return; }
    const quad = state.quadrant || null;
    const source = quad
      ? ((typeof QUADRANT_PROMPT_META !== "undefined" && QUADRANT_PROMPT_META[quad] &&
          QUADRANT_PROMPT_META[quad].label) || "象限分析")
      : "通用AI助手";
    const reqId = "sync-" + Date.now();
    function ackHandler(ev) {
      const m = ev.data;
      if (!m || m.channel !== "cockpit-home-sync-ack" || m.req !== reqId) return;
      window.removeEventListener("message", ackHandler);
      clearTimeout(timer);
      setExportStatus(card, "✓ 已同步到主页问题清单(可下钻)");
    }
    const timer = setTimeout(() => {
      window.removeEventListener("message", ackHandler);
      setExportStatus(card, "✓ 已发送同步请求(主页未回执)");
    }, 4000);
    window.addEventListener("message", ackHandler);
    try {
      target.postMessage({
        channel: "cockpit-home-sync",
        quadrant: quad,
        source: source,
        summary: turnSummaryText(turnTag),
        html: r.html,
        ts: new Date().toISOString(),
        req: reqId,
      }, "*");
      setExportStatus(card, "同步中…");
    } catch (err) {
      window.removeEventListener("message", ackHandler);
      clearTimeout(timer);
      setExportStatus(card, "同步失败:" + String(err && err.message || err), true);
    }
  }

  // 分享到飞书:占位入口,未接入飞书开放平台。
  function shareTurnReportToFeishu(turnTag, card) {
    const r = collectTurnReportHTML(turnTag);
    if (!r) { setExportStatus(card, "本轮没有可分享的内容", true); return; }
    setExportStatus(card, "「分享到飞书」为占位入口,未接入飞书开放平台(占位:仅展示功能选项)");
  }

  function exportTurnReport(turnTag) {
    const tagStr = String(turnTag);
    const r = collectTurnReportHTML(turnTag);
    if (!r) {
      alert("本轮没有可导出的看板内容。");
      return;
    }
    const html = r.html;
    const blob = new Blob([html], { type: "text/html;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const win = window.open(url, "_blank");
    // If popups are blocked, fall back to anchor-download.
    if (!win) {
      const a = document.createElement("a");
      a.href = url;
      a.download = "report-turn" + tagStr + ".html";
      a.click();
    }
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  }

  // --- Word export ------------------------------------------------------
  // Clicking 导出 Word makes ONE LLM call (/api/report/compose) that
  // integrates the turn's dashboard content into a formal report
  // document — title, executive summary, a sectioned 目录 with a
  // per-section intro paragraph — then assembles the .doc, interleaving
  // the real rendered tables/charts. Falls back to a plain dump if the
  // LLM call fails. Word opens HTML-content .doc files natively.

  function cardExportKind(card) {
    if (card.classList.contains("dash-chart") ||
        card.classList.contains("dash-multidim")) return "chart";
    if (card.classList.contains("dash-table")) return "table";
    return "text";
  }

  function cardExportTitle(card) {
    const t = card.querySelector(".dash-title");
    if (t && t.textContent.trim()) return t.textContent.trim();
    const tag = card.querySelector(".dash-tag");
    return tag ? tag.textContent.trim() : "";
  }

  // A compact text representation of a card so the compose LLM knows
  // what each block contains (without shipping rendered HTML / images).
  function cardExportText(card) {
    if (card.classList.contains("dash-table")) {
      const table = card.querySelector(".dash-table-wrap table");
      if (!table) return "";
      return Array.from(table.querySelectorAll("tr")).slice(0, 12).map((tr) =>
        Array.from(tr.querySelectorAll("th,td"))
          .map((c) => c.textContent.trim()).join(" | ")
      ).join(" ; ");
    }
    if (card.classList.contains("dash-chart") ||
        card.classList.contains("dash-multidim")) {
      const src = card.querySelector(".dash-source");
      return src ? src.textContent.trim() : "";
    }
    const body = card.querySelector(".dash-body");
    return body ? body.textContent.trim() : "";
  }

  // Assemble a professional Word report DOCUMENT from the LLM plan + the
  // real rendered cards. Self-contained HTML styled as a formal report —
  // cover page · 目录 · numbered sections · formal tables. Word opens
  // HTML-content .doc files and renders this as a proper document.
  // plan = { title, summary, sections:[{heading,intro,blocks:[idx]}] }.
  function buildWordReportHTML(turnTag, plan, cards) {
    const sections = Array.isArray(plan.sections) ? plan.sections : [];
    const used = new Set();
    const title = (plan.title || "经营分析报表").trim();
    const now = new Date();
    const dateCN = now.getFullYear() + " 年 " + (now.getMonth() + 1)
      + " 月 " + now.getDate() + " 日";
    const PB = '<br clear="all" '
      + 'style="mso-special-character:line-break;page-break-before:always">';

    // --- 目录 rows ---
    const tocRows = [];
    let tno = 0;
    if (plan.summary) {
      tno += 1;
      tocRows.push('<tr><td class="toc-no">' + tno
        + '</td><td class="toc-txt">执行摘要</td></tr>');
    }
    sections.forEach((s) => {
      tno += 1;
      tocRows.push('<tr><td class="toc-no">' + tno + '</td><td class="toc-txt">'
        + esc((s.heading || "").trim()) + '</td></tr>');
    });

    // --- 正文 ---
    const body = [];
    if (plan.summary) {
      body.push('<h1 class="sec-h1">执行摘要</h1>');
      body.push('<div class="sec-summary">' + esc(plan.summary) + '</div>');
    }
    sections.forEach((s) => {
      body.push('<h1 class="sec-h1">' + esc((s.heading || "").trim()) + '</h1>');
      if (s.intro) body.push('<p class="sec-intro">' + esc(s.intro) + '</p>');
      (Array.isArray(s.blocks) ? s.blocks : []).forEach((raw) => {
        const bi = Number(raw);
        const card = cards[bi];
        if (!card || used.has(bi)) return;
        used.add(bi);
        body.push(renderCardForExport(card));
      });
    });
    const leftover = cards
      .map((c, i) => (used.has(i) ? "" : renderCardForExport(c)))
      .filter(Boolean);
    if (leftover.length) {
      body.push('<h1 class="sec-h1">附:其他内容</h1>');
      body.push(leftover.join("\n"));
    }

    return [
      '<html xmlns:o="urn:schemas-microsoft-com:office:office"',
      '      xmlns:w="urn:schemas-microsoft-com:office:word"',
      '      xmlns="http://www.w3.org/TR/REC-html40">',
      '<head>',
      '<meta charset="utf-8">',
      '<title>' + esc(title) + '</title>',
      '<style>',
      '@page { size: 21cm 29.7cm; margin: 2.5cm 2.3cm; }',
      '* { box-sizing: border-box; }',
      'body { font-family: "SimSun","宋体",serif; font-size: 12pt; color: #1a1a1a; line-height: 1.7; margin: 0; }',
      'p { margin: 0 0 8pt; }',
      '.cover { text-align: center; padding-top: 4.6cm; }',
      '.cover-cat { font-family: "Microsoft YaHei",sans-serif; font-size: 14pt; letter-spacing: 8pt; color: #1f5fa8; margin-bottom: 2cm; }',
      '.cover-title { font-family: "Microsoft YaHei",sans-serif; font-size: 30pt; font-weight: 700; color: #11233f; line-height: 1.4; margin: 0 1cm; }',
      '.cover-rule { width: 30%; border: 0; border-top: 3px solid #1f5fa8; margin: 0.8cm auto 1.5cm; }',
      '.cover-meta { margin: 0 auto; border-collapse: collapse; font-family: "Microsoft YaHei",sans-serif; font-size: 11pt; }',
      '.cover-meta td { padding: 5pt 14pt; color: #333; }',
      '.cover-meta .k { color: #8a8a8a; text-align: right; }',
      '.cover-conf { margin-top: 3.4cm; font-family: "Microsoft YaHei",sans-serif; font-size: 10.5pt; color: #b03030; letter-spacing: 3pt; }',
      '.doc-title-cn { font-family: "Microsoft YaHei",sans-serif; font-size: 19pt; font-weight: 700; color: #11233f; text-align: center; letter-spacing: 6pt; margin: 0 0 0.8cm; }',
      '.toc { width: 100%; border-collapse: collapse; font-family: "Microsoft YaHei",sans-serif; font-size: 11.5pt; }',
      '.toc td { padding: 9pt 4pt; border-bottom: 1px dotted #c4c4c4; }',
      '.toc-no { width: 1.6cm; color: #1f5fa8; font-weight: 700; }',
      '.toc-txt { color: #222; }',
      '.sec-h1 { font-family: "Microsoft YaHei",sans-serif; font-size: 15pt; font-weight: 700; color: #11233f; border-left: 5px solid #1f5fa8; padding-left: 10pt; margin: 22pt 0 10pt; }',
      '.sec-intro { color: #444; margin: 0 0 10pt; text-indent: 2em; }',
      '.sec-summary { padding: 12pt 16pt; background: #f4f7fb; border: 1px solid #d6e1ee; line-height: 1.85; text-indent: 2em; }',
      '.report-section { margin: 12pt 0 16pt; }',
      '.report-section header { margin-bottom: 5pt; }',
      '.report-tag { font-family: "Microsoft YaHei",sans-serif; font-size: 9pt; color: #9aa0a6; margin-right: 6pt; }',
      '.report-title { font-family: "Microsoft YaHei",sans-serif; font-size: 11.5pt; font-weight: 700; color: #1f5fa8; }',
      '.report-source { font-size: 9pt; color: #9aa0a6; margin-top: 4pt; }',
      '.report-body { white-space: pre-wrap; line-height: 1.85; }',
      '.report-chart { text-align: center; }',
      '.report-chart img { max-width: 100%; height: auto; border: 1px solid #dadada; }',
      '.report-empty { color: #9aa0a6; font-size: 9pt; padding: 10pt; border: 1px dashed #ccc; text-align: center; }',
      '.report-table-wrap table { width: 100%; border-collapse: collapse; font-family: "Microsoft YaHei",sans-serif; font-size: 10pt; margin: 4pt 0; }',
      '.report-table-wrap th, .report-table-wrap td { border: 1px solid #b9c4d2; padding: 5pt 8pt; }',
      '.report-table-wrap thead th { background: #1f5fa8; color: #fff; font-weight: 700; }',
      '.report-table-wrap tbody tr:nth-child(even) td { background: #eef3f9; }',
      '.doc-end { margin-top: 26pt; padding-top: 10pt; border-top: 2px solid #1f5fa8; text-align: center; font-family: "Microsoft YaHei",sans-serif; font-size: 9.5pt; color: #8a8a8a; }',
      '</style>',
      '</head>',
      '<body>',
      '<div class="cover">',
      '  <div class="cover-cat">经营分析报告</div>',
      '  <div class="cover-title">' + esc(title) + '</div>',
      '  <hr class="cover-rule">',
      '  <table class="cover-meta">',
      '    <tr><td class="k">生成日期</td><td>' + dateCN + '</td></tr>',
      '    <tr><td class="k">生成方式</td><td>BI 智能报表生成</td></tr>',
      '    <tr><td class="k">报表编号</td><td>RPT-' + esc(String(turnTag)) + '</td></tr>',
      '  </table>',
      '  <div class="cover-conf">内部资料 · 注意保密</div>',
      '</div>',
      PB,
      '<div class="doc-title-cn">目 录</div>',
      '<table class="toc">' + tocRows.join("") + '</table>',
      PB,
      body.join("\n"),
      '<div class="doc-end">—— 报表结束 ——<br>本报表由 BI 智能报表生成助手自动生成,数据以系统取数为准</div>',
      '</body>',
      '</html>',
    ].join("\n");
  }

  function downloadDoc(turnTag, html) {
    const blob = new Blob(["﻿", html], {
      type: "application/msword;charset=utf-8",
    });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "report-turn" + String(turnTag) + ".doc";
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 60_000);
  }

  // Composed Word docs, kept in memory (keyed by turnTag) until download.
  const rgWordDocs = {};

  // The Word button is two-stage:
  //   ① click「📄 导出 Word」  → one LLM call composes the report document
  //   ② click「⬇ 下载 Word 文档」→ downloads the composed .doc
  async function handleWordButton(turnTag, btn) {
    const exportCard = btn.closest(".dash-export");
    // Stage ② — already composed: this click just downloads.
    if (btn.dataset.state === "ready") {
      if (rgWordDocs[turnTag]) downloadDoc(turnTag, rgWordDocs[turnTag]);
      return;
    }
    // Stage ① — compose via the LLM.
    const cards = turnCards(turnTag);
    if (!cards.length) {
      alert("本轮没有可导出的看板内容。");
      return;
    }
    const blocks = cards.map((card, idx) => ({
      idx: idx,
      kind: cardExportKind(card),
      title: cardExportTitle(card),
      content: cardExportText(card),
    }));
    btn.disabled = true;
    btn.textContent = "⏳ 整合中…";
    setExportStatus(exportCard, "正在调用大模型整合报表文档…");
    let plan = null;
    let errMsg = "";
    try {
      const resp = await fetch("/api/report/compose", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ blocks: blocks }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        throw new Error(err.detail || "compose failed");
      }
      plan = await resp.json();
    } catch (e) {
      errMsg = e.message || String(e);
    }
    btn.disabled = false;
    if (plan && Array.isArray(plan.sections) && plan.sections.length) {
      rgWordDocs[turnTag] = buildWordReportHTML(turnTag, plan, cards);
      btn.dataset.state = "ready";
      btn.textContent = "⬇ 下载 Word 文档";
      setExportStatus(exportCard, "✓ 报表文档已整合完成,点击「下载 Word 文档」保存");
    } else {
      btn.textContent = "📄 导出 Word";
      setExportStatus(exportCard, "整合失败:" + errMsg + " —— 可点击重试", true);
    }
  }

  function clearDashboard() {
    const bucket = B();
    el.dashboardList.innerHTML = "";
    bucket.dashboardHasContent = false;
    bucket.conclusionSeen = new Set();
    bucket.rootCauseSeen = new Set();
    bucket.actionsSeen = new Set();
    if (el.dashboardEmpty) {
      if (!el.dashboardEmpty.parentNode) el.dashboardList.appendChild(el.dashboardEmpty);
      el.dashboardEmpty.style.display = "";
    }
    updateDashboardCount();
  }

  // ------------------------------------------------------------------
  // Ontology tab
  // ------------------------------------------------------------------
  function upsertOntologyEntities(entities) {
    if (!entities || entities.length === 0) return;
    const bucket = B();
    let added = false;
    for (const entity of entities) {
      if (bucket.ontologyByCode.has(entity.code)) continue;
      bucket.ontologyByCode.set(entity.code, entity);
      added = true;
      el.ontologyList.appendChild(buildEntityCard(entity));
    }
    if (added) el.countOntology.textContent = bucket.ontologyByCode.size;
  }

  function buildEntityCard(entity) {
    const card = el_h("div", `entity-card ${entity.kind}`);
    card.dataset.code = entity.code;
    const kindLabel = KIND_LABELS[entity.kind] || entity.kind.toUpperCase();
    card.innerHTML = `
      <div class="entity-head">
        <span class="entity-kind-tag">${esc(kindLabel)}</span>
        <span class="entity-code">${esc(entity.code)}</span>
        <span class="entity-name">${esc(entity.name || "")}</span>
        <span class="entity-chevron">›</span>
      </div>
      <div class="entity-body">${esc(entity.display || "")}</div>`;
    card.querySelector(".entity-head").addEventListener("click", () => card.classList.toggle("open"));
    return card;
  }

  el.chatScroll.addEventListener("click", (e) => {
    const ref = e.target.closest(".entity-ref");
    if (!ref) return;
    flashOntologyEntity(ref.dataset.code);
  });

  function flashOntologyEntity(code) {
    showView("ontology");  // 本体内容 is now a standalone page
    const card = el.ontologyList.querySelector(`.entity-card[data-code="${CSS.escape(code)}"]`);
    if (card) {
      card.classList.add("open");
      card.scrollIntoView({ behavior: "smooth", block: "center" });
      card.style.transition = "background 0.3s";
      card.style.background = "rgba(26, 115, 232, 0.15)";
      setTimeout(() => { card.style.background = ""; }, 600);
    }
  }

  // ------------------------------------------------------------------
  // Tool-call tab
  // ------------------------------------------------------------------
  function recordToolCall(record) {
    const bucket = B();
    bucket.toolCalls.push(record);
    el.countTools.textContent = bucket.toolCalls.length;
    el.toolList.appendChild(buildToolCard(record, bucket.toolCalls.length));
  }

  function buildToolCard(r, idx) {
    const card = el_h("div", "tool-card");
    const preview = toolPreview(r.name, r.input);
    const chips = (r.ontology_entities || []).map(e => buildChipHTML(e)).join("");
    card.innerHTML = `
      <div class="tool-head">
        <span class="tool-idx">#${idx}</span>
        <span class="tool-name">${esc(r.name)}</span>
        <span class="tool-preview">${esc(preview)}</span>
        <span class="tool-duration">${fmtDuration(r.duration_ms)}</span>
      </div>
      <div class="tool-body">
        <div class="kv-block">
          <div class="kv-label">输入</div>
          <pre>${esc(JSON.stringify(r.input || {}, null, 2))}</pre>
        </div>
        <div class="kv-block">
          <div class="kv-label">输出</div>
          <pre>${esc(r.output || "")}</pre>
        </div>
        ${chips ? `<div class="kv-block">
          <div class="kv-label">命中的本体实体</div>
          <div class="chip-row">${chips}</div>
        </div>` : ""}
      </div>`;
    card.querySelector(".tool-head").addEventListener("click", () => card.classList.toggle("open"));
    card.querySelectorAll(".chip").forEach(ch => {
      ch.addEventListener("click", () => flashOntologyEntity(ch.dataset.code));
    });
    return card;
  }

  function buildChipHTML(entity) {
    const kindLabel = KIND_LABELS[entity.kind] || entity.kind.toUpperCase();
    return `<span class="chip ${esc(entity.kind)}" data-code="${esc(entity.code)}" title="${esc(kindLabel)} — ${esc(entity.name || "")}">
      <span class="chip-kind"></span>
      <span class="chip-code">${esc(entity.code)}</span>
      <span class="chip-name">${esc(entity.name || "")}</span>
    </span>`;
  }

  function buildChatStep(r) {
    const step = el_h("div", "step");
    const preview = toolPreview(r.name, r.input);
    const chips = (r.ontology_entities || []).map(e => buildChipHTML(e)).join("");
    step.innerHTML = `
      <div class="step-header">
        <span class="step-icon">▸</span>
        <span class="step-name">${esc(r.name)}</span>
        <span class="step-summary">${esc(preview)}</span>
        <span class="step-duration">${fmtDuration(r.duration_ms)}</span>
      </div>
      <div class="step-body">
        <div class="step-sub">输入</div>
        <pre>${esc(JSON.stringify(r.input || {}, null, 2))}</pre>
        <div class="step-sub">输出</div>
        <pre>${esc(r.output || "")}</pre>
        ${chips ? `<div class="step-sub">命中的本体</div><div class="chip-row">${chips}</div>` : ""}
      </div>`;
    step.querySelector(".step-header").addEventListener("click", () => step.classList.toggle("open"));
    step.querySelectorAll(".chip").forEach(ch => {
      ch.addEventListener("click", (ev) => { ev.stopPropagation(); flashOntologyEntity(ch.dataset.code); });
    });
    return step;
  }

  // ------------------------------------------------------------------
  // LLM I/O tab
  // ------------------------------------------------------------------
  function newLlmTurn(req) {
    const bucket = B();
    const idx = bucket.llmTurns.length;
    const turn = { iteration: req.iteration, request: req, response: null };
    bucket.llmTurns.push(turn);
    el.countLlm.textContent = bucket.llmTurns.length;
    const card = buildLlmCard(turn, idx);
    el.llmList.appendChild(card);
    return card;
  }

  function fillLlmResponse(iteration, resp) {
    const bucket = B();
    for (let i = bucket.llmTurns.length - 1; i >= 0; i--) {
      if (bucket.llmTurns[i].iteration === iteration && !bucket.llmTurns[i].response) {
        bucket.llmTurns[i].response = resp;
        const cards = el.llmList.querySelectorAll(".llm-card");
        if (cards[i]) cards[i].replaceWith(buildLlmCard(bucket.llmTurns[i], i));
        return;
      }
    }
  }

  function buildLlmCard(turn, idx) {
    const { iteration, request, response } = turn;
    const tokenInfo = response && response.usage
      ? `输出 ${response.usage.output_tokens || 0} tokens`
      : "…";
    const stopR = response && response.stop_reason ? response.stop_reason : "…";
    const nTools = response && response.tool_uses ? response.tool_uses.length : 0;
    const summary = nTools
      ? `${response.text ? "text+" : ""}${nTools} tool_use · stop=${stopR}`
      : (response && response.text ? `text · stop=${stopR}` : "流式中…");

    const card = el_h("div", "llm-card");
    card.innerHTML = `
      <div class="llm-head">
        <span class="iter">请求 #${idx + 1} · 迭代 ${iteration}</span>
        <span class="summary">${esc(summary)}</span>
        <span class="usage">${esc(tokenInfo)}</span>
      </div>
      <div class="llm-body">
        <div class="kv-label">请求消息 (${request.message_count})</div>
        ${renderMessages(request.messages_snapshot || [])}
        <div class="kv-label" style="margin-top: 12px;">响应</div>
        ${response ? renderResponse(response) : '<div class="msg-block">流式中…</div>'}
      </div>`;
    card.querySelector(".llm-head").addEventListener("click", () => card.classList.toggle("open"));
    return card;
  }

  function renderMessages(messages) {
    if (!messages || !messages.length) return '<div class="msg-block">(空)</div>';
    return messages.map((m) => {
      const blocks = [];
      if (typeof m.content === "string") {
        blocks.push(`<div class="msg-block role-${esc(m.role)}">
          <span class="block-label">${esc(m.role)} — text</span>${esc(m.content)}</div>`);
      } else {
        for (const b of (m.content || [])) {
          if (b.type === "text") {
            blocks.push(`<div class="msg-block role-${esc(m.role)}">
              <span class="block-label">${esc(m.role)} — text</span>${esc(b.text || "")}</div>`);
          } else if (b.type === "tool_use") {
            blocks.push(`<div class="msg-block role-${esc(m.role)}">
              <span class="block-label">${esc(m.role)} — tool_use ${esc(b.name)}</span>${esc(JSON.stringify(b.input || {}, null, 2))}</div>`);
          } else if (b.type === "tool_result") {
            blocks.push(`<div class="msg-block role-${esc(m.role)}">
              <span class="block-label">${esc(m.role)} — tool_result</span>${esc(b.content_preview || "")}</div>`);
          } else {
            blocks.push(`<div class="msg-block role-${esc(m.role)}">
              <span class="block-label">${esc(m.role)} — ${esc(b.type || "?")}</span></div>`);
          }
        }
      }
      return blocks.join("");
    }).join("");
  }

  function renderResponse(resp) {
    const parts = [];
    if (resp.text) {
      parts.push(`<div class="msg-block role-assistant">
        <span class="block-label">assistant — text</span>${esc(resp.text)}</div>`);
    }
    for (const tu of (resp.tool_uses || [])) {
      parts.push(`<div class="msg-block role-assistant">
        <span class="block-label">assistant — tool_use ${esc(tu.name)}</span>${esc(JSON.stringify(tu.input || {}, null, 2))}</div>`);
    }
    return parts.join("") || '<div class="msg-block">(空)</div>';
  }

  // ------------------------------------------------------------------
  // SSE dispatch
  // ------------------------------------------------------------------
  function onEvent(evt) {
    switch (evt.type) {
      case "user_message":
        break;
      case "iteration_start":
        startAssistantMessage(evt.iteration);
        break;
      case "llm_request":
        newLlmTurn(evt);
        break;
      case "text_delta":
        appendAssistantDelta(evt.text);
        break;
      case "tool_start":
      case "tool_input":
        break;
      case "tool_result": {
        const record = {
          id: evt.id,
          name: evt.name,
          input: evt.input,
          output: evt.output,
          duration_ms: evt.duration_ms,
          ontology_entities: evt.ontology_entities,
          chart: evt.chart || null,
          table: evt.table || null,
          multi_chart: evt.multi_chart || null,
        };
        recordToolCall(record);
        attachChatStep(buildChatStep(record));
        // Advance the pinned SOP checklist based on which tool just ran.
        advanceSopForTool(record.name);
        if (record.chart) {
          attachChatChart(record.chart);
          pushChartToDashboard(record.chart);
        }
        if (record.table) {
          attachChatTable(record.table);
          pushTableToDashboard(record.table);
        }
        if (record.multi_chart) {
          attachChatMultiChart(record.multi_chart);
          pushMultiChartToDashboard(record.multi_chart);
        }
        upsertOntologyEntities(evt.ontology_entities);
        break;
      }
      case "user_choice_requested":
        attachChoiceCard(evt);
        setBusy(false);
        break;
      case "user_choice_resolved":
        markChoiceResolved(evt.tool_use_id, evt.choice_labels || evt.choice_label);
        setBusy(true);
        break;
      case "awaiting_user_choice":
        break;
      case "llm_response":
        finalizeAssistantText();
        fillLlmResponse(evt.iteration, {
          text: evt.text,
          tool_uses: evt.tool_uses,
          stop_reason: evt.stop_reason,
          usage: evt.usage,
        });
        if (evt.text) {
          // 📌结论 / 🔍根因 / 💡建议 may land in the SAME message or be split
          // across separate iterations. Extract each INDEPENDENTLY on its own
          // marker — never gate 根因/建议 on 📌 being in the same message.
          // (The old `if (text.includes("📌"))` gate dropped the L2/L3 cards
          //  whenever the model emitted 📌结论 and 🔍根因/💡建议 separately.)
          // All three pushes are idempotent no-ops without their marker.
          pushConclusionIfAny(evt.text);
          pushRootCauseIfAny(evt.text);
          pushActionsIfAny(evt.text);
          // Advance the SOP checklist: 深度分析 markers → step ⑤, 📌结论 → 交付.
          advanceSopForText(evt.text);
          // Remember this turn delivered a 📌 结论 — used at turn end to
          // reconcile the checklist to 100% (handles L1 turns that skip 深度分析).
          if (evt.text.includes("📌")) B().concludedTurnTag = B().currentTurnTag || 1;
          // Quadrant-assistant: detect any ```ui-command``` blocks and STAGE
          // them on the pending queue. The user clicks an "执行" button at
          // end-of-turn to actually apply them to the cockpit.
          if (state.quadrant) {
            const cmds = extractUiCommands(evt.text);
            if (cmds.length) stageUiCommands(cmds);
          }
        }
        break;
      case "render_enforce": {
        finalizeAssistantText();
        const reasons = (evt.reasons || []).join(" / ") || "缺少表格 / 图表卡片";
        const tip = el_h("div", "msg msg-system msg-enforce",
          `<div class="msg-header"><span class="msg-role" style="color: var(--accent-amber,#ff6d00); border-color: var(--accent-amber,#ff6d00);">SYSTEM · 强制渲染</span></div>
           <div class="msg-body" style="color: var(--fg-1); border-left: 2px solid var(--accent-amber,#ff6d00); padding-left: 10px;">
             检测到本轮${esc(reasons)}却未调用渲染工具,已注入提醒,要求模型补一次 <code>TableGenerate</code>(必要时再加 <code>ChartGenerate</code>)。
           </div>`);
        el.chatScroll.appendChild(tip);
        el.chatScroll.scrollTop = el.chatScroll.scrollHeight;
        break;
      }
      case "done": {
        setBusy(false);
        const _bk = B();
        const _tag = _bk.currentTurnTag || 1;
        // Tables produced this turn stay on the dashboard regardless of level —
        // the L1 template (6.2) itself requires TableGenerate, so 取数 tables
        // must map to the 看板 just like charts/conclusions do.
        // If this turn delivered a 📌 结论, reconcile the pinned task list to
        // 100% so it never dangles at ◔ 进行中 after the answer is out.
        if (_bk.concludedTurnTag === _tag) reconcileTodosOnConclusion();
        appendTurnExportButton(_tag);
        // Quadrant-assistant: if any ui-commands were staged this turn,
        // render the "执行" card so the user can apply them in one click.
        if (state.quadrant) appendApplyButton(_tag);
        // Persist this conversation to the restorable 「最近」history (updates
        // the same record in place via bucket.convId).
        saveCurrentConversation();
        break;
      }
      case "error":
        finalizeAssistantText();
        const errEl = el_h("div", "msg msg-error",
          `<div class="msg-header"><span class="msg-role" style="color: var(--accent-red); border-color: var(--accent-red);">ERROR</span></div>
           <div class="msg-body" style="color: var(--accent-red);">${esc(evt.message || "unknown")}</div>`);
        el.chatScroll.appendChild(errEl);
        setBusy(false);
        break;
      default:
        console.warn("unknown event", evt);
    }
  }

  // ------------------------------------------------------------------
  // Fetch + stream
  // ------------------------------------------------------------------
  async function sendMessage(text) {
    if (state.busy || !text.trim()) return;
    // Gate report-mode sends until a report has been activated
    if (state.mode === "report" && !state.report.sessionActivated) {
      uploadStatus("请先上传或选择一份报表", "error");
      return;
    }
    setBusy(true);
    // Bump per-turn tag so dashboard cards group by user turn
    B().currentTurnTag = (B().currentTurnTag || 0) + 1;
    const _bk = B();
    _bk.turnQuestions = _bk.turnQuestions || {};
    _bk.turnQuestions[_bk.currentTurnTag] = text;
    // Seed a fresh SOP task checklist for this turn (BI data mode only).
    if (state.mode === "data") initSopTodos();
    addUserMessage(text);
    // Keep the right-hand dashboard readable as a complete mini-report:
    // every turn starts with the user's question, followed by its conclusion,
    // tables and charts as they arrive.
    appendDashboardCard(dashboardQuestionCard(text, _bk.currentTurnTag));

    // In quadrant-assistant mode, prepend a hidden system-style instruction so
    // the LLM knows which quadrant it is editing and what command vocabulary
    // it may emit. The user sees only their original text.
    const quadPrefix = buildQuadrantSystemPrefix();
    const payloadText = quadPrefix ? `${quadPrefix}\n\n用户问: ${text}` : text;

    const url = state.mode === "report" ? "/api/report/chat" : "/api/chat";
    let resp;
    try {
      activeRequestController = new AbortController();
      resp = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: payloadText }),
        signal: activeRequestController.signal,
      });
    } catch (err) {
      if (err && err.name === "AbortError") return;
      onEvent({ type: "error", message: `request failed: ${err.message || err}` });
      setBusy(false);
      return;
    }
    if (!resp.ok || !resp.body) {
      const errText = await resp.text().catch(() => resp.statusText);
      onEvent({ type: "error", message: `HTTP ${resp.status}: ${errText}` });
      setBusy(false);
      return;
    }
    await streamResponse(resp);
    activeRequestController = null;
  }

  async function streamResponse(resp) {
    const reader = resp.body.getReader();
    const dec = new TextDecoder("utf-8");
    let buf = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) !== -1) {
        const chunk = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        for (const line of chunk.split("\n")) {
          if (line.startsWith("data:")) {
            const payload = line.slice(5).trim();
            if (!payload) continue;
            try {
              onEvent(JSON.parse(payload));
            } catch (e) { console.warn("bad json", payload); }
          }
        }
      }
    }
  }

  function setBusy(v) {
    state.busy = v;
    el.btnSend.disabled = v;
    el.chatInput.disabled = v;
    el.btnSend.textContent = v ? "…" : "发送 ▸";
    // Navigation remains available while a turn is in flight.
  }

  // ------------------------------------------------------------------
  // Mode switch
  // ------------------------------------------------------------------
  function detachChildren(container) {
    const nodes = Array.from(container.childNodes);
    for (const n of nodes) container.removeChild(n);
    return nodes;
  }

  function attachChildren(container, nodes) {
    for (const n of nodes) container.appendChild(n);
  }

  function switchMode(newMode) {
    if (newMode === state.mode) return;
    if (state.busy) {
      if (activeRequestController) activeRequestController.abort();
      const resetUrl = state.mode === "report" ? "/api/report/session/reset" : "/api/session/reset";
      fetch(resetUrl, { method: "POST" }).catch(() => {});
      setBusy(false);
    }
    // Quadrant assistants are locked to a single mode; only the initial
    // lock-in (from applyQuadrantFromUrl) may set it.
    if (state.lockedMode && newMode !== state.lockedMode) return;

    // Stash outgoing mode's DOM (snapshot of current containers)
    const out = buckets[state.mode];
    out.chatNodes      = detachChildren(el.chatScroll);
    out.ontologyNodes  = detachChildren(el.ontologyList);
    out.toolNodes      = detachChildren(el.toolList);
    out.llmNodes       = detachChildren(el.llmList);
    if (el.dashboardList) {
      out.dashboardNodes = detachChildren(el.dashboardList)
        .filter(n => !(n === el.dashboardEmpty));
    }

    state.mode = newMode;
    document.body.dataset.mode = newMode;
    el.modeBtns.forEach(b => b.classList.toggle("active", b.dataset.mode === newMode));

    // Attach incoming mode's DOM
    const inc = buckets[newMode];
    if (inc.chatNodes.length) {
      attachChildren(el.chatScroll, inc.chatNodes);
    } else {
      // Fresh — reattach the persistent empty-state element
      if (!el.chatEmpty.parentNode) el.chatScroll.appendChild(el.chatEmpty);
    }
    attachChildren(el.ontologyList, inc.ontologyNodes);
    attachChildren(el.toolList,     inc.toolNodes);
    attachChildren(el.llmList,      inc.llmNodes);
    renderTodoPanel();  // show the incoming mode's task list (or hide if none)
    if (el.dashboardList) {
      if (inc.dashboardNodes && inc.dashboardNodes.length) {
        attachChildren(el.dashboardList, inc.dashboardNodes);
        if (el.dashboardEmpty) el.dashboardEmpty.style.display = "none";
      } else {
        if (el.dashboardEmpty) {
          if (!el.dashboardEmpty.parentNode) el.dashboardList.appendChild(el.dashboardEmpty);
          el.dashboardEmpty.style.display = "";
        }
      }
    }

    // Counters
    el.countOntology.textContent = inc.ontologyByCode.size;
    el.countTools.textContent    = inc.toolCalls.length;
    el.countLlm.textContent      = inc.llmTurns.length;
    if (el.dashboardCount) el.dashboardCount.textContent = (inc.dashboardNodes || []).length;
    updateTurnCounter();

    // Empty-state & topbar
    renderEmptyState();
    if (el.chatEmpty) el.chatEmpty.style.display = inc.hasContent ? "none" : "";
    renderTopbarMeta();
    renderReportControls();
    updateChatInputAvailability();
    updateSendPlaceholder();

    // System panel is mode-specific — lazy-load next time it's opened
    if (state.activeTab === "system") loadSystemPrompt();

    // 最近 list is per-mode — refresh for the incoming mode
    if (typeof loadRecent === "function") loadRecent();
  }

  el.modeBtns.forEach(b => {
    b.addEventListener("click", () => switchMode(b.dataset.mode));
  });

  function updateChatInputAvailability() {
    if (state.busy) return;
    const blocked = state.mode === "report" && !state.report.sessionActivated;
    el.chatInput.disabled = blocked;
    el.btnSend.disabled = blocked;
  }

  function updateSendPlaceholder() {
    if (state.mode === "report") {
      if (!state.report.sessionActivated) {
        el.chatInput.placeholder = "请先上传或激活报表(可多选)...";
      } else {
        const recs = state.report.activeReports || [];
        const n = recs.length;
        if (n === 0) {
          // Report-generation session — no uploaded report bound.
          el.chatInput.placeholder = "报表生成中,可继续补充生成要求...  (Enter 发送)";
        } else if (n <= 1) {
          el.chatInput.placeholder = `针对「${recs[0]?.filename || state.report.activeReport?.filename || "报表"}」提问...  (Enter 发送 · Shift+Enter 换行)`;
        } else {
          el.chatInput.placeholder = `针对 ${n} 份报表(${recs[0].filename} 等)提问...  (Enter 发送 · Shift+Enter 换行)`;
        }
      }
    } else {
      el.chatInput.placeholder = "提问...  (Enter 发送 · Shift+Enter 换行)";
    }
  }

  // ------------------------------------------------------------------
  // Report mode: upload, history, activation, toggle
  // ------------------------------------------------------------------
  function uploadStatus(msg, kind = "info") {
    el.uploadStatus.textContent = msg || "";
    el.uploadStatus.className = "upload-status " + (msg ? kind : "");
  }

  async function refreshReportStatus() {
    try {
      const r = await fetch("/api/report/status");
      const data = await r.json();
      const list = Array.isArray(data.active_reports)
        ? data.active_reports
        : (data.active_report ? [data.active_report] : []);
      state.report.activeReports = list;
      state.report.activeReport = list[0] || null;
      state.report.withDb = !!data.with_db;
      state.report.sessionActivated = !!data.has_session && list.length > 0;
      renderReportControls();
    } catch (e) {
      console.warn("report status load failed", e);
    }
  }

  async function refreshReportHistory() {
    try {
      const r = await fetch("/api/report/list");
      const data = await r.json();
      state.report.history = data.items || [];
      el.historyCount.textContent = state.report.history.length;
      renderHistoryList();
    } catch (e) {
      console.warn("report history load failed", e);
    }
  }

  function renderReportControls() {
    const recs = state.report.activeReports || [];
    const first = recs[0] || null;
    state.report.activeReport = first;
    // Attach-chip only makes sense in report mode with at least one active report
    const chipVisible = state.mode === "report" && !!first;
    if (el.attachRow) el.attachRow.hidden = !chipVisible;
    if (chipVisible) {
      const more = recs.length > 1 ? `  +${recs.length - 1}` : "";
      el.attachChipName.textContent = (first.filename || "(未命名)") + more;
      const parts = recs.length > 1
        ? [`${recs.length} 份报表`, `共 ${recs.reduce((a, r) => a + (r.page_count || 0), 0)} 页`,
           `${recs.reduce((a, r) => a + (r.tables_count || 0), 0)} 表格`]
        : [
            first.ext?.replace(".", "").toUpperCase() || "",
            `${first.page_count || 0} 页`,
            `${first.tables_count || 0} 表格`,
            `${fmtBytes(first.size_bytes || first.text_length || 0)}`,
            fmtDate(first.uploaded_at),
          ];
      el.attachChipMeta.textContent = parts.filter(Boolean).join(" · ");
      // Tooltip lists every active filename
      const titleLines = recs.map((r, i) => `${i + 1}. ${r.filename}`).join("\n");
      if (el.attachChipName.parentElement) el.attachChipName.parentElement.title = titleLines;
    }
    if (el.withDb) el.withDb.checked = !!state.report.withDb;
    updateChatInputAvailability();
    updateSendPlaceholder();
  }

  const MAX_ACTIVE_REPORTS = 5;

  function activeIdSet() {
    return new Set((state.report.activeReports || []).map(r => r.id));
  }

  function renderHistoryList() {
    const items = state.report.history;
    if (!items.length) {
      el.historyList.innerHTML = '<div class="history-empty">暂无上传记录</div>';
      updateHistoryToolbar();
      return;
    }
    const activeIds = activeIdSet();
    const sel = state.report.historySelectedIds;
    el.historyList.innerHTML = items.map(it => {
      const meta = [
        (it.ext || "").replace(".", "").toUpperCase(),
        `${it.page_count || 0}页`,
        `${it.tables_count || 0}表`,
        fmtBytes(it.size_bytes || 0),
        fmtDate(it.uploaded_at),
      ].filter(Boolean).join(" · ");
      const isActive = activeIds.has(it.id);
      const isChecked = sel.has(it.id);
      return `
        <div class="history-item ${isActive ? 'active' : ''}" data-id="${esc(it.id)}">
          <label class="history-item-check">
            <input type="checkbox" class="history-checkbox" data-id="${esc(it.id)}"
                   ${isChecked ? 'checked' : ''} />
          </label>
          <div class="history-item-main">
            <div class="history-item-name">
              ${esc(it.filename || "(未命名)")}
              ${isActive ? '<span class="history-item-badge">使用中</span>' : ''}
            </div>
            <div class="history-item-meta">${esc(meta)}</div>
            ${it.preview ? `<div class="history-item-preview">${esc(it.preview)}</div>` : ""}
          </div>
          <div class="history-item-actions">
            <button class="btn btn-ghost history-use" data-id="${esc(it.id)}"
                    title="单独激活该报表(替换当前选择)">仅用此份</button>
            <button class="btn btn-ghost history-del" data-id="${esc(it.id)}" title="删除">✕</button>
          </div>
        </div>`;
    }).join("");
    el.historyList.querySelectorAll(".history-checkbox").forEach(cb => {
      cb.addEventListener("change", () => {
        const id = cb.dataset.id;
        if (cb.checked) {
          if (sel.size >= MAX_ACTIVE_REPORTS) {
            cb.checked = false;
            uploadStatus(`最多只能选择 ${MAX_ACTIVE_REPORTS} 份报表`, "error");
            setTimeout(() => uploadStatus(""), 2000);
            return;
          }
          sel.add(id);
        } else {
          sel.delete(id);
        }
        updateHistoryToolbar();
      });
    });
    el.historyList.querySelectorAll(".history-use").forEach(b => {
      b.addEventListener("click", () => activateReports([b.dataset.id]));
    });
    el.historyList.querySelectorAll(".history-del").forEach(b => {
      b.addEventListener("click", () => deleteReport(b.dataset.id));
    });
    updateHistoryToolbar();
  }

  function updateHistoryToolbar() {
    const n = state.report.historySelectedIds.size;
    if (el.historySelectedCount) {
      el.historySelectedCount.textContent = `已选 ${n} 份`;
    }
    if (el.historyActivateSel) {
      el.historyActivateSel.disabled = (n === 0) || state.busy;
    }
  }

  async function activateReports(ids) {
    if (state.busy) return;
    if (!Array.isArray(ids) || ids.length === 0) {
      uploadStatus("请至少选择一份报表", "error");
      return;
    }
    if (ids.length > MAX_ACTIVE_REPORTS) {
      uploadStatus(`最多只能选择 ${MAX_ACTIVE_REPORTS} 份报表`, "error");
      return;
    }
    uploadStatus(`正在激活 ${ids.length} 份报表…`, "pending");
    try {
      const r = await fetch("/api/report/activate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ report_ids: ids, with_db: !!state.report.withDb }),
      });
      if (!r.ok) throw new Error((await r.json()).detail || "activate failed");
      const data = await r.json();
      const list = Array.isArray(data.active_reports) ? data.active_reports
                  : (data.active_report ? [data.active_report] : []);
      state.report.activeReports = list;
      state.report.activeReport = list[0] || null;
      state.report.withDb = !!data.with_db;
      state.report.sessionActivated = list.length > 0;
      state.report.historySelectedIds.clear();
      renderReportControls();
      await refreshReportHistory();
      hideHistoryPopover();
      // Server just (re)created a fresh session — wipe local chat history
      clearBucketChat("report");
      const label = list.length === 1
        ? `已切换到「${list[0].filename}」`
        : `已激活 ${list.length} 份报表(${list[0].filename} 等)`;
      uploadStatus(label, "success");
      setTimeout(() => uploadStatus(""), 2000);
    } catch (e) {
      uploadStatus("激活失败: " + (e.message || e), "error");
    }
  }

  // Backward-compat alias for older call sites (e.g., upload completion).
  async function activateReport(rid) {
    return activateReports([rid]);
  }

  async function deleteReport(rid) {
    if (!confirm("确定删除该报表?该操作不可恢复。")) return;
    try {
      const r = await fetch(`/api/report/${encodeURIComponent(rid)}`, { method: "DELETE" });
      if (!r.ok) throw new Error("delete failed");
      // Drop from local active mirror; server already updated its side.
      const wasActive = (state.report.activeReports || []).some(x => x.id === rid);
      state.report.activeReports = (state.report.activeReports || []).filter(x => x.id !== rid);
      state.report.activeReport = state.report.activeReports[0] || null;
      if (wasActive && state.report.activeReports.length === 0) {
        state.report.sessionActivated = false;
        clearBucketChat("report");
      }
      state.report.historySelectedIds.delete(rid);
      await refreshReportHistory();
      renderReportControls();
    } catch (e) {
      uploadStatus("删除失败: " + (e.message || e), "error");
    }
  }

  function clearBucketChat(mode) {
    const bucket = buckets[mode];
    bucket.ontologyByCode.clear();
    bucket.toolCalls.length = 0;
    bucket.llmTurns.length = 0;
    bucket.turnCount = 0;
    bucket.systemPrompt = null;
    bucket.currentAssistantEl = null;
    bucket.currentAssistantText = "";
    bucket.chatNodes = [];
    bucket.ontologyNodes = [];
    bucket.toolNodes = [];
    bucket.llmNodes = [];
    bucket.dashboardNodes = [];
    bucket.hasContent = false;
    bucket.dashboardHasContent = false;
    bucket.conclusionSeen = new Set();
    bucket.rootCauseSeen = new Set();
    bucket.actionsSeen = new Set();
    bucket.currentTurnTag = 0;
    bucket.turnQuestions = {};
    bucket.questions = [];
    bucket.pendingCommands = [];
    bucket.todos = [];
    bucket.sopStep = 0;
    bucket.concludedTurnTag = 0;
    bucket.convId = null;   // detach from any saved 最近 record → next is fresh
    bucket.titleHint = null; // drop the restored-title anchor; next title is fresh
    // If this is the active mode, also clear visible DOM
    if (state.mode === mode) {
      renderTodoPanel();  // hides the pinned task list (bucket.todos now empty)
      detachChildren(el.chatScroll);
      detachChildren(el.ontologyList);
      detachChildren(el.toolList);
      detachChildren(el.llmList);
      if (el.dashboardList) detachChildren(el.dashboardList);
      if (el.dashboardEmpty) {
        el.dashboardList.appendChild(el.dashboardEmpty);
        el.dashboardEmpty.style.display = "";
      }
      if (el.chatEmpty && !el.chatEmpty.parentNode) el.chatScroll.appendChild(el.chatEmpty);
      if (el.chatEmpty) el.chatEmpty.style.display = "";
      el.countOntology.textContent = "0";
      el.countTools.textContent = "0";
      el.countLlm.textContent = "0";
      if (el.dashboardCount) el.dashboardCount.textContent = "0";
      updateTurnCounter();
    }
  }

  async function uploadOne(file) {
    const ext = file.name.toLowerCase().slice(file.name.lastIndexOf("."));
    if (ext !== ".pdf" && ext !== ".docx") {
      throw new Error(`不支持的文件类型 ${ext},仅支持 .pdf / .docx`);
    }
    if (file.size > 50 * 1024 * 1024) {
      throw new Error("文件过大,上限 50MB");
    }
    const fd = new FormData();
    fd.append("file", file);
    const r = await fetch("/api/report/upload", { method: "POST", body: fd });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      throw new Error(err.detail || "upload failed");
    }
    return await r.json();  // ReportRecord
  }

  async function uploadFiles(files) {
    if (!files || !files.length) return;
    const list = Array.from(files);
    if (list.length > MAX_ACTIVE_REPORTS) {
      uploadStatus(`一次最多上传 ${MAX_ACTIVE_REPORTS} 份报表,已截取前 ${MAX_ACTIVE_REPORTS} 份`, "error");
      list.length = MAX_ACTIVE_REPORTS;
    }
    const newIds = [];
    const failures = [];
    for (let i = 0; i < list.length; i++) {
      const f = list[i];
      uploadStatus(`正在上传 (${i + 1}/${list.length})「${f.name}」…`, "pending");
      try {
        const rec = await uploadOne(f);
        newIds.push(rec.id);
      } catch (e) {
        failures.push(`${f.name}: ${e.message || e}`);
      }
    }
    await refreshReportHistory();
    if (failures.length && !newIds.length) {
      uploadStatus("全部上传失败:\n" + failures.join("\n"), "error");
      return;
    }
    if (failures.length) {
      uploadStatus(`部分失败 (${failures.length}/${list.length}),即将激活成功的 ${newIds.length} 份…`, "pending");
    } else {
      uploadStatus(`已上传 ${newIds.length} 份,正在激活…`, "pending");
    }
    if (newIds.length) await activateReports(newIds);
  }

  // Backward-compat single-file path (drag/drop with one file).
  async function uploadFile(file) {
    if (!file) return;
    return uploadFiles([file]);
  }

  // ------- Composer: attach button + drag/drop over the whole input area -------
  function triggerFilePicker() {
    if (el.fileInput) el.fileInput.click();
  }
  if (el.btnAttach) el.btnAttach.addEventListener("click", triggerFilePicker);
  if (el.attachChipChange) el.attachChipChange.addEventListener("click", triggerFilePicker);
  if (el.attachChipRemove) {
    el.attachChipRemove.addEventListener("click", async () => {
      const recs = state.report.activeReports || [];
      if (!recs.length) return;
      const label = recs.length === 1
        ? `从当前会话中移除「${recs[0].filename}」?`
        : `从当前会话中移除全部 ${recs.length} 份报表?`;
      if (!confirm(`${label}(文件仍保留在最近上传列表中,不会从服务器删除)`)) return;
      // Clear server session AND server-side active list
      try { await fetch("/api/report/session/reset", { method: "POST" }); } catch (e) {}
      state.report.activeReports = [];
      state.report.activeReport = null;
      state.report.sessionActivated = false;
      clearBucketChat("report");
      renderReportControls();
      uploadStatus("已移除当前报表", "success");
      setTimeout(() => uploadStatus(""), 1500);
    });
  }
  if (el.fileInput) {
    el.fileInput.addEventListener("change", () => {
      const files = el.fileInput.files;
      if (files && files.length) uploadFiles(files);
      el.fileInput.value = "";
    });
  }
  // Drag-and-drop over the composer — only accept files in report mode,
  // and keep the overlay driven by a reference counter so child drag events
  // don't flicker the highlight off and on.
  if (el.chatInputWrap) {
    let dragDepth = 0;
    const isFileDrag = (e) => {
      if (!e.dataTransfer) return false;
      const types = e.dataTransfer.types;
      if (!types) return false;
      for (let i = 0; i < types.length; i++) {
        if (types[i] === "Files") return true;
      }
      return false;
    };
    el.chatInputWrap.addEventListener("dragenter", (e) => {
      if (state.mode !== "report" || !isFileDrag(e)) return;
      e.preventDefault();
      dragDepth++;
      el.chatInputWrap.classList.add("drag-hover");
    });
    el.chatInputWrap.addEventListener("dragover", (e) => {
      if (state.mode !== "report" || !isFileDrag(e)) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "copy";
    });
    el.chatInputWrap.addEventListener("dragleave", (e) => {
      if (state.mode !== "report") return;
      dragDepth = Math.max(0, dragDepth - 1);
      if (dragDepth === 0) el.chatInputWrap.classList.remove("drag-hover");
    });
    el.chatInputWrap.addEventListener("drop", (e) => {
      if (state.mode !== "report") return;
      e.preventDefault();
      dragDepth = 0;
      el.chatInputWrap.classList.remove("drag-hover");
      const files = e.dataTransfer.files;
      if (files && files.length) uploadFiles(files);
    });
  }

  // ------- Checkbox: 启用数据库查询 -------
  if (el.withDb) {
    el.withDb.addEventListener("change", async () => {
      const flag = el.withDb.checked;
      if (!state.report.sessionActivated) {
        // No session yet; just stash locally, will be used on next activate
        state.report.withDb = flag;
        return;
      }
      try {
        const r = await fetch("/api/report/config", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ with_db: flag }),
        });
        if (!r.ok) throw new Error((await r.json()).detail || "config failed");
        state.report.withDb = flag;
        uploadStatus(flag ? "已启用数据库查询" : "已禁用数据库查询", "success");
        setTimeout(() => uploadStatus(""), 1500);
      } catch (e) {
        el.withDb.checked = !flag;
        uploadStatus("切换失败: " + (e.message || e), "error");
      }
    });
  }

  // ------- 最近报表 popover -------
  if (el.btnHistory) el.btnHistory.addEventListener("click", showHistoryPopover);
  if (el.historyClose) el.historyClose.addEventListener("click", hideHistoryPopover);
  if (el.historySelectAll) {
    el.historySelectAll.addEventListener("click", () => {
      const sel = state.report.historySelectedIds;
      sel.clear();
      const items = state.report.history || [];
      // Take up to MAX_ACTIVE_REPORTS most recent
      for (let i = 0; i < items.length && sel.size < MAX_ACTIVE_REPORTS; i++) {
        sel.add(items[i].id);
      }
      renderHistoryList();
    });
  }
  if (el.historyClearSel) {
    el.historyClearSel.addEventListener("click", () => {
      state.report.historySelectedIds.clear();
      renderHistoryList();
    });
  }
  if (el.historyActivateSel) {
    el.historyActivateSel.addEventListener("click", () => {
      const ids = Array.from(state.report.historySelectedIds);
      if (ids.length) activateReports(ids);
    });
  }

  function showHistoryPopover() {
    // Pre-seed selection with the currently active set so opening the
    // popover always reflects "what's already on" — user can then add/
    // remove freely and click "激活所选" to apply.
    const active = activeIdSet();
    state.report.historySelectedIds = new Set(active);
    refreshReportHistory();
    el.historyPopover.hidden = false;
    setTimeout(() => el.historyPopover.classList.add("visible"), 10);
  }

  function hideHistoryPopover() {
    el.historyPopover.classList.remove("visible");
    setTimeout(() => { el.historyPopover.hidden = true; }, 150);
    state.report.historySelectedIds.clear();
  }

  // Click outside popover to dismiss
  document.addEventListener("click", (e) => {
    if (el.historyPopover && !el.historyPopover.hidden) {
      if (!el.historyPopover.contains(e.target)
          && e.target !== el.btnHistory
          && !(el.btnHistory && el.btnHistory.contains(e.target))) {
        hideHistoryPopover();
      }
    }
  });

  // ------------------------------------------------------------------
  // Input handling
  // ------------------------------------------------------------------
  function trySend() {
    const text = el.chatInput.value.trim();
    if (!text) return;
    el.chatInput.value = "";
    el.chatInput.style.height = "";
    sendMessage(text);
  }

  el.btnSend.addEventListener("click", trySend);
  el.chatInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      trySend();
    }
  });
  el.chatInput.addEventListener("input", () => {
    el.chatInput.style.height = "auto";
    el.chatInput.style.height = Math.min(el.chatInput.scrollHeight, 140) + "px";
  });

  async function resetConversation(opts) {
    const silent = opts && opts.silent;
    if (state.busy) return;
    if (!silent && !confirm("开始新对话?当前对话会存入左侧「最近」,可随时恢复。")) return;
    await saveCurrentConversation();   // persist current to 最近 before clearing
    const url = state.mode === "report" ? "/api/report/session/reset" : "/api/session/reset";
    await fetch(url, { method: "POST" });
    clearBucketChat(state.mode);       // also resets bucket.convId → fresh
    renderEmptyState();
    if (state.mode === "report") {
      await refreshReportStatus();
    }
    loadRecent();
    const ms = document.getElementById("memory-status");
    if (ms) {
      ms.textContent = "✓ 已开始新对话(上一段已存入「最近」)";
      ms.className = "settings-status success";
      setTimeout(() => { if (ms) ms.textContent = ""; }, 2500);
    }
  }

  if (el.btnReset) el.btnReset.addEventListener("click", () => resetConversation());
  const navNewChat = document.getElementById("nav-new-chat");
  if (navNewChat) navNewChat.addEventListener("click", () => {
    showView("workspace");
    resetConversation({ silent: true });
  });

  // ------------------------------------------------------------------
  // Inspector collapse / expand
  // ------------------------------------------------------------------
  const INSPECTOR_LS_KEY = "bi.inspectorCollapsed";

  function applyInspectorState(collapsed) {
    document.body.dataset.inspector = collapsed ? "collapsed" : "expanded";
    if (el.btnToggleInspector) {
      el.btnToggleInspector.textContent = collapsed ? "◧ PANEL" : "◨ PANEL";
      el.btnToggleInspector.title = collapsed
        ? "展开右侧检查面板 (Ctrl+\\)"
        : "折叠右侧检查面板 (Ctrl+\\)";
    }
    try { localStorage.setItem(INSPECTOR_LS_KEY, collapsed ? "1" : "0"); } catch (e) {}
  }

  function toggleInspector() {
    const collapsed = document.body.dataset.inspector === "collapsed";
    applyInspectorState(!collapsed);
  }

  // Restore on boot
  (function bootInspectorState() {
    let collapsed = false;
    try { collapsed = localStorage.getItem(INSPECTOR_LS_KEY) === "1"; } catch (e) {}
    applyInspectorState(collapsed);
  })();

  // Wire up wheel forwarding for chat-scroll so the wheel works
  // anywhere in the chat content, not just on the visible scrollbar.
  setupChatWheelForwarding();

  if (el.btnToggleInspector) el.btnToggleInspector.addEventListener("click", toggleInspector);
  if (el.inspectorCollapseBtn) el.inspectorCollapseBtn.addEventListener("click", () => applyInspectorState(true));
  if (el.inspectorReopen) el.inspectorReopen.addEventListener("click", () => applyInspectorState(false));

  // ------------------------------------------------------------------
  // Sidebar collapse / expand  (left nav, Claude/ChatGPT-style)
  // ------------------------------------------------------------------
  // Versioned key makes the first visit use the new icon-rail default while
  // preserving an explicit expand/collapse choice afterwards.
  const SIDEBAR_LS_KEY = "bi.sidebarCollapsed.v2";

  function applySidebarState(collapsed) {
    document.body.classList.toggle("sidebar-collapsed", collapsed);
    if (el.sidebarCollapse) {
      el.sidebarCollapse.title = collapsed ? "展开侧栏" : "收起侧栏";
    }
    try { localStorage.setItem(SIDEBAR_LS_KEY, collapsed ? "1" : "0"); } catch (e) {}
  }

  (function bootSidebarState() {
    let collapsed = true;
    let saved = null;
    try {
      saved = localStorage.getItem(SIDEBAR_LS_KEY);
      collapsed = saved === "1";
    } catch (e) {}
    // No saved preference means the navigation starts in the compact icon rail.
    if (saved == null) collapsed = true;
    applySidebarState(collapsed);
  })();

  if (el.sidebarCollapse) {
    el.sidebarCollapse.addEventListener("click", () => {
      applySidebarState(!document.body.classList.contains("sidebar-collapsed"));
    });
  }
  if (el.sidebarReopen) el.sidebarReopen.addEventListener("click", () => applySidebarState(false));

  // ------------------------------------------------------------------
  // Dashboard collapse / expand  (middle pane)
  // ------------------------------------------------------------------
  const DASHBOARD_LS_KEY = "bi.dashboardCollapsed";

  function applyDashboardState(collapsed) {
    document.body.dataset.dashboard = collapsed ? "collapsed" : "expanded";
    if (el.btnToggleDashboard) {
      el.btnToggleDashboard.classList.toggle("collapsed", collapsed);
      el.btnToggleDashboard.title = collapsed ? "展开中间实时看板" : "折叠中间实时看板";
    }
    try { localStorage.setItem(DASHBOARD_LS_KEY, collapsed ? "1" : "0"); } catch (e) {}
  }

  function toggleDashboard() {
    const collapsed = document.body.dataset.dashboard === "collapsed";
    applyDashboardState(!collapsed);
  }

  (function bootDashboardState() {
    let collapsed = false;
    try { collapsed = localStorage.getItem(DASHBOARD_LS_KEY) === "1"; } catch (e) {}
    applyDashboardState(collapsed);
  })();

  if (el.btnToggleDashboard) el.btnToggleDashboard.addEventListener("click", toggleDashboard);
  if (el.dashboardCollapseBtn) el.dashboardCollapseBtn.addEventListener("click", () => applyDashboardState(true));
  if (el.dashboardReopen) el.dashboardReopen.addEventListener("click", () => applyDashboardState(false));
  if (el.dashboardClear) el.dashboardClear.addEventListener("click", () => {
    if (!confirm("清空当前模式的实时看板?")) return;
    clearDashboard();
  });
  document.addEventListener("keydown", (e) => {
    // Ctrl+\  — toggle inspector (ignore inside text inputs so \ still types)
    if (e.ctrlKey && !e.shiftKey && !e.altKey && e.key === "\\") {
      const tag = (e.target && e.target.tagName) || "";
      if (tag === "TEXTAREA" || tag === "INPUT") return;
      e.preventDefault();
      toggleInspector();
    }
  });

  // ------------------------------------------------------------------
  // Cross-frame: parent shell (CEO dashboard) sends `{type:"toggleSettings",
  // visible: bool}` to show/hide the MODEL/RESET/DASH/PANEL row.
  // ------------------------------------------------------------------
  window.addEventListener("message", (e) => {
    const msg = e && e.data;
    if (!msg || typeof msg !== "object" || msg.type !== "toggleSettings") return;
    const hidden = msg.visible === false;
    document.body.classList.toggle("settings-hidden", hidden);
  });

  // ------------------------------------------------------------------
  // Quadrant assistant mode
  // ------------------------------------------------------------------
  const QUADRANT_PROMPT_META = {
    salesflow: {
      label: "财经助手",
      scope: "CEO 驾驶舱 · 问题象限 01 · 财务经营流",
      emptyTitle: "财经助手 · 财务经营流分析",
      welcome: "财经助手已就绪。可分析订-发-收-回节点落差、区域结构与回款健康度,也可直接改本象限的维度 / 文字 / 图表。",
      hints: [
        "本期发货为何高于订单 64.62 万?",
        "把订/发/收/回节点柱图按事业部下钻",
        "应收回款健康度如何?逾期客户有哪些?"
      ],
      filters: [
        { id: "salesTimeFilter", aria: "时间", current: ["年","季","月"] },
        { id: "salesRegionFilter", aria: "区域", current: ["集团","华东","华南","海外"] },
        { id: "salesScopeFilter", aria: "口径", current: ["财报","业务库","财报+业务库"] }
      ],
      charts: [{ id: "salesNodeBars", desc: "订/发/收/回 节点柱图" }],
      textHints: [
        "article[data-quadrant='salesflow'] .problem-title h2  — 象限主问题",
        "article[data-quadrant='salesflow'] .flow-block-title  — 顶层设计/告警分组小标题",
        "article[data-quadrant='salesflow'] .sales-filter-row b — 流程节点目标达成标题",
        "article[data-quadrant='salesflow'] .gap-tile b — 关键落差小卡名",
        "article[data-quadrant='salesflow'] .core-flow-tile b — 核心流小卡名"
      ]
    },
    assetflow: {
      label: "资产助手",
      scope: "CEO 驾驶舱 · 问题象限 02 · 资产运营流",
      emptyTitle: "资产助手 · 资产运营流分析",
      welcome: "资产助手已就绪。可分析采购→生产→仓库→站点四段库存接力与落差、品类呆滞与不良品,也可改本象限维度 / 文字 / 图表。",
      hints: [
        "四段实物流哪一段落差最大?",
        "按品类拆解站点库存与 6 月以上超期金额",
        "给四段接力柱图增加「包材」品类维度"
      ],
      filters: [
        { id: "assetCategoryFilter", aria: "品类", current: ["闪光灯罩","金属件","镜片/陶瓷","电子件","检测类","板卡类","塑料件"] }
      ],
      charts: [{ id: "assetStageBars", desc: "原材料 → 在制 → 成品 → 发出 四段接力柱图" }],
      textHints: [
        "article[data-quadrant='assetflow'] .problem-title h2 — 象限主问题",
        "article[data-quadrant='assetflow'] .asset-box h4 — 资产健康/经营关注盒标题",
        "article[data-quadrant='assetflow'] .asset-filter-row b — 四段接力标题",
        "article[data-quadrant='assetflow'] .asset-kpi span — KPI 标签",
        "article[data-quadrant='assetflow'] .asset-alert span — 告警标签"
      ]
    },
    command: {
      label: "督办助手",
      scope: "CEO 驾驶舱 · 问题象限 03 · 督办令中心",
      emptyTitle: "督办助手 · 督办令中心",
      welcome: "督办助手已就绪。可梳理督办四步闭环、超期与待验收任务及责任负载,也可改本象限的步骤文案。",
      hints: [
        "当前超期督办令的阻塞原因是什么?",
        "待验收 5 单是否已有方案未组织验收?",
        "把四步闭环说明改得更精炼"
      ],
      filters: [],
      charts: [],
      textHints: [
        "article[data-quadrant='command'] .problem-title h2 — 象限主问题",
        "article[data-quadrant='command'] .command-step b — 四步骤标题",
        "article[data-quadrant='command'] .command-step p — 四步骤说明"
      ]
    },
    riskmatrix: {
      label: "风险助手",
      scope: "CEO 驾驶舱 · 问题象限 04 · 四维风险热力矩阵",
      emptyTitle: "风险助手 · 四维风险热力矩阵",
      welcome: "风险助手已就绪。可解读运营 / 技术 / 预测 / 合规四维风险敞口与优先处置区,也可改本象限的风险区文案。",
      hints: [
        "哪个风险区已达优先处置阈值?",
        "交付延迟敞口集中在哪些客户?",
        "调整运营风险区的描述文案"
      ],
      filters: [],
      charts: [],
      textHints: [
        "article[data-quadrant='riskmatrix'] .problem-title h2 — 象限主问题",
        "article[data-quadrant='riskmatrix'] .risk-zone h4 — 风险区标题",
        "article[data-quadrant='riskmatrix'] .risk-zone p — 风险区描述",
        "article[data-quadrant='riskmatrix'] .risk-zone small — 风险区脚注"
      ]
    },
    reportmgmt: {
      label: "报表助手",
      scope: "CEO 驾驶舱 · 问题象限 05 · 报表管理",
      emptyTitle: "报表助手 · 报表管理",
      welcome: "报表助手已就绪。可治理口径变更、公共项分摊、核对差异与报表同步等事项,也可改本象限的通用问题文案。",
      hints: [
        "仍待确认的口径变更有哪些?",
        "公共项异常占比 12.8% 如何拆解?",
        "改写通用问题板块的标题"
      ],
      filters: [],
      charts: [],
      textHints: [
        "article[data-quadrant='reportmgmt'] .problem-title h2 — 象限主问题",
        "article[data-quadrant='reportmgmt'] .report-common-board h4 — 通用问题板块标题",
        "article[data-quadrant='reportmgmt'] .report-issue — 单条通用问题"
      ]
    }
  };

  function applyQuadrantFromUrl() {
    let key = null;
    try {
      key = new URLSearchParams(location.search).get("quadrant");
    } catch (_) { key = null; }
    if (!key || !QUADRANT_PROMPT_META[key]) return;
    state.quadrant = key;
    const meta = QUADRANT_PROMPT_META[key];
    const badge = document.getElementById("brand-quadrant");
    if (badge) {
      badge.textContent = meta.label;
      badge.hidden = false;
      badge.title = meta.scope;
    }
    // Stamp body for any future CSS hooks
    document.body.dataset.quadrant = key;

    // Mode lock per quadrant: only 报表助手(第五象限/reportmgmt)gets
    // 报表分析; every other quadrant assistant is数据分析 only. The
    // bottom-right general assistant has no quadrant → keeps both modes.
    const lockedMode = (key === "reportmgmt") ? "report" : "data";
    state.lockedMode = lockedMode;
    if (state.mode !== lockedMode) switchMode(lockedMode);
    // Hide the data/report toggle — quadrant assistants are single-mode.
    if (el.modeSwitch) el.modeSwitch.hidden = true;
  }

  function buildQuadrantSystemPrefix() {
    if (!state.quadrant) return "";
    const meta = QUADRANT_PROMPT_META[state.quadrant];
    if (!meta) return "";
    const filterLines = meta.filters.length
      ? meta.filters.map(f => `  · id=${f.id} (${f.aria}) — 当前选项: [${f.current.join(", ")}]`).join("\n")
      : "  · (本象限暂无可编辑筛选器)";
    const chartLines = meta.charts.length
      ? meta.charts.map(c => `  · ${c.id} — ${c.desc}`).join("\n")
      : "  · (本象限暂无可编辑图表)";
    const textLines = meta.textHints.map(t => `  · ${t}`).join("\n");
    return [
      `[象限助手系统提示 — 此段内容仅用于约束你本轮的输出格式,不要在回复中复述]`,
      `你当前作为「${meta.label}」运行,服务于 ${meta.scope}。`,
      `除常规的数据问答外,你还可以直接修改这块象限页面。`,
      ``,
      `可改的筛选器(<select>):`,
      filterLines,
      ``,
      `可改的图表:`,
      chartLines,
      ``,
      `可改的看板文字(白名单 selector,严格匹配前缀):`,
      textLines,
      ``,
      `如果用户的话明确要求改页面,请在你的回答里输出一个或多个 fenced code block,语言标记必须是 \`ui-command\`,内容为 JSON 对象,字段定义:`,
      `  - channel: 固定 "cockpit-ui"`,
      `  - quadrant: 固定 "${state.quadrant}"`,
      `  - action: 以下之一`,
      `      · set_filter_options    {target:"<filter id>", options:[{value,label}|"字符串"...]}`,
      `      · add_filter_option     {target:"<filter id>", option:{value,label}|"字符串"}`,
      `      · remove_filter_option  {target:"<filter id>", value:"<要删的 value 或 label>"}`,
      `      · set_text              {selector:"<上面 textHints 白名单>", text:"<新文字>", limit?:<数字,只改前几个>}`,
      `      · set_chart_dim         {chart_id:"<chart id>", dim:"<by_region|by_bu|by_node|…>"}`,
      `      · set_chart_type        {chart_id:"<chart id>", type:"bars|line"}`,
      `      · set_chart_color       {chart_id:"<chart id>", color:"#hex 或 css color"}`,
      ``,
      `重要约定:`,
      `  - target / chart_id 都是裸 DOM id,不要加 "#" 前缀(写 "assetCategoryFilter" 而不是 "#assetCategoryFilter")。`,
      `  - 一次回答可以发多条 ui-command 块,会作为一批等用户点「执行」后统一应用。`,
      ``,
      `示例(把财经象限的时间筛选器改为半年口径):`,
      "```ui-command",
      `{"channel":"cockpit-ui","quadrant":"salesflow","action":"set_filter_options","target":"salesTimeFilter","options":["上半年","下半年","全年"]}`,
      "```",
      ``,
      `若用户只是问数,正常调本体/SQL/图表工具回答即可,不要发 ui-command。`,
      `若用户要求改页面但要素不全(比如没说具体改什么文字),正常提问澄清,不要凭空发 ui-command。`,
      ``,
      `数据分析纪律(与通用助手完全一致,不得因象限身份弱化 —— ui-command 是附加能力,不替代分析 SOP):`,
      `  - 🔴 强制图表配对:本轮只要调用了 \`TableGenerate\`,就必须同时至少调用 1 次 \`ChartGenerate\`;≥2 行的结果集禁止在正文手写 Markdown \`|\` 表格,必须走 \`TableGenerate\`。L1 取数/L2 问题寻找 多行结果 ≥1 表 +≥1 图;L3 及以上分析型 ≥1 表 +≥2 图(2 图覆盖不同视角)。仅 1 行 1 列纯标量可只用文字。`,
      `  - 🔴 五级分析逐级递进并逐级引导(L1 取数→L2 问题→L3 根因→L4 决策→L5 执行):每轮交付必须有一条 📌结论(一句带数字与实体编码,会被抽取为看板结论卡);L1–L4 结尾用一句话 🧭引导进入下一级。L3 起带 🔍根因证据链(论点+数据+来源三元组)+ 📈附图;L4 每个方案含效果/成本/风险/周期(+历史案例)并给推荐;L5 给可执行行动(谁/何时/标准)+可量化监控+复盘闭环。这些段落前端会汇总进中间实时看板,缺图或缺结论视为交付不合格。`,
      `[象限助手系统提示结束]`
    ].join("\n");
  }

  function extractUiCommands(text) {
    if (!text || typeof text !== "string") return [];
    const out = [];
    const re = /```ui-command\s*\n([\s\S]*?)```/g;
    let m;
    while ((m = re.exec(text)) !== null) {
      const body = m[1].trim();
      if (!body) continue;
      try {
        const obj = JSON.parse(body);
        if (obj && typeof obj === "object") {
          obj.channel = "cockpit-ui";
          if (!obj.quadrant && state.quadrant) obj.quadrant = state.quadrant;
          out.push(obj);
        }
      } catch (err) {
        console.warn("[ui-command] bad JSON block:", body, err);
      }
    }
    return out;
  }

  // ------------------------------------------------------------------
  // Pending UI-command queue:
  // Commands are STAGED here as they come out of llm_response. The user
  // clicks an "执行" button rendered at end-of-turn to flush the whole
  // batch to the cockpit in a single apply_batch postMessage.
  // ------------------------------------------------------------------
  function describeUiCommand(cmd) {
    if (!cmd || !cmd.action) return "(空命令)";
    switch (cmd.action) {
      case "set_filter_options": {
        const n = Array.isArray(cmd.options) ? cmd.options.length : 0;
        const tail = Array.isArray(cmd.options)
          ? cmd.options.slice(0, 3).map(o => typeof o === "string" ? o : (o.label ?? o.value)).join("、")
          : "";
        return `改筛选项 · #${cmd.target} → ${n} 项${tail ? ` (${tail}${n > 3 ? "…" : ""})` : ""}`;
      }
      case "add_filter_option":
        return `追加筛选项 · #${cmd.target} → ${typeof cmd.option === "string" ? cmd.option : (cmd.option?.label ?? cmd.option?.value ?? "?")}`;
      case "remove_filter_option":
        return `移除筛选项 · #${cmd.target} · ${cmd.value}`;
      case "set_text": {
        const sel = String(cmd.selector || "");
        const shortSel = sel.length > 56 ? "…" + sel.slice(-54) : sel;
        const t = String(cmd.text || "");
        return `改文字 · ${shortSel} → 「${t.length > 28 ? t.slice(0, 28) + "…" : t}」`;
      }
      case "set_chart_dim":
        return `改图表维度 · ${cmd.chart_id} → ${cmd.dim}`;
      case "set_chart_type":
        return `改图表类型 · ${cmd.chart_id} → ${cmd.type}`;
      case "set_chart_color":
        return `改图表配色 · ${cmd.chart_id} → ${cmd.color}`;
      default:
        return `${cmd.action}`;
    }
  }

  function stageUiCommands(cmds) {
    if (!cmds || !cmds.length) return;
    const bucket = B();
    if (!bucket.pendingCommands) bucket.pendingCommands = [];
    for (const c of cmds) bucket.pendingCommands.push(c);
  }

  function appendApplyButton(turnTag) {
    const bucket = B();
    const cmds = bucket.pendingCommands || [];
    if (!cmds.length) return;
    if (!state.quadrant) return; // outside quadrant-assistant mode — no-op
    // If this turn already has an apply card we re-render it to reflect the
    // latest pending list (in case multiple llm_response iterations added
    // commands during the same turn).
    const tagStr = String(turnTag);
    const existing = el.chatScroll.querySelector(`.ui-apply-card[data-turn="${CSS.escape(tagStr)}"]`);
    if (existing) existing.remove();
    const card = el_h("div", "ui-apply-card");
    card.dataset.turn = tagStr;
    const list = cmds.map(c => `<li>${esc(describeUiCommand(c))}</li>`).join("");
    card.innerHTML = `
      <div class="ui-apply-head">
        <span class="ui-apply-icon">🛠</span>
        <span class="ui-apply-title">本轮 ${cmds.length} 条待应用变更</span>
        <button type="button" class="ui-apply-btn">▶ 执行</button>
      </div>
      <ul class="ui-apply-list">${list}</ul>
      <div class="ui-apply-status"></div>`;
    el.chatScroll.appendChild(card);
    scrollChatBottom();
    card.querySelector(".ui-apply-btn").addEventListener("click", () => {
      applyPendingCommands(card);
    });
  }

  function applyPendingCommands(card) {
    const bucket = B();
    const cmds = (bucket.pendingCommands || []).slice();
    if (!cmds.length) {
      const status = card.querySelector(".ui-apply-status");
      if (status) status.textContent = "没有待应用的变更";
      return;
    }
    const btn = card.querySelector(".ui-apply-btn");
    const status = card.querySelector(".ui-apply-status");
    if (btn) { btn.disabled = true; btn.textContent = "应用中…"; }
    if (status) status.textContent = `正在应用 ${cmds.length} 条变更…`;
    const target = (window.parent && window.parent !== window) ? window.parent : null;
    if (!target) {
      if (status) status.textContent = "未检测到驾驶舱(workbench 未嵌入)";
      if (btn) { btn.disabled = false; btn.textContent = "▶ 执行"; }
      return;
    }
    const reqId = `apply-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
    function ackHandler(e) {
      const msg = e.data;
      if (!msg || msg.channel !== "cockpit-ui-ack" || msg.req !== reqId) return;
      window.removeEventListener("message", ackHandler);
      clearTimeout(timer);
      handleApplyAck(card, msg);
    }
    const timer = setTimeout(() => {
      window.removeEventListener("message", ackHandler);
      handleApplyAck(card, { ok: false, error: "驾驶舱未响应(超时)" });
    }, 5000);
    window.addEventListener("message", ackHandler);
    try {
      target.postMessage({
        channel: "cockpit-ui",
        action: "apply_batch",
        quadrant: state.quadrant,
        commands: cmds,
        req: reqId,
      }, "*");
    } catch (err) {
      window.removeEventListener("message", ackHandler);
      clearTimeout(timer);
      handleApplyAck(card, { ok: false, error: String(err && err.message || err) });
      return;
    }
    bucket.pendingCommands = [];
  }

  function handleApplyAck(card, ack) {
    const btn = card.querySelector(".ui-apply-btn");
    const status = card.querySelector(".ui-apply-status");
    if (ack && ack.ok) {
      if (btn) btn.style.display = "none";
      const applied = (typeof ack.applied === "number") ? ack.applied : null;
      const failed = (typeof ack.failed === "number") ? ack.failed : 0;
      if (status) {
        status.textContent = failed > 0
          ? `✓ 已应用 ${applied ?? "全部"} 条变更(其中 ${failed} 条失败,详见控制台)`
          : `✓ 已应用 ${applied ?? "全部"} 条变更`;
      }
      card.classList.add("applied");
    } else {
      if (btn) { btn.disabled = false; btn.textContent = "重试"; }
      if (status) status.textContent = `应用失败: ${ack?.error || "未知错误"}`;
      card.classList.add("failed");
    }
  }

  // Light theme — opt-in via ?theme=light (e.g. embedded as the white-based
  // Meta-ERP 智能分析助手 inside the role dashboard's i-Agent). Stamps a class
  // on <html> that flips the dark palette to a light one (see styles.css).
  function applyThemeFromUrl() {
    let theme = null;
    try { theme = new URLSearchParams(location.search).get("theme"); }
    catch (_) { theme = null; }
    if (theme === "light") document.documentElement.classList.add("theme-light");
  }

  applyThemeFromUrl();
  applyQuadrantFromUrl();
  bindDashboardQuestionLinks();

  // ------------------------------------------------------------------
  // Boot
  // ------------------------------------------------------------------
  loadMeta();
  loadRecent();
})();
