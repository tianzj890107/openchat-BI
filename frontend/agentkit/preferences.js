const preferenceKey = "agentkit.analysisPreferences";

export function readPreferences() {
  try {
    const analysis = JSON.parse(localStorage.getItem(preferenceKey) || "{}");
    return {...analysis, name: localStorage.getItem("bi.userName") || "", theme: localStorage.getItem("bi.theme.v2") || "light"};
  } catch { return {name: "", theme: "light"}; }
}

export function writePreferences({name, theme, user_role, agent_pref}) {
  try {
    localStorage.setItem("bi.userName", name);
    localStorage.setItem("bi.theme.v2", theme);
    localStorage.setItem(preferenceKey, JSON.stringify({user_role, agent_pref}));
  } catch { /* restricted browser storage */ }
}
