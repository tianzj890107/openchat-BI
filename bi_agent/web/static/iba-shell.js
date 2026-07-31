/* Shared IBA outer-navigation behavior.
 *
 * The three entry pages keep their existing content implementations, but the
 * IBA navigation now has one click path: same-document dashboard/i-Agent
 * switches update immediately, while the sidebar's own CSS controls the
 * only motion in this shell (the hamburger expand/collapse interaction).
 */
(function installIbaShellNavigation() {
  "use strict";

  const DASHBOARD_PATH = "/dashboard.html";
  const COLLAPSE_KEY = "iba.sidebar.collapsed";

  function isCollapsed() {
    const body = document.body;
    return !!body && (body.classList.contains("nav-collapsed") || body.classList.contains("sidebar-collapsed"));
  }

  function saveSidebarState() {
    if (document.body) localStorage.setItem(COLLAPSE_KEY, isCollapsed() ? "collapsed" : "expanded");
  }

  function restoreSidebarState() {
    const saved = localStorage.getItem(COLLAPSE_KEY);
    if (!document.body || (saved !== "collapsed" && saved !== "expanded")) return;
    const collapsed = saved === "collapsed";
    if (document.body.classList.contains("nav-collapsed")) {
      document.body.classList.toggle("nav-collapsed", collapsed);
    }
    if (document.body.classList.contains("sidebar-collapsed")) {
      document.body.classList.toggle("sidebar-collapsed", collapsed);
    }
  }

  function isModifiedClick(event) {
    return event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey;
  }

  function targetUrl(anchor) {
    const raw = anchor.getAttribute("href");
    if (!raw || raw === "#") return null;
    const target = new URL(raw, window.location.href);
    // The dashboard page keeps i-Agent in its existing iframe view. Normalize
    // the legacy /workbench link to that route before the local switch.
    if (anchor.id === "iAgentOpen" && window.location.pathname.endsWith(DASHBOARD_PATH)) {
      return new URL(`${DASHBOARD_PATH}?view=iagent`, window.location.origin);
    }
    return target;
  }

  function animateLocalDashboardSwitch(target) {
    const wantsIagent = target.searchParams.get("view") === "iagent";
    if (wantsIagent && typeof window.showIagentView === "function") {
      window.history.replaceState(null, "", `${DASHBOARD_PATH}?view=iagent`);
      window.showIagentView();
    } else if (!wantsIagent && typeof window.showDashboardView === "function") {
      window.history.replaceState(null, "", DASHBOARD_PATH);
      window.showDashboardView();
    }
  }

  function navigateTo(target) {
    const sameDashboard = window.location.pathname.endsWith(DASHBOARD_PATH)
      && target.pathname.endsWith(DASHBOARD_PATH);
    if (sameDashboard) {
      animateLocalDashboardSwitch(target);
      return;
    }

    // Keep the outer IBA rail in the same expanded/collapsed state after a
    // full document navigation (CEO and dashboard use different class names).
    saveSidebarState();
    window.location.assign(target.href);
  }

  function onNavigationClick(event) {
    if (isModifiedClick(event)) return;
    const anchor = event.target.closest(".sidebar .submenu a");
    if (!anchor) return;
    const target = targetUrl(anchor);
    if (!target || target.origin !== window.location.origin) return;
    event.preventDefault();
    navigateTo(target);
  }

  restoreSidebarState();
  if (document.body) {
    new MutationObserver(saveSidebarState).observe(document.body, { attributes: true, attributeFilter: ["class"] });
  }
  document.addEventListener("click", onNavigationClick, true);
})();
