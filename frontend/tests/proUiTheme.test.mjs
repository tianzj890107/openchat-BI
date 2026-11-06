import test from "node:test";
import assert from "node:assert/strict";
import { PROX_WORKBENCH_THEME } from "../src/proUiTheme.js";

test("Pro UI theme keeps brand tokens and only business-density component overrides", () => {
  const antd = PROX_WORKBENCH_THEME.antd;
  assert.equal(antd.token.colorPrimary, PROX_WORKBENCH_THEME.token.primary);
  assert.equal(antd.token.colorPrimaryHover, PROX_WORKBENCH_THEME.token.primaryHover);
  assert.deepEqual(Object.keys(antd.components).sort(), ["Form", "Table"]);
  for (const component of ["Button", "Input", "InputNumber", "Select", "Tabs", "Segmented", "Switch", "Slider"]) {
    assert.equal(antd.components[component], undefined, `unexpected shape override: ${component}`);
  }
});

test("generic controls inherit platform focus and selection tokens", () => {
  const antd = PROX_WORKBENCH_THEME.antd;
  assert.equal(antd.token.controlHeight, 36);
  assert.equal(antd.token.borderRadius, 12);
  assert.equal(antd.components.Form.labelColor, PROX_WORKBENCH_THEME.token.text);
  assert.equal(antd.components.Table.rowHoverBg, "#f4f8f5");
});

test("sidebar and conversation rows use compact Pro UI component tokens", () => {
  const components = PROX_WORKBENCH_THEME.components;
  assert.equal(components.SidebarNav.itemHeight, "30px");
  assert.equal(components.SidebarNav.itemGap, "1px");
  assert.equal(components.Conversations.itemHeight, "38px");
  assert.equal(components.Conversations.itemGap, "1px");
  assert.equal(components.Sender.radius, "14px");
});
