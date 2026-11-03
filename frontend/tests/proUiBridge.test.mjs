import test from "node:test";
import assert from "node:assert/strict";
import {
  composerActionState,
  navigationActiveKey,
  normalizeComposerValue,
  sidebarCollapsedFromPreference,
  welcomePromptsFromHints,
} from "../src/proUiBridge.js";

test("composer can submit only when it has text and is not busy", () => {
  assert.deepEqual(
    composerActionState({ value: "  本月收入  ", busy: false, disabled: false }),
    { text: "  本月收入  ", canSubmit: true, canCancel: false, submitLabel: "发送" },
  );
  assert.equal(composerActionState({ value: "   ", busy: false }).canSubmit, false);
  assert.equal(composerActionState({ value: "查询", busy: true }).canSubmit, false);
  assert.equal(composerActionState({ value: "查询", disabled: true }).canSubmit, false);
});

test("busy composer exposes stop semantics instead of a second submit", () => {
  const state = composerActionState({ value: "查询", busy: true });
  assert.equal(state.canCancel, true);
  assert.equal(state.submitLabel, "停止");
});

test("composer values are normalized without trimming user-visible text", () => {
  assert.equal(normalizeComposerValue(null), "");
  assert.equal(normalizeComposerValue(undefined), "");
  assert.equal(normalizeComposerValue("  keep spaces  "), "  keep spaces  ");
});

test("welcome prompts preserve order and remove blank or duplicate hints", () => {
  const prompts = welcomePromptsFromHints(["看收入", "", "看收入", "  毛利  ", null]);
  assert.deepEqual(prompts.map((item) => item.label), ["看收入", "毛利"]);
  assert.equal(prompts[0].key, "welcome-prompt-0");
  assert.equal(prompts[1].key, "welcome-prompt-1");
});

test("navigation active key follows workspace mode and standalone pages", () => {
  assert.equal(navigationActiveKey("workspace", "data"), "data");
  assert.equal(navigationActiveKey("workspace", "report"), "report");
  assert.equal(navigationActiveKey("sources", "report"), "sources");
  assert.equal(navigationActiveKey("", ""), "data");
});

test("sidebar restores an explicit preference and falls back to the shell state", () => {
  assert.equal(sidebarCollapsedFromPreference("1", false), true);
  assert.equal(sidebarCollapsedFromPreference("0", true), false);
  assert.equal(sidebarCollapsedFromPreference(null, true), true);
  assert.equal(sidebarCollapsedFromPreference(null, false), false);
  assert.equal(sidebarCollapsedFromPreference("unknown", true), true);
});
