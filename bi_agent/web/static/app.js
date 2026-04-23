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
      // Detached DOM children (populated on mode switch-out)
      chatNodes: [],
      ontologyNodes: [],
      toolNodes: [],
      llmNodes: [],
      // Whether the mode currently has any chat content
      hasContent: false,
    };
  }

  const buckets = { data: makeBucket(), report: makeBucket() };

  // ------------------------------------------------------------------
  // Global state
  // ------------------------------------------------------------------
  const state = {
    meta: null,
    busy: false,
    activeTab: "ontology",
    mode: "data",                      // "data" | "report"
    // Report-mode extras
    report: {
      activeReport: null,              // {id, filename, ...}
      withDb: false,
      history: [],                     // list of records from /api/report/list
      sessionActivated: false,
    },
  };

  function B() { return buckets[state.mode]; }

  // ------------------------------------------------------------------
  // Elements
  // ------------------------------------------------------------------
  const el = {
    chatScroll:     document.getElementById("chat-scroll"),
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
  };

  // Default empty-state strings per mode
  const EMPTY_STATES = {
    data: {
      glyph: "◇",
      title: "光峰财务 BI 智能分析",
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
    term: "TERM",
    business_object: "BO",
    logical_entity: "LE",
    attribute: "ATTR",
    relation: "REL",
    metric: "METRIC",
    activity: "ACT",
    rule: "RULE",
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

  function el_h(tag, cls, html) {
    const x = document.createElement(tag);
    if (cls) x.className = cls;
    if (html !== undefined) x.innerHTML = html;
    return x;
  }

  function scrollChatBottom() {
    el.chatScroll.scrollTop = el.chatScroll.scrollHeight;
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
    if (agent) el.agentName.textContent = agent.name;
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
    el.emptyGlyph.textContent = cfg.glyph;
    el.emptyTitle.textContent = cfg.title;
    const agent = currentAgentMeta();
    el.emptyWelcome.textContent =
      (agent && (agent.welcome_message || agent.description)) || "";
    el.emptyHints.innerHTML = cfg.hints.map(h =>
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
      el.settingsModel.appendChild(opt);
    });
    const cur = llm.current || {};
    el.settingsModel.value = cur.model_key || "";
    el.settingsMaxTokens.value = cur.max_tokens ?? 8192;
    el.settingsTemp.value = cur.temperature ?? 1.0;
    el.settingsTempVal.textContent = Number(el.settingsTemp.value).toFixed(2);
    updateModelHint();
    renderKeyStatus(llm.api_keys || {});
    el.settingsKeyAnthropic.value = "";
    el.settingsKeyQwen.value = "";
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
  }

  function updateModelHint() {
    const opt = el.settingsModel.options[el.settingsModel.selectedIndex];
    if (!opt) { el.settingsModelHint.textContent = ""; return; }
    const provider = opt.dataset.provider;
    const maxOut = opt.dataset.maxOutputTokens;
    let hint = `provider: ${provider} · max_output: ${maxOut}`;
    if (provider === "qwen") hint += " · 需要环境变量 DASHSCOPE_API_KEY";
    else hint += " · 需要环境变量 ANTHROPIC_API_KEY";
    el.settingsModelHint.textContent = hint;
    el.settingsMaxTokens.max = maxOut;
  }

  function openSettings() {
    el.settingsStatus.textContent = "";
    el.settingsOverlay.hidden = false;
    setTimeout(() => el.settingsOverlay.classList.add("visible"), 10);
  }

  function closeSettings() {
    el.settingsOverlay.classList.remove("visible");
    setTimeout(() => { el.settingsOverlay.hidden = true; }, 150);
  }

  async function saveSettings() {
    const payload = {
      model_key: el.settingsModel.value,
      max_tokens: parseInt(el.settingsMaxTokens.value, 10),
      temperature: parseFloat(el.settingsTemp.value),
    };
    const aKey = el.settingsKeyAnthropic.value.trim();
    if (aKey) payload.anthropic_api_key = aKey;
    const qKey = el.settingsKeyQwen.value.trim();
    if (qKey) payload.qwen_api_key = qKey;

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
    const payload = provider === "anthropic"
      ? { anthropic_api_key: "" }
      : { qwen_api_key: "" };
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
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && el.settingsOverlay && !el.settingsOverlay.hidden) {
      closeSettings();
    }
  });

  // ------------------------------------------------------------------
  // System prompt (per-mode)
  // ------------------------------------------------------------------
  async function loadSystemPrompt() {
    el.systemContent.innerHTML = '<div class="sys-section"><div class="sys-title">Loading…</div></div>';
    try {
      const r = await fetch(`/api/system-prompt?mode=${state.mode}`);
      const data = await r.json();
      B().systemPrompt = data.system_prompt;
      renderSystem();
    } catch (e) {
      el.systemContent.innerHTML = `<div class="sys-section"><div class="sys-title">Error</div><div class="sys-body">${esc(e.message || String(e))}</div></div>`;
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
             "DescribeTable", "ChartGenerate", "AskUser"]
          : ["ChartGenerate", "AskUser"])
      : (a.tools || []);
    const tools = toolsList.map(t => `<span class="tool-pill">${esc(t)}</span>`).join("") || '<span class="kv-v">(all)</span>';
    el.systemContent.innerHTML = `
      <div class="sys-section">
        <div class="sys-title">Agent Definition (${esc(state.mode)} mode)</div>
        <div class="sys-body">name: ${esc(a.name)}
model: ${esc(a.model || "default")}
description: ${esc(a.description || "")}
welcome: ${esc(a.welcome_message || "")}</div>
      </div>
      <div class="sys-section">
        <div class="sys-title">Tool Whitelist</div>
        <div style="padding: 4px 0;">${tools}</div>
      </div>
      <div class="sys-section">
        <div class="sys-title">System Prompt (full)</div>
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
    el.turnCounter.textContent = n + (n === 1 ? " turn" : " turns");
  }

  function addUserMessage(text) {
    hideEmpty();
    B().turnCount += 1;
    updateTurnCounter();
    const msg = el_h("div", "msg msg-user");
    msg.innerHTML = `
      <div class="msg-header">
        <span class="msg-role user">USER</span>
      </div>
      <div class="msg-body">${esc(text)}</div>`;
    el.chatScroll.appendChild(msg);
    scrollChatBottom();
  }

  function assistantRoleLabel() {
    const agent = currentAgentMeta();
    return (agent && agent.name ? agent.name : "ASSISTANT").toUpperCase();
  }

  function startAssistantMessage(iteration) {
    const msg = el_h("div", "msg msg-assistant");
    msg.innerHTML = `
      <div class="msg-header">
        <span class="msg-role assistant">${esc(assistantRoleLabel())}</span>
        <span class="msg-iter">iter ${iteration}</span>
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
    const card = el_h("div", "choice-card");
    card.dataset.toolUseId = evt.tool_use_id;
    const optionsHtml = (evt.options || []).map((opt, idx) => `
      <button class="choice-option" data-id="${esc(opt.id)}" data-label="${esc(opt.label)}">
        <span class="choice-idx">${idx + 1}</span>
        <span class="choice-body">
          <span class="choice-label">${esc(opt.label)}</span>
          ${opt.detail ? `<span class="choice-detail">${esc(opt.detail)}</span>` : ""}
        </span>
        <span class="choice-arrow">↵</span>
      </button>`).join("");
    card.innerHTML = `
      <div class="choice-head">
        <span class="choice-tag">需要您选择</span>
        <span class="choice-question">${esc(evt.question || "")}</span>
      </div>
      ${evt.context ? `<div class="choice-context">${esc(evt.context)}</div>` : ""}
      <div class="choice-options">${optionsHtml}</div>
      <div class="choice-status"></div>`;
    container.appendChild(card);
    scrollChatBottom();

    card.querySelectorAll(".choice-option").forEach(btn => {
      btn.addEventListener("click", () => {
        submitChoice(card, btn.dataset.id, btn.dataset.label);
      });
    });
  }

  function markChoiceResolved(toolUseId, label) {
    const card = el.chatScroll.querySelector(`.choice-card[data-tool-use-id="${CSS.escape(toolUseId)}"]`);
    if (!card) return;
    card.classList.add("resolved");
    const status = card.querySelector(".choice-status");
    if (status) status.textContent = `已选择: ${label}`;
    card.querySelectorAll(".choice-option").forEach(b => { b.disabled = true; });
  }

  async function submitChoice(card, id, label) {
    if (card.classList.contains("resolved")) return;
    card.classList.add("submitting");
    const status = card.querySelector(".choice-status");
    if (status) status.textContent = `正在提交: ${label}…`;
    setBusy(true);

    const url = state.mode === "report" ? "/api/report/choice" : "/api/choice";
    const resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ choice_id: id, choice_label: label }),
    });
    if (!resp.ok || !resp.body) {
      onEvent({ type: "error", message: `HTTP ${resp.status}` });
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
    const savedLink = chart.saved_path
      ? `<span class="chart-saved">saved: <a href="/charts/${esc(chart.saved_path.split(/[\\/]/).pop())}" target="_blank" title="${esc(chart.saved_path)}">${esc(chart.saved_path.split(/[\\/]/).pop())}</a></span>`
      : "";
    card.innerHTML = `
      <div class="chart-head">
        <span class="chart-type">${esc(chart.chart_type || "chart")}</span>
        <span class="chart-title">${esc(chart.title || "")}</span>
        ${savedLink}
      </div>
      <div class="chart-canvas"></div>`;
    return card;
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
    } catch (e) {
      canvas.innerHTML = `<div style="padding:14px;color:var(--accent-red);font-family:var(--font-mono);font-size:12px;">Chart render failed: ${esc(e.message || String(e))}</div>`;
    }
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
    const targetTab = Array.from(el.tabs).find(t => t.dataset.tab === "ontology");
    if (targetTab) targetTab.click();
    const card = el.ontologyList.querySelector(`.entity-card[data-code="${CSS.escape(code)}"]`);
    if (card) {
      card.classList.add("open");
      card.scrollIntoView({ behavior: "smooth", block: "center" });
      card.style.transition = "background 0.3s";
      card.style.background = "rgba(88, 166, 255, 0.15)";
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
          <div class="kv-label">Input</div>
          <pre>${esc(JSON.stringify(r.input || {}, null, 2))}</pre>
        </div>
        <div class="kv-block">
          <div class="kv-label">Output</div>
          <pre>${esc(r.output || "")}</pre>
        </div>
        ${chips ? `<div class="kv-block">
          <div class="kv-label">Ontology Entities Touched</div>
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
        <div class="step-sub">Input</div>
        <pre>${esc(JSON.stringify(r.input || {}, null, 2))}</pre>
        <div class="step-sub">Output</div>
        <pre>${esc(r.output || "")}</pre>
        ${chips ? `<div class="step-sub">Ontology Hits</div><div class="chip-row">${chips}</div>` : ""}
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
      ? `${response.usage.output_tokens || 0} out`
      : "…";
    const stopR = response && response.stop_reason ? response.stop_reason : "…";
    const nTools = response && response.tool_uses ? response.tool_uses.length : 0;
    const summary = nTools
      ? `${response.text ? "text+" : ""}${nTools} tool_use · stop=${stopR}`
      : (response && response.text ? `text · stop=${stopR}` : "streaming…");

    const card = el_h("div", "llm-card");
    card.innerHTML = `
      <div class="llm-head">
        <span class="iter">REQ #${idx + 1} · iter ${iteration}</span>
        <span class="summary">${esc(summary)}</span>
        <span class="usage">${esc(tokenInfo)}</span>
      </div>
      <div class="llm-body">
        <div class="kv-label">Request Messages (${request.message_count})</div>
        ${renderMessages(request.messages_snapshot || [])}
        <div class="kv-label" style="margin-top: 12px;">Response</div>
        ${response ? renderResponse(response) : '<div class="msg-block">streaming…</div>'}
      </div>`;
    card.querySelector(".llm-head").addEventListener("click", () => card.classList.toggle("open"));
    return card;
  }

  function renderMessages(messages) {
    if (!messages || !messages.length) return '<div class="msg-block">(empty)</div>';
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
    return parts.join("") || '<div class="msg-block">(empty)</div>';
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
        };
        recordToolCall(record);
        attachChatStep(buildChatStep(record));
        if (record.chart) attachChatChart(record.chart);
        upsertOntologyEntities(evt.ontology_entities);
        break;
      }
      case "user_choice_requested":
        attachChoiceCard(evt);
        setBusy(false);
        break;
      case "user_choice_resolved":
        markChoiceResolved(evt.tool_use_id, evt.choice_label);
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
        break;
      case "done":
        setBusy(false);
        break;
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
    addUserMessage(text);

    const url = state.mode === "report" ? "/api/report/chat" : "/api/chat";
    const resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text }),
    });
    if (!resp.ok || !resp.body) {
      const errText = await resp.text().catch(() => resp.statusText);
      onEvent({ type: "error", message: `HTTP ${resp.status}: ${errText}` });
      return;
    }
    await streamResponse(resp);
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
    el.btnSend.textContent = v ? "…" : "SEND ▸";
    // Block mode switching while a turn is in flight
    el.modeBtns.forEach(b => { b.disabled = v; });
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
    if (newMode === state.mode || state.busy) return;

    // Stash outgoing mode's DOM (snapshot of current containers)
    const out = buckets[state.mode];
    out.chatNodes      = detachChildren(el.chatScroll);
    out.ontologyNodes  = detachChildren(el.ontologyList);
    out.toolNodes      = detachChildren(el.toolList);
    out.llmNodes       = detachChildren(el.llmList);

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

    // Counters
    el.countOntology.textContent = inc.ontologyByCode.size;
    el.countTools.textContent    = inc.toolCalls.length;
    el.countLlm.textContent      = inc.llmTurns.length;
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
        el.chatInput.placeholder = "请先上传一份 PDF/Word 报表...";
      } else {
        el.chatInput.placeholder = `针对「${state.report.activeReport?.filename || "报表"}」提问...  (Enter 发送 · Shift+Enter 换行)`;
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
      if (data.active_report) {
        state.report.activeReport = data.active_report;
        state.report.withDb = !!data.with_db;
        state.report.sessionActivated = !!data.has_session;
      } else {
        state.report.activeReport = null;
        state.report.sessionActivated = false;
      }
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
    const active = state.report.activeReport;
    // Attach-chip only makes sense in report mode with an active report
    const chipVisible = state.mode === "report" && !!active;
    if (el.attachRow) el.attachRow.hidden = !chipVisible;
    if (chipVisible) {
      el.attachChipName.textContent = active.filename || "(未命名)";
      const parts = [
        active.ext?.replace(".", "").toUpperCase() || "",
        `${active.page_count || 0} 页`,
        `${active.tables_count || 0} 表格`,
        `${fmtBytes(active.size_bytes || active.text_length || 0)}`,
        fmtDate(active.uploaded_at),
      ].filter(Boolean);
      el.attachChipMeta.textContent = parts.join(" · ");
    }
    if (el.withDb) el.withDb.checked = !!state.report.withDb;
    updateChatInputAvailability();
    updateSendPlaceholder();
  }

  function renderHistoryList() {
    const items = state.report.history;
    if (!items.length) {
      el.historyList.innerHTML = '<div class="history-empty">暂无上传记录</div>';
      return;
    }
    el.historyList.innerHTML = items.map(it => {
      const meta = [
        (it.ext || "").replace(".", "").toUpperCase(),
        `${it.page_count || 0}页`,
        `${it.tables_count || 0}表`,
        fmtBytes(it.size_bytes || 0),
        fmtDate(it.uploaded_at),
      ].filter(Boolean).join(" · ");
      const isActive = state.report.activeReport && state.report.activeReport.id === it.id;
      return `
        <div class="history-item ${isActive ? 'active' : ''}" data-id="${esc(it.id)}">
          <div class="history-item-main">
            <div class="history-item-name">${esc(it.filename || "(未命名)")}</div>
            <div class="history-item-meta">${esc(meta)}</div>
            ${it.preview ? `<div class="history-item-preview">${esc(it.preview)}</div>` : ""}
          </div>
          <div class="history-item-actions">
            <button class="btn btn-ghost history-use" data-id="${esc(it.id)}">
              ${isActive ? '使用中' : '使用'}
            </button>
            <button class="btn btn-ghost history-del" data-id="${esc(it.id)}" title="删除">✕</button>
          </div>
        </div>`;
    }).join("");
    el.historyList.querySelectorAll(".history-use").forEach(b => {
      b.addEventListener("click", () => activateReport(b.dataset.id));
    });
    el.historyList.querySelectorAll(".history-del").forEach(b => {
      b.addEventListener("click", () => deleteReport(b.dataset.id));
    });
  }

  async function activateReport(rid) {
    if (state.busy) return;
    uploadStatus("正在激活报表…", "pending");
    try {
      const r = await fetch("/api/report/activate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ report_id: rid, with_db: !!state.report.withDb }),
      });
      if (!r.ok) throw new Error((await r.json()).detail || "activate failed");
      const data = await r.json();
      state.report.activeReport = data.active_report;
      state.report.withDb = !!data.with_db;
      state.report.sessionActivated = true;
      renderReportControls();
      await refreshReportHistory();
      hideHistoryPopover();
      // Clear chat of the report mode (server just (re)created a fresh session)
      clearBucketChat("report");
      uploadStatus(`已切换到「${data.active_report.filename}」`, "success");
      setTimeout(() => uploadStatus(""), 2000);
    } catch (e) {
      uploadStatus("激活失败: " + (e.message || e), "error");
    }
  }

  async function deleteReport(rid) {
    if (!confirm("确定删除该报表?该操作不可恢复。")) return;
    try {
      const r = await fetch(`/api/report/${encodeURIComponent(rid)}`, { method: "DELETE" });
      if (!r.ok) throw new Error("delete failed");
      if (state.report.activeReport && state.report.activeReport.id === rid) {
        state.report.activeReport = null;
        state.report.sessionActivated = false;
        clearBucketChat("report");
      }
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
    bucket.hasContent = false;
    // If this is the active mode, also clear visible DOM
    if (state.mode === mode) {
      detachChildren(el.chatScroll);
      detachChildren(el.ontologyList);
      detachChildren(el.toolList);
      detachChildren(el.llmList);
      if (el.chatEmpty && !el.chatEmpty.parentNode) el.chatScroll.appendChild(el.chatEmpty);
      if (el.chatEmpty) el.chatEmpty.style.display = "";
      el.countOntology.textContent = "0";
      el.countTools.textContent = "0";
      el.countLlm.textContent = "0";
      updateTurnCounter();
    }
  }

  async function uploadFile(file) {
    if (!file) return;
    const ext = file.name.toLowerCase().slice(file.name.lastIndexOf("."));
    if (ext !== ".pdf" && ext !== ".docx") {
      uploadStatus(`不支持的文件类型 ${ext},仅支持 .pdf / .docx`, "error");
      return;
    }
    if (file.size > 50 * 1024 * 1024) {
      uploadStatus("文件过大,上限 50MB", "error");
      return;
    }
    uploadStatus(`正在上传并解析「${file.name}」…`, "pending");
    const fd = new FormData();
    fd.append("file", file);
    try {
      const r = await fetch("/api/report/upload", { method: "POST", body: fd });
      if (!r.ok) {
        const err = await r.json().catch(() => ({ detail: r.statusText }));
        throw new Error(err.detail || "upload failed");
      }
      const rec = await r.json();
      uploadStatus(`解析完成: ${rec.page_count} 页 / ${rec.tables_count} 表 / ${rec.text_length} 字 — 正在激活…`, "pending");
      await refreshReportHistory();
      await activateReport(rec.id);
    } catch (e) {
      uploadStatus("上传失败: " + (e.message || e), "error");
    }
  }

  // ------- Composer: attach button + drag/drop over the whole input area -------
  function triggerFilePicker() {
    if (el.fileInput) el.fileInput.click();
  }
  if (el.btnAttach) el.btnAttach.addEventListener("click", triggerFilePicker);
  if (el.attachChipChange) el.attachChipChange.addEventListener("click", triggerFilePicker);
  if (el.attachChipRemove) {
    el.attachChipRemove.addEventListener("click", async () => {
      const active = state.report.activeReport;
      if (!active) return;
      if (!confirm(`从当前会话中移除「${active.filename}」?(该文件仍保留在最近上传列表中,不会从服务器删除)`)) return;
      // Server-side: reset the report session so no prompt block is attached
      try { await fetch("/api/report/session/reset", { method: "POST" }); } catch (e) {}
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
      const f = el.fileInput.files && el.fileInput.files[0];
      if (f) uploadFile(f);
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
      const f = e.dataTransfer.files && e.dataTransfer.files[0];
      if (f) uploadFile(f);
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

  function showHistoryPopover() {
    refreshReportHistory();
    el.historyPopover.hidden = false;
    setTimeout(() => el.historyPopover.classList.add("visible"), 10);
  }

  function hideHistoryPopover() {
    el.historyPopover.classList.remove("visible");
    setTimeout(() => { el.historyPopover.hidden = true; }, 150);
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

  el.btnReset.addEventListener("click", async () => {
    if (state.busy) return;
    if (!confirm("开始新对话?当前模式的对话历史将被清空。")) return;
    const url = state.mode === "report" ? "/api/report/session/reset" : "/api/session/reset";
    await fetch(url, { method: "POST" });
    clearBucketChat(state.mode);
    renderEmptyState();
    if (state.mode === "report") {
      await refreshReportStatus();
    }
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

  if (el.btnToggleInspector) el.btnToggleInspector.addEventListener("click", toggleInspector);
  if (el.inspectorCollapseBtn) el.inspectorCollapseBtn.addEventListener("click", () => applyInspectorState(true));
  if (el.inspectorReopen) el.inspectorReopen.addEventListener("click", () => applyInspectorState(false));
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
  // Boot
  // ------------------------------------------------------------------
  loadMeta();
})();
