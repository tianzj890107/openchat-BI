import {hydrateTurns, turnsFromSnapshot} from "./state.js";

const escapeMarkdown = (value) => value.replace(/([\\`*_[\]<>])/g, "\\$1");

function documentFrom(html) {
  const template = document.createElement("template");
  template.innerHTML = html || "";
  return template.content;
}

function text(node) {
  if (!node) return "";
  const copy = node.cloneNode(true);
  copy.querySelectorAll("script,style,button,template,.step,.turn-sop,.dash-card,.thinking-line").forEach((entry) => entry.remove());
  copy.querySelectorAll("br,p,li,tr,h1,h2,h3,h4").forEach((entry) => entry.after("\n"));
  return copy.textContent.replace(/\n{3,}/g, "\n\n").trim();
}

function parseJson(value, fallback = null) {
  try { return JSON.parse(value); } catch { return fallback; }
}

function legacyTool(card, id) {
  const tool = {id, name: "历史结果", status: "done"};
  if (card.dataset.chartJson) {
    let spec;
    try { spec = parseJson(decodeURIComponent(card.dataset.chartJson)); } catch { return null; }
    if (!spec) return null;
    return card.classList.contains("dash-multidim") ? {...tool, multiChart: spec} : {...tool, chart: spec};
  }
  const table = card.querySelector("table");
  if (!table) return null;
  return {...tool, table: {
    title: text(card.querySelector(".dash-title,.table-title")) || "明细表",
    columns: Array.from(table.querySelectorAll("thead th"), (cell) => ({label: text(cell)})),
    rows: Array.from(table.querySelectorAll("tbody tr"), (row) => Array.from(row.cells, text)),
    summary: text(card.querySelector(".table-summary")),
    footnote: text(card.querySelector(".table-footnote")),
    source_note: text(card.querySelector(".dash-source")).replace(/^Source ·\s*/, ""),
  }};
}

function signature(tool) {
  for (const kind of ["table", "chart", "multiChart"]) {
    if (tool[kind]) return `${kind}:${JSON.stringify(tool[kind])}`;
  }
  return "";
}

export function restoreTurns(snapshot, messages, assets = {}) {
  const structured = turnsFromSnapshot(snapshot);
  const chat = documentFrom(assets.chat_html);
  const board = documentFrom(assets.dashboard_html);
  const questions = [...chat.querySelectorAll(".msg-user")];
  // Old snapshots may contain a richer transcript than the model context, or
  // no model context at all. Read only the contents of recognized elements.
  const transcript = [];
  let current;
  for (const bubble of chat.querySelectorAll(".msg-user,.msg-assistant")) {
    const body = text(bubble.querySelector(".msg-body"));
    if (bubble.classList.contains("msg-user")) {
      current = {user: body, answers: []};
      transcript.push(current);
    } else if (current && body) {
      current.answers.push(escapeMarkdown(body));
    }
  }
  const hydrated = hydrateTurns(messages);
  const recovered = transcript.map((entry, index) => {
    const base = hydrated[index];
    return {
      id: base?.id || `restored-${index}`, user: entry.user || base?.user || "", status: "done",
      assistant: {
        text: base?.assistant.text || entry.answers.join("\n\n"),
        thinking: base?.assistant.thinking || "",
        tools: base?.assistant.tools || [],
      },
    };
  });
  const fallback = recovered.length ? [...recovered, ...hydrated.slice(recovered.length)] : hydrated;
  let turns = structured || fallback;
  if (structured && structured.length < fallback.length) {
    // Earlier AgentKit snapshots truncated the saved prefix. Recover any
    // remaining questions from the persisted transcript when the prefix agrees.
    const prefixMatches = structured.every(({user}, index) =>
      fallback[index].user === user || fallback[index].user.endsWith(`\n${user}`));
    if (prefixMatches) turns = [...structured, ...fallback.slice(structured.length)];
  }
  const tags = new Map(questions.map((question, index) => [question.dataset.turn || String(index + 1), index]));
  const indexOf = (node) => {
    const holder = node.closest("[data-turn]");
    const tag = holder?.dataset.turn;
    return tag ? (tags.get(tag) ?? Number(tag) - 1) : turns.length - 1;
  };
  const sections = [["conclusion", "结论"], ["rootcause", "根因分析"], ["actions", "行动建议"]];
  for (const [position, card] of [...board.querySelectorAll(".dash-table,.dash-chart,.dash-multidim")].entries()) {
    const turn = turns[indexOf(card)];
    if (!turn) continue;
    const tool = legacyTool(card, `${turn.id}:legacy-result:${position}`);
    if (tool && !turn.assistant.tools.some((existing) => signature(existing) === signature(tool))) {
      turn.assistant.tools.push(tool);
    }
  }
  for (const [kind, title] of sections) {
    for (const card of [...board.querySelectorAll(`.dash-${kind}`), ...chat.querySelectorAll(`.dash-${kind}`)]) {
      const turn = turns[indexOf(card)];
      const content = text(card.querySelector(".dash-body") || card);
      if (!turn || !content || turn.sections?.some((section) => section.kind === kind)) continue;
      turn.sections = [...(turn.sections || []), {kind, title, content}];
    }
  }
  for (const node of chat.querySelectorAll(".turn-sop[data-sop]")) {
    const turn = turns[indexOf(node)];
    const todos = parseJson(node.dataset.sop, []);
    if (turn && !turn.sop && Array.isArray(todos)) turn.sop = {todos};
  }
  const last = turns.at(-1);
  if (last && !last.sop && assets.sop_steps?.length) last.sop = {todos: assets.sop_steps};
  // Attach old saved ontology evidence to its originating tool when available.
  const tools = documentFrom(assets.tools_html);
  const ontology = documentFrom(assets.ontology_html);
  const savedEntities = [...ontology.querySelectorAll(".entity-card[data-code]")];
  const chatTools = [...chat.querySelectorAll(".step[data-turn]")];
  const steps = chatTools.length ? chatTools : [...tools.querySelectorAll(".step[data-turn]")];
  for (const [position, node] of steps.entries()) {
    if (node.dataset.reasoning) continue;
    const turn = turns[indexOf(node)];
    if (!turn) continue;
    const name = text(node.querySelector(".step-name"));
    const input = text(node.querySelector(".tool-io-input pre"));
    const output = text(node.querySelector(".tool-io-output pre"));
    const existing = turn.assistant.tools.find((tool) => tool.id === (node.dataset.activityId || node.dataset.toolId) ||
      (tool.name === name && input && String(tool.input || "").replace(/\s/g, "") === input.replace(/\s/g, "")));
    const entities = [...node.querySelectorAll(".chip[data-code]")].map((chip) => {
      const match = savedEntities.find((item) => chip.dataset.entityKey
        ? item.dataset.entityKey === chip.dataset.entityKey : item.dataset.code === chip.dataset.code);
      return {
        code: chip.dataset.code, kind: match?.dataset.kind || [...chip.classList].find((kind) => kind !== "chip"),
        name: match?.dataset.name || text(chip.querySelector(".chip-name")),
        repository_id: match?.dataset.repositoryId || "",
      };
    });
    if (existing) {
      if (!existing.output && output) existing.output = output;
      if (!existing.entities?.length && entities.length) existing.entities = entities;
    } else if (name) {
      turn.assistant.tools.push({id: `${turn.id}:legacy-tool:${position}`, name, input, output, entities, status: "done"});
    }
  }
  return turns;
}
