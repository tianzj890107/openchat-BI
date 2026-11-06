import React, { useEffect, useMemo, useState } from "react";
import { Skeleton, Tooltip } from "antd";
import {
  Button as ProXButton,
  ProXConfigProvider,
  ProXConversations,
  ProXSearchDialog,
  ProXSidebarLayout,
  ProXSidebarNav,
  ProXUserMenu,
} from "@pro-ui/x-react";
import {
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  PlusOutlined,
  ReloadOutlined,
  SearchOutlined,
  SettingOutlined,
  UserOutlined,
} from "@ant-design/icons";
import {
  navigationActiveKey,
  sidebarCollapsedFromPreference,
} from "./proUiBridge.js";
import { PROX_WORKBENCH_THEME } from "./proUiTheme.js";

function SidebarPanelIcon() {
  return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="3" /><path d="M10 4v16" /></svg>;
}

const SIDEBAR_STORAGE_KEY = "bi.sidebarCollapsed.v2";
const SIDEBAR_WIDTH_STORAGE_KEY = "bi.sidebarWidth.v1";

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

const ALL_NAV_ITEMS = NAV_SECTIONS.flatMap((section) => section.items);

function readStoredWidth() {
  try {
    const saved = Number(localStorage.getItem(SIDEBAR_WIDTH_STORAGE_KEY));
    return Number.isFinite(saved) ? Math.min(380, Math.max(248, saved)) : 272;
  } catch (_) {
    return 272;
  }
}

export default function ProUiSidebar({
  FeatureGlyph,
  AgentMark,
  fetchRecent,
  requestRecentRefresh,
  recentTimeLabel,
  dispatchRuntime,
  productVersion,
}) {
  // The layout component owns collapse and resize mechanics. The runtime body
  // class is mirrored only because the legacy page router still keys a few
  // responsive rules from it.
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
  const [width, setWidth] = useState(readStoredWidth);
  const [recent, setRecent] = useState([]);
  const [recentStatus, setRecentStatus] = useState("loading");
  const [active, setActive] = useState(() => document.body.dataset.mode || "data");
  const [searchOpen, setSearchOpen] = useState(false);

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

  useEffect(() => {
    try {
      localStorage.setItem(SIDEBAR_WIDTH_STORAGE_KEY, String(width));
    } catch (_) {}
  }, [width]);

  const toggle = () => setCollapsed((value) => !value);
  const openNewChat = () => document.getElementById("nav-new-chat")?.click();
  const openConversation = (key) => {
    const item = recent.find((entry) => entry.key === key);
    setActive(document.body.dataset.mode || "data");
    setRecent((items) => items.map((current) => ({ ...current, active: current.key === key })));
    const legacyNode = item?.node || document.querySelector(`#recent-list .recent-item[data-cid="${CSS.escape(item?.cid || key)}"]`);
    legacyNode?.click();
    setSearchOpen(false);
  };

  const conversations = useMemo(() => recent.map((item) => ({
    key: item.key,
    label: (
      <span className="pro-ui-conversation-label">
        <span className="pro-ui-conversation-title">{item.title}</span>
        <small>{recentTimeLabel(item.updatedAt)}</small>
      </span>
    ),
  })), [recent, recentTimeLabel]);

  const searchItems = useMemo(() => recent.map((item) => ({
    key: item.key,
    label: item.title,
    searchText: item.title,
    description: recentTimeLabel(item.updatedAt),
    group: "最近对话",
    icon: <FeatureGlyph kind="syslog" />,
  })), [recent, recentTimeLabel, FeatureGlyph]);

  const activeConversation = recent.find((item) => item.active)?.key;
  const openAccount = () => document.getElementById("sidebar-account")?.click();
  const accountItems = [
    { key: "account", label: "账号设置", icon: <SettingOutlined /> },
    { key: "profile", label: "个人资料", icon: <UserOutlined /> },
  ];
  const selectNav = (key) => {
    setActive(key);
    dispatchRuntime(key);
  };

  const navigation = (
    <div className="pro-ui-nav" aria-label="工作台导航">
      {NAV_SECTIONS.map((section) => (
        <ProXSidebarNav
          key={section.label}
          className="pro-ui-nav-component"
          items={section.items.map((item) => ({
            id: item.key,
            title: item.label,
            icon: <FeatureGlyph kind={item.icon} />,
          }))}
          activeId={active}
          onSelect={selectNav}
          collapsed={collapsed}
          title={section.label}
          type="sidebar"
          tooltip={collapsed}
        />
      ))}
    </div>
  );

  const rail = (
    <div className="pro-ui-sidebar-rail">
      <Tooltip title="智能分析" placement="right">
        <button
          type="button"
          className="pro-ui-rail-brand"
          onClick={() => window.dispatchEvent(new CustomEvent("bi-composer-focus"))}
          aria-label="智能分析"
        >
          <AgentMark />
        </button>
      </Tooltip>
      <Tooltip title="展开导航" placement="right">
        <ProXButton
          type="text"
          className="pro-ui-rail-action"
          icon={<MenuUnfoldOutlined />}
          onClick={() => setCollapsed(false)}
          aria-label="展开导航"
        />
      </Tooltip>
      <Tooltip title="新对话" placement="right">
        <ProXButton
          type="text"
          className="pro-ui-rail-action"
          icon={<PlusOutlined />}
          onClick={openNewChat}
          aria-label="新对话"
        />
      </Tooltip>
      <ProXSidebarNav
        type="rail"
        items={ALL_NAV_ITEMS.map((item) => ({
          id: item.key,
          title: item.label,
          icon: <FeatureGlyph kind={item.icon} />,
        }))}
        activeId={active}
        onSelect={selectNav}
        tooltip
      />
      <Tooltip title="搜索最近对话" placement="right">
        <ProXButton
          type="text"
          className="pro-ui-rail-action"
          icon={<SearchOutlined />}
          onClick={() => setSearchOpen(true)}
          aria-label="搜索最近对话"
        />
      </Tooltip>
      <ProXUserMenu
        name="分析员"
        description={productVersion}
        avatar={<span className="pro-ui-account-avatar">分</span>}
        compact
        items={accountItems}
        onAction={openAccount}
      />
    </div>
  );

  const brandHeader = (
    <header className="pro-ui-sidebar-brand">
      <button
        type="button"
        className="pro-ui-brand-button"
        onClick={() => window.dispatchEvent(new CustomEvent("bi-composer-focus"))}
      >
        <AgentMark />
        <span className="pro-ui-brand-copy">
          <strong>智能分析</strong>
          <small>Ontology Analyst</small>
        </span>
      </button>
      <Tooltip title={collapsed ? "展开导航" : "收起导航"} placement="right">
        <ProXButton
          type="text"
          className="pro-ui-sidebar-toggle"
          icon={<SidebarPanelIcon />}
          onClick={toggle}
          aria-label={collapsed ? "展开导航" : "收起导航"}
        />
      </Tooltip>
    </header>
  );

  return (
    <ProXConfigProvider theme={PROX_WORKBENCH_THEME}>
      <ProXSidebarLayout
        className="pro-ui-sidebar-layout"
        width={width}
        onWidthChange={setWidth}
        collapsed={collapsed}
        onCollapsedChange={setCollapsed}
        minWidth={248}
        maxWidth={380}
        collapsedWidth={64}
        railWidth={56}
        resizable
        rail={collapsed ? rail : undefined}
        header={brandHeader}
        footer={(
          <ProXUserMenu
            name="分析员"
            description={productVersion}
            avatar={<span className="pro-ui-account-avatar">分</span>}
            items={accountItems}
            onAction={openAccount}
          />
        )}
      >
        <div className="pro-ui-sidebar-content">
          <ProXButton
            block
            icon={<PlusOutlined />}
            className="pro-ui-new-chat"
            onClick={openNewChat}
          >
            新对话
          </ProXButton>

          {navigation}

          <section className="pro-ui-recent" aria-label="最近对话">
            <header className="pro-ui-recent-header">
              <span>最近对话</span>
              <div className="pro-ui-recent-actions">
                <Tooltip title="搜索最近对话">
                  <ProXButton
                    type="text"
                    icon={<SearchOutlined />}
                    onClick={() => setSearchOpen(true)}
                    aria-label="搜索最近对话"
                  />
                </Tooltip>
                <Tooltip title="刷新历史">
                  <ProXButton
                    type="text"
                    icon={<ReloadOutlined />}
                    onClick={() => requestRecentRefresh()}
                    aria-label="刷新历史"
                  />
                </Tooltip>
              </div>
            </header>
            {recentStatus === "loading" ? (
              <Skeleton className="pro-ui-recent-loading" active title={false} paragraph={{ rows: 5 }} />
            ) : recentStatus === "error" ? (
              <ProXButton block onClick={() => requestRecentRefresh()}>
                历史加载失败，点击重试
              </ProXButton>
            ) : recent.length ? (
              <ProXConversations
                rootClassName="pro-ui-conversations"
                items={conversations}
                activeKey={activeConversation}
                onActiveChange={openConversation}
              />
            ) : (
              <div className="pro-ui-recent-empty">暂无历史会话</div>
            )}
          </section>
        </div>
      </ProXSidebarLayout>

      <ProXSearchDialog
        open={searchOpen}
        onOpenChange={setSearchOpen}
        items={searchItems}
        onSelect={(item) => openConversation(item.key)}
        title="搜索最近对话"
        placeholder="输入会话标题"
        emptyText="没有匹配的会话"
      />
    </ProXConfigProvider>
  );
}
