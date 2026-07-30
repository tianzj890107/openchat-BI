import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { Button, ConfigProvider, Divider, Layout, Menu, Tooltip } from "antd";
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

function Sidebar() {
  const [collapsed, setCollapsed] = useState(document.body.classList.contains("sidebar-collapsed"));
  const [recent, setRecent] = useState(readRecent);
  const [active, setActive] = useState("data");

  useEffect(() => {
    const recentList = document.getElementById("recent-list");
    const observer = recentList ? new MutationObserver(() => setRecent(readRecent())) : null;
    if (recentList) observer.observe(recentList, { childList: true, subtree: true, characterData: true });
    return () => observer?.disconnect();
  }, []);

  const items = useMemo(() => navItems.map((item) => {
    if (item.type) return item;
    return { ...item, label: collapsed ? null : item.label };
  }), [collapsed]);

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
          <Tooltip title={collapsed ? "展开侧栏" : "收起侧栏"}>
            <Button type="text" size="small" icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />} onClick={toggle} />
          </Tooltip>
        </div>
        <Button className="antd-new-chat" block={!collapsed} type="primary" icon={<PlusOutlined />} onClick={() => document.getElementById("nav-new-chat")?.click()}>
          {!collapsed && "新对话"}
        </Button>
        <Menu mode="inline" inlineCollapsed={collapsed} selectedKeys={[active]} items={items} onClick={({ key }) => { setActive(key); dispatchLegacy(key); }} />
        {!collapsed && <>
          <Divider className="antd-sidebar-divider" />
          <div className="antd-sidebar-section-title">最近</div>
          <div className="antd-recent-list">
            {recent.length ? recent.map((item) => <button key={item.key} className="antd-recent-item" onClick={() => item.node?.click()} title={item.title}>{item.title}</button>) : <span className="antd-recent-empty">暂无历史会话</span>}
          </div>
          <button className="antd-account" onClick={() => document.getElementById("sidebar-account")?.click()}><UserOutlined /> <span>分析员</span></button>
        </>}
      </Sider>
    </ConfigProvider>
  );
}

const root = document.getElementById("antd-sidebar-root");
if (root) createRoot(root).render(<Sidebar />);
