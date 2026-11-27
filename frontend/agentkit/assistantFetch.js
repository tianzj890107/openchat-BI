// 储小策助手复用完整 AgentKit 工作台：把通用工作台的接口适配到 360 专用接口，
// 客户入口未开放的配置/报表/会话写入不产生网络请求。
const JSON_HEADERS = {"Content-Type": "application/json"};

function jsonResponse(value) {
  return new Response(JSON.stringify(value), {status: 200, headers: JSON_HEADERS});
}

export function installAssistantFetch(win = window) {
  const original = win.fetch.bind(win);
  const base = () => String(win.APP_ROOT_PATH || "").replace(/\/+$/, "");
  const api = (path) => `${base()}/${String(path).replace(/^\/+/, "")}`;

  win.fetch = async function assistantFetch(input, init = {}) {
    const raw = typeof input === "string" ? input : input?.url || "";
    const url = new URL(raw, win.location.href);
    const path = url.pathname;
    const method = String(init.method || input?.method || "GET").toUpperCase();

    if (method === "POST" && /\/api\/chat$/.test(path)) {
      const body = JSON.parse(init.body || "{}");
      body.analysis360_direct = true;
      return original(api("api/analysis360/chat"), {...init, body: JSON.stringify(body)});
    }
    if (method === "POST" && /\/api\/choice$/.test(path)) {
      return original(api("api/analysis360/choice"), init);
    }
    if (method === "GET" && /\/api\/conversations$/.test(path)) {
      const response = await original(api("api/analysis360/history"), {headers: {Accept: "application/json"}});
      const data = await response.json().catch(() => ({conversations: []}));
      const conversations = (Array.isArray(data.conversations) ? data.conversations : []).map((item) => ({
        id: item.id, title: item.title, updated_at: item.updated, created_at: item.updated,
        first_user_question: item.title, turn_count: 0, mode: "data",
      }));
      return jsonResponse({conversations});
    }
    const activate = path.match(/\/api\/conversations\/([^/]+)\/activate$/);
    if (method === "POST" && activate) {
      const id = decodeURIComponent(activate[1]);
      const response = await original(api(`api/analysis360/history/${encodeURIComponent(id)}`));
      if (!response.ok) return jsonResponse({session_id: id, messages: [], agentkit: {turns: []}});
      const record = await response.json();
      return jsonResponse({
        session_id: id, mode: "data", runtime_mode: "data", messages: [],
        agentkit: {version: 1, turns: Array.isArray(record.turns) ? record.turns : []},
        awaiting_choice: false,
      });
    }
    if (method === "GET" && /\/api\/conversations\/[^/]+\/assets$/.test(path)) {
      return jsonResponse({assets: []});
    }
    if (method === "POST" && /\/api\/conversations\/save$/.test(path)) {
      const body = JSON.parse(init.body || "{}");
      return original(api("api/analysis360/history"), {
        method: "POST", headers: JSON_HEADERS,
        body: JSON.stringify({
          session_id: body.session_id || "",
          title: body.title || body.first_user_question || "",
          turns: body.agentkit?.turns || [],
        }),
      });
    }
    if (method === "GET" && /\/api\/config$/.test(path)) {
      const meta = await original(api("api/meta")).then((item) => item.json()).catch(() => ({}));
      const model = meta?.agent?.model || "团队模型";
      return jsonResponse({
        current: {model_key: model, max_tokens: 8000, temperature: 0.5, thinking: false},
        models: [{model_key: model, label: model, max_output_tokens: 200000, supports_thinking: true}],
      });
    }
    if (method === "GET" && /\/api\/sources$/.test(path)) {
      return jsonResponse({
        ontology: {active: "360", options: ["360"], remote_repositories: []},
        database: {active: "360", options: ["360"], remote_databases: [], local_postgres: null},
        retrieval: {mode: "semantic", graph: {options: []}},
        doris: {value: "", active: false},
      });
    }
    if (method === "GET" && /\/api\/report\/status/.test(path)) {
      return jsonResponse({active_reports: [], with_db: true, has_session: false});
    }
    if (method === "PUT" && /\/api\/(sources|roles|config)$/.test(path)) {
      return jsonResponse({changed: [], ok: true});
    }
    if (/\/api\/report\//.test(path)) return jsonResponse({});
    return original(input, init);
  };
}
