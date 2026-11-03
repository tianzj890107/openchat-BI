import React, { useEffect, useMemo, useState } from "react";
import { Button, ConfigProvider, Divider, Dropdown, Tooltip } from "antd";
import { Conversations } from "@ant-design/x";
import {
  DownOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  PlusOutlined,
  ReloadOutlined,
  SettingOutlined,
  UserOutlined,
} from "@ant-design/icons";
import {
  navigationActiveKey,
  sidebarCollapsedFromPreference,
} from "./proUiBridge.js";

const SIDEBAR_STORAGE_KEY = "bi.sidebarCollapsed.v2";

const SAGE_THEME = {
  token: {
    colorPrimary: "#36745c",
    colorInfo: "#36745c",
    colorSuccess: "#2f7d55",
    colorWarning: "#b45309",
    colorError: "#b42318",
    colorText: "#27332d",
    colorTextSecondary: "#6b756f",
    colorBorder: "#e4e9e5",
    colorBgContainer: "#ffffff",
    borderRadius: 12,
    fontFamily: "PingFang SC, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
  },
};

const NAV_SECTIONS = [
  {
    label: "分析工作区",
    items: [
      { key: "data", label: "智能分析", icon: "bars" },
      { key: "report", label: "报表分析", icon: "report" },
    ],
  },
  {
    label: "业务内容",
    items: [
      { key: "ontology", label: "本体内容", icon: "ontology" },
      { key: "syslog", label: "系统调用记录", icon: "syslog" },
    ],
  },
  {
    label: "设置",
    items: [
      { key: "ontology-adapt", label: "本体适配", icon: "adapt" },
      { key: "sources", label: "数据源", icon: "sources" },
      { key: "model", label: "模型参数", icon: "model" },
      { key: "roles", label: "角色选择", icon: "roles" },
      { key: "memory", label: "记忆管理", icon: "memory" },
    ],
  },
];

export default function ProUiSidebar({
  FeatureGlyph,
  AgentMark,
  fetchRecent,
  requestRecentRefresh,
  recentTimeLabel,
  dispatchRuntime,
  productVersion,
}) {
  // Open the business navigation on first visit while preserving an explicit
  // collapse choice from the legacy runtime.
  const [collapsed, setCollapsed] = useState(() => {
    let saved = null;
    try {
      saved = localStorage.getItem(SIDEBAR_STORAGE_KEY);
    } catch (_) {}
    return sidebarCollapsedFromPreference(
      saved,
      document.body.classList.contains("sidebar-collapsed"),
    );
  });
  const [recent, setRecent] = useState([]);
  const [recentStatus, setRecentStatus] = useState("loading");
  const [active, setActive] = useState(() => document.body.dataset.mode || "data");

  useEffect(() => {
    let disposed = false;
    const refresh = async (mode = document.body.dataset.mode || "data") => {
      if (disposed) return;
      setRecentStatus("loading");
      try {
        const items = await fetchRecent(mode);
        if (disposed) return;
        setRecent(items);
        setRecentStatus(items.length ? "success" : "empty");
      } catch (_) {
        if (disposed) return;
        setRecent([]);
        setRecentStatus("error");
      }
    };
    refresh();
    const onUpdated = (event) => {
      const eventMode = event.detail?.mode || "data";
      if (eventMode !== (document.body.dataset.mode || "data")) return;
      if (!Array.isArray(event.detail?.conversations)) return;
      const activeIds = new Set([...document.querySelectorAll("#recent-list .recent-item.active")].map((node) => node.dataset?.cid));
      setRecent(event.detail.conversations.map((item) => ({
        key: item.id,
        cid: item.id,
        title: item.title || "未命名对话",
        updatedAt: item.updated_at || item.created_at || "",
        active: activeIds.has(item.id),
      })));
      setRecentStatus(event.detail.status || (event.detail.conversations.length ? "success" : "empty"));
    };
    const onMode = (event) => {
      setActive(event.detail?.mode || document.body.dataset.mode || "data");
      refresh(event.detail?.mode || document.body.dataset.mode || "data");
    };
    const onViewChanged = (event) => {
      setActive(navigationActiveKey(
        event.detail?.view || "workspace",
        event.detail?.mode || document.body.dataset.mode || "data",
      ));
    };
    const onRetry = (event) => refresh(event.detail?.mode || document.body.dataset.mode || "data");
    window.addEventListener("bi-conversations-updated", onUpdated);
    window.addEventListener("bi-mode-changed", onMode);
    window.addEventListener("bi-view-changed", onViewChanged);
    window.addEventListener("bi-conversations-retry", onRetry);
    return () => {
      disposed = true;
      window.removeEventListener("bi-conversations-updated", onUpdated);
      window.removeEventListener("bi-mode-changed", onMode);
      window.removeEventListener("bi-view-changed", onViewChanged);
      window.removeEventListener("bi-conversations-retry", onRetry);
    };
  }, [fetchRecent]);

  useEffect(() => {
    document.body.classList.toggle("sidebar-collapsed", collapsed);
    document.body.dataset.sidebarState = collapsed ? "icons" : "expanded";
    try {
      localStorage.setItem(SIDEBAR_STORAGE_KEY, collapsed ? "1" : "0");
    } catch (_) {}
  }, [collapsed]);

  const toggle = () => setCollapsed((value) => !value);

  const conversations = useMemo(() => recent.map((item) => ({
    key: item.key,
    label: (
      <span className="pro-ui-conversation-label">
        <span>{item.title}</span>
        <small>{recentTimeLabel(item.updatedAt)}</small>
      </span>
    ),
    group: "最近对话",
  })), [recent, recentTimeLabel]);

  const activeConversation = recent.find((item) => item.active)?.key;

  const openConversation = (key) => {
    const item = recent.find((entry) => entry.key === key);
    setActive(document.body.dataset.mode || "data");
    setRecent((items) => items.map((current) => ({ ...current, active: current.key === key })));
    const legacyNode = item?.node || document.querySelector(`#recent-list .recent-item[data-cid="${CSS.escape(item?.cid || key)}"]`);
    legacyNode?.click();
  };

  const openAccount = () => document.getElementById("sidebar-account")?.click();
  const accountMenu = {
    items: [
      { key: "account", label: "账号设置", icon: <SettingOutlined /> },
      { key: "profile", label: "个人资料", icon: <UserOutlined /> },
    ],
    onClick: () => openAccount(),
  };

  return (
    <ConfigProvider theme={SAGE_THEME}>
      <aside className={`pro-ui-sidebar ${collapsed ? "is-collapsed" : "is-expanded"}`}>
        <div className="pro-ui-sidebar-scroll">
          <header className="pro-ui-sidebar-brand">
            <button type="button" className="pro-ui-brand-button" onClick={() => window.dispatchEvent(new CustomEvent("bi-composer-focus"))}>
              <AgentMark />
              {!collapsed ? (
                <span className="pro-ui-brand-copy">
                  <strong>智能分析</strong>
                  <small>Ontology Analyst</small>
                </span>
              ) : null}
            </button>
            <Tooltip title={collapsed ? "展开导航" : "收起导航"} placement="right">
              <Button
                type="text"
                size="small"
                className="pro-ui-sidebar-toggle"
                icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
                onClick={toggle}
                aria-label={collapsed ? "展开导航" : "收起导航"}
              />
            </Tooltip>
          </header>

          <Tooltip title={collapsed ? "新对话" : ""} placement="right">
            <button
              type="button"
              className="pro-ui-new-chat"
              onClick={() => document.getElementById("nav-new-chat")?.click()}
            >
              <PlusOutlined />
              {!collapsed ? <span>新对话</span> : null}
            </button>
          </Tooltip>

          <nav className="pro-ui-nav" aria-label="工作台导航">
            {NAV_SECTIONS.map((section) => (
              <section key={section.label} className="pro-ui-nav-section">
                {!collapsed ? <div className="pro-ui-nav-heading">{section.label}</div> : null}
                {section.items.map((item) => (
                  <Tooltip key={item.key} title={collapsed ? item.label : ""} placement="right">
                    <button
                      type="button"
                      className={`pro-ui-nav-item${active === item.key ? " is-active" : ""}`}
                      onClick={() => {
                        setActive(item.key);
                        dispatchRuntime(item.key);
                      }}
                      aria-current={active === item.key ? "page" : undefined}
                    >
                      <FeatureGlyph kind={item.icon} />
                      {!collapsed ? <span>{item.label}</span> : null}
                    </button>
                  </Tooltip>
                ))}
              </section>
            ))}
          </nav>

          {!collapsed ? (
            <>
              <Divider className="pro-ui-sidebar-divider" />
              <section className="pro-ui-recent" aria-label="最近对话">
                <header>
                  <span>最近对话</span>
                  <Tooltip title="刷新历史">
                    <Button
                      type="text"
                      size="small"
                      icon={<ReloadOutlined />}
                      onClick={() => requestRecentRefresh()}
                      aria-label="刷新历史"
                    />
                  </Tooltip>
                </header>
                {recentStatus === "loading" ? (
                  <div className="pro-ui-recent-loading" aria-busy="true">
                    {Array.from({ length: 5 }, (_, index) => <span key={index} />)}
                  </div>
                ) : recentStatus === "error" ? (
                  <button type="button" className="pro-ui-recent-error" onClick={() => requestRecentRefresh()}>
                    历史加载失败，点击重试
                  </button>
                ) : recent.length ? (
                  <Conversations
                    className="pro-ui-conversations"
                    items={conversations}
                    activeKey={activeConversation}
                    groupable
                    onActiveChange={openConversation}
                  />
                ) : (
                  <div className="pro-ui-recent-empty">暂无历史会话</div>
                )}
              </section>
            </>
          ) : (
            <Tooltip title="最近对话" placement="right">
              <button type="button" className="pro-ui-nav-item pro-ui-recent-rail" onClick={toggle}>
                <span className="pro-ui-recent-rail-dot" />
                <span className="pro-ui-recent-rail-dot" />
                <span className="pro-ui-recent-rail-dot" />
              </button>
            </Tooltip>
          )}

          <Dropdown menu={accountMenu} trigger={["click"]} placement="topRight">
            <button type="button" className="pro-ui-account" onClick={(event) => event.stopPropagation()}>
              <span className="pro-ui-account-avatar">分</span>
              {!collapsed ? (
                <span className="pro-ui-account-copy">
                  <strong>分析员</strong>
                  <small>{productVersion}</small>
                </span>
              ) : null}
              {!collapsed ? <DownOutlined className="pro-ui-account-caret" /> : null}
            </button>
          </Dropdown>
        </div>
      </aside>
    </ConfigProvider>
  );
}
