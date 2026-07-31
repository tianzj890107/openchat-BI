import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { Button, Card, Collapse, ConfigProvider, Divider, Layout, List, Menu, Progress, Tag, Tooltip } from "antd";
import { ThoughtChain } from "@ant-design/x";
import { Bubble } from "@ant-design/x";
import {
  AppstoreOutlined,
  BarChartOutlined,
  DatabaseOutlined,
  FileSearchOutlined,
  HistoryOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  PlusOutlined,
  SettingOutlined,
  SlidersOutlined,
  UserOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  MinusCircleOutlined,
} from "@ant-design/icons";
import "antd/dist/reset.css";

const { Sider } = Layout;

const navItems = [
  { key: "data", view: "workspace", label: "智能分析", icon: <BarChartOutlined /> },
  { key: "report", view: "workspace", label: "报表分析", icon: <FileSearchOutlined /> },
  { type: "group", label: "内容" },
  { key: "ontology", view: "ontology", label: "本体内容", icon: <AppstoreOutlined /> },
  { key: "syslog", view: "syslog", label: "系统调用记录", icon: <HistoryOutlined /> },
  { type: "divider" },
  { type: "group", label: "设置" },
  { key: "ontology-adapt", view: "ontology-adapt", label: "本体适配", icon: <SlidersOutlined /> },
  { key: "sources", view: "sources", label: "数据源", icon: <DatabaseOutlined /> },
  { key: "model", view: "model", label: "模型参数", icon: <SettingOutlined /> },
  { key: "roles", view: "roles", label: "角色选择", icon: <UserOutlined /> },
  { key: "memory", view: "memory", label: "记忆管理", icon: <HistoryOutlined /> },
];

function getLegacyButton(key) {
  const legacy = document.getElementById("sidebar");
  if (!legacy) return null;
  if (key === "data" || key === "report") {
    return legacy.querySelector(`.mode-btn[data-mode="${key}"]`);
  }
  return legacy.querySelector(`[data-view="${key}"]`);
}

function dispatchLegacy(key) {
  const button = getLegacyButton(key);
  if (button) button.click();
}

function readRecent() {
  const list = document.getElementById("recent-list");
  if (!list) return [];
  return [...list.querySelectorAll(".recent-item")].map((node, index) => ({
    key: node.dataset?.cid || `recent-${index}`,
    title: node.querySelector(".recent-title")?.textContent?.trim() || node.textContent.trim(),
    node,
  }));
}

async function fetchRecent(mode = "data") {
  try {
    const response = await fetch(`/api/conversations?mode=${encodeURIComponent(mode)}`);
    if (!response.ok) return [];
    const payload = await response.json();
    return (payload.conversations || []).map((item) => ({
      key: item.id,
      cid: item.id,
      title: item.title || "未命名对话",
    }));
  } catch (_) {
    return [];
  }
}

function Sidebar() {
  const [collapsed, setCollapsed] = useState(document.body.classList.contains("sidebar-collapsed"));
  const [recent, setRecent] = useState(readRecent);
  const [active, setActive] = useState("data");

  useEffect(() => {
    let disposed = false;
    const refresh = async (mode = document.body.dataset.mode || "data") => {
      const items = await fetchRecent(mode);
      if (!disposed) setRecent(items);
    };
    refresh();
    const recentList = document.getElementById("recent-list");
    const observer = recentList ? new MutationObserver(() => setRecent(readRecent())) : null;
    if (recentList) observer.observe(recentList, { childList: true, subtree: true, characterData: true });
    const onUpdated = (event) => refresh(event.detail?.mode || document.body.dataset.mode || "data");
    window.addEventListener("bi-conversations-updated", onUpdated);
    return () => { disposed = true; observer?.disconnect(); window.removeEventListener("bi-conversations-updated", onUpdated); };
  }, []);

  // Keep the labels in the menu data even while collapsed. Ant Design uses
  // the item label as the collapsed-menu tooltip; hiding it here made those
  // tooltips render as empty bubbles. The label is still visually hidden by
  // Ant Design's inline-collapsed styles.
  const items = useMemo(() => navItems.map((item) => {
    if (item.type) return item;
    return { ...item, label: item.label, title: item.label };
  }), []);

  const toggle = () => {
    document.getElementById("sidebar-collapse")?.click();
    setCollapsed((value) => !value);
  };

  return (
    <ConfigProvider theme={{ token: { colorPrimary: "#1677ff", borderRadius: 8, fontFamily: "PingFang SC, -apple-system, sans-serif" } }}>
      <Sider className="antd-workbench-sidebar" collapsed={collapsed} width={260} collapsedWidth={64} theme="light">
        <div className="antd-sidebar-brand">
          <span className="antd-brand-mark">◆</span>
          {!collapsed && <span><strong>智析</strong><small id="antd-agent-name">bi-analyst</small></span>}
          <Tooltip
            placement="right"
            title={collapsed ? "展开侧栏" : "收起侧栏"}
            color="#fff"
            overlayClassName="antd-workbench-tooltip"
          >
            <Button type="text" size="small" icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />} onClick={toggle} />
          </Tooltip>
        </div>
        <Tooltip
          placement="right"
          title={collapsed ? "新对话" : null}
          color="#fff"
          overlayClassName="antd-workbench-tooltip"
        >
          <Button className="antd-new-chat" block={!collapsed} type="primary" icon={<PlusOutlined />} onClick={() => document.getElementById("nav-new-chat")?.click()}>
            {!collapsed && "新对话"}
          </Button>
        </Tooltip>
        <Menu mode="inline" inlineCollapsed={collapsed} selectedKeys={[active]} items={items} onClick={({ key }) => { setActive(key); dispatchLegacy(key); }} />
        {!collapsed && <>
          <Divider className="antd-sidebar-divider" />
          <div className="antd-sidebar-section-title">最近</div>
          <div className="antd-recent-list">
            {recent.length ? recent.map((item) => <button key={item.key} className="antd-recent-item" onClick={() => item.node?.click() || document.querySelector(`#recent-list .recent-item[data-cid="${CSS.escape(item.cid || item.key)}"]`)?.click()} title={item.title}>{item.title}</button>) : <span className="antd-recent-empty">暂无历史会话</span>}
          </div>
          <button className="antd-account" onClick={() => document.getElementById("sidebar-account")?.click()}><UserOutlined /> <span>分析员</span></button>
        </>}
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
  if (status === "completed") return <CheckCircleOutlined style={{ color: "#28a36a" }} />;
  if (status === "in_progress") return <ClockCircleOutlined style={{ color: "#1677ff" }} />;
  return <MinusCircleOutlined style={{ color: "#b8c0cc" }} />;
}

function WorkflowPanels() {
  const [workflow, setWorkflow] = useState(readWorkflow);
  const [sopOpen, setSopOpen] = useState(false);
  const [todoOpen, setTodoOpen] = useState(false);
  useEffect(() => {
    const targets = [document.getElementById("chat-sop"), document.getElementById("chat-todo")].filter(Boolean);
    const observer = new MutationObserver(() => setWorkflow(readWorkflow()));
    targets.forEach((target) => observer.observe(target, { attributes: true, childList: true, subtree: true, characterData: true }));
    return () => observer.disconnect();
  }, []);
  if (workflow.sopHidden && workflow.todoHidden) return null;
  const done = workflow.sop.filter((item) => item.status === "completed").length;
  const total = workflow.sop.length;
  const chainItems = workflow.sop.map((item) => ({
    key: item.key,
    title: item.text,
    status: item.status === "completed" ? "success" : item.status === "in_progress" ? "pending" : "pending",
    icon: workflowIcon(item.status),
  }));
  return (
    <div className="antd-workflow-panels">
      {!!workflow.sop.length && <Collapse
        ghost
        activeKey={sopOpen ? ["sop"] : []}
        onChange={(keys) => setSopOpen(keys.includes("sop"))}
        items={[{ key: "sop", label: <span className="antd-workflow-title">分析 SOP <Tag color="blue">{done}/{total}</Tag></span>, children: <ThoughtChain items={chainItems} size="small" /> }]}
      />}
      {!!(workflow.todos.length || workflow.questions.length) && <Collapse
        ghost
        activeKey={todoOpen ? ["todo"] : []}
        onChange={(keys) => setTodoOpen(keys.includes("todo"))}
        items={[{ key: "todo", label: <span className="antd-workflow-title">任务清单 <Tag>{workflow.questions.length ? `${workflow.questions.length} 个问题` : `${workflow.todos.length} 项`}</Tag></span>, children: <>
          {!!workflow.questions.length && <List size="small" header="用户提问" dataSource={workflow.questions} renderItem={(item, index) => <List.Item className="antd-question-item" onClick={() => document.querySelector(`#chat-todo .chat-question-item[data-question-turn="${CSS.escape(item.turn)}"]`)?.click()}><Tag>{index + 1}</Tag><span>{item.text}</span></List.Item>} />}
          {!!workflow.todos.length && <List size="small" header="分析进度" dataSource={workflow.todos} renderItem={(item) => <List.Item><span>{workflowIcon(item.status)}</span><span>{item.text}</span></List.Item>} />}
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
  const visibleHtml = rawHtml.replace(/<span class="thinking-line">[\s\S]*?思考中…<\/span>/g, "").trim();
  if (!user && !visibleHtml) return null;
  const hasMarkup = /<\/?[a-z][^>]*>/i.test(visibleHtml);
  const hasMarkdown = /\*\*|__|```|^\s{0,3}#{1,6}\s|^\s*[-+*]\s|\|.+\|/m.test(visibleHtml);
  const contentHtml = !hasMarkup && hasMarkdown && typeof window.legacyRenderMarkdown === "function"
    ? window.legacyRenderMarkdown(visibleHtml)
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

function AntdStep({ name, summary, duration, html }) {
  return <Collapse ghost size="small" items={[{
    key: "step",
    label: <span className="antd-step-label"><b>{name}</b><span>{summary}</span><em>{duration}</em></span>,
    children: <div className="antd-step-html" dangerouslySetInnerHTML={{ __html: html || "" }} />,
  }]} />;
}

function mountStep(step) {
  if (!step || stepRoots.has(step)) return;
  const host = document.createElement("div");
  host.className = "antd-step-host";
  step.appendChild(host);
  const header = step.querySelector(":scope > .step-header");
  const body = step.querySelector(":scope > .step-body");
  const text = (selector) => step.querySelector(selector)?.textContent?.trim() || "";
  const root = createRoot(host);
  const update = () => root.render(<AntdStep name={text(".step-name")} summary={text(".step-summary")} duration={text(".step-duration")} html={body?.innerHTML || ""} />);
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
function mountResultCard(card, type) {
  if (!card || cardRoots.has(card)) return;
  const host = document.createElement("div");
  host.className = "antd-result-card-host";
  card.appendChild(host);
  const head = card.querySelector(`:scope > .${type === "table" ? "table-head" : type === "multi" ? "multidim-head" : "chart-head"}`);
  const title = head?.querySelector(`.${type === "table" ? "table-title" : type === "multi" ? "multidim-title" : "chart-title"}`)?.textContent?.trim() || "分析结果";
  const nodes = type === "chart"
    ? [card.querySelector(":scope > .chart-canvas")]
    : type === "table"
      ? [card.querySelector(":scope > .table-scroll"), card.querySelector(":scope > .table-summary"), card.querySelector(":scope > .table-footnote")]
      : [card.querySelector(":scope > .multidim-toolbar"), card.querySelector(":scope > .multidim-canvas"), card.querySelector(":scope > .multidim-summary"), card.querySelector(":scope > .multidim-footnote")];
  const root = createRoot(host);
  root.render(<Card size="small" title={title} className={`antd-result-card antd-result-${type}`}><div ref={(slot) => { if (slot) nodes.filter(Boolean).forEach((node) => slot.appendChild(node)); }} /></Card>);
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
  const host = document.createElement("div");
  host.className = "antd-dashboard-card-host";
  card.appendChild(host);
  card.classList.add("antd-dashboard-card-mounted");
  const head = card.querySelector(":scope > .dash-head");
  // Keep the semantic badge and title visible in the board, just like the
  // header of the conversation result cards. Other head metadata (source and
  // turn) stays hidden to avoid duplicating technical information.
  const typeTag = head?.querySelector(":scope > .dash-tag");
  const title = head?.querySelector(":scope > .dash-title");
  const nodes = [...card.children].filter((node) => node !== head && node !== host);
  if (typeTag || title) {
    const resultHead = document.createElement("div");
    resultHead.className = "antd-dashboard-result-head";
    if (typeTag) resultHead.appendChild(typeTag);
    if (title) resultHead.appendChild(title);
    nodes.unshift(resultHead);
  }
  const root = createRoot(host);
  root.render(<DashboardInnerBubble nodes={nodes} />);
  if (head) head.style.display = "none";
  cardRoots.set(card, root);
}
window.antdDashboardCardMount = mountDashboardCard;

function enhanceLegacyTree(container) {
  if (!container) return;
  container.querySelectorAll(":scope > .msg:not(.antd-message-enhanced)").forEach((node) => {
    mountMessage(node, node.classList.contains("msg-user") ? "user" : "assistant", node.querySelector(".msg-iter")?.textContent?.replace(/[^0-9]/g, ""));
  });
  container.querySelectorAll(".step:not(.antd-step-enhanced)").forEach(mountStep);
  container.querySelectorAll(":scope > .chart-card:not(.antd-result-card-host), :scope > .table-card:not(.antd-result-card-host), :scope > .multidim-card:not(.antd-result-card-host)").forEach((node) => {
    mountResultCard(node, node.classList.contains("table-card") ? "table" : node.classList.contains("multidim-card") ? "multi" : "chart");
  });
  container.querySelectorAll(":scope > .dash-card:not(.antd-dashboard-card-host):not(.antd-dashboard-question-hidden)").forEach(mountDashboardCard);
}

function observeLegacySurface(id) {
  const container = document.getElementById(id);
  if (!container) return;
  enhanceLegacyTree(container);
  const observer = new MutationObserver(() => enhanceLegacyTree(container));
  observer.observe(container, { childList: true, subtree: true });
}

const root = document.getElementById("antd-sidebar-root");
if (root) createRoot(root).render(<Sidebar />);
const workflowRoot = document.getElementById("antd-workflow-root");
if (workflowRoot) createRoot(workflowRoot).render(<WorkflowPanels />);
observeLegacySurface("chat-scroll");
observeLegacySurface("dashboard-list");
