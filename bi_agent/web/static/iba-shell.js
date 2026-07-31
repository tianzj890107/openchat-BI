/* Shared IBA outer-navigation behavior.
 *
 * The three entry pages keep their existing content implementations, but the
 * IBA navigation now has one click path: same-document dashboard/i-Agent
 * switches animate in place, while cross-page navigation uses the same short
 * exit transition before changing location.
 */
(function installIbaShellNavigation() {
  "use strict";

  const DASHBOARD_PATH = "/dashboard.html";

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
    const content = document.querySelector(".content");
    if (content) {
      content.classList.remove("iba-view-switching");
      void content.offsetWidth;
      content.classList.add("iba-view-switching");
      window.setTimeout(() => content.classList.remove("iba-view-switching"), 280);
    }

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

    document.documentElement.classList.add("iba-route-leaving");
    window.setTimeout(() => { window.location.assign(target.href); }, 180);
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

  document.addEventListener("click", onNavigationClick, true);
})();
