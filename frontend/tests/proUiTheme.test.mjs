import test from "node:test";
import assert from "node:assert/strict";
import { PROX_WORKBENCH_THEME } from "../src/proUiTheme.js";

test("Pro UI theme exposes page and component tokens for the React page layer", () => {
  const antd = PROX_WORKBENCH_THEME.antd;
  assert.equal(antd.token.colorPrimary, PROX_WORKBENCH_THEME.token.primary);
  assert.equal(antd.token.colorPrimaryHover, PROX_WORKBENCH_THEME.token.primaryHover);
  for (const component of [
    "Button",
    "Input",
    "InputNumber",
    "Select",
    "Checkbox",
    "Radio",
    "Switch",
    "Slider",
    "Steps",
    "Alert",
    "Divider",
    "Modal",
    "Table",
    "Tabs",
    "Segmented",
    "Card",
    "Tooltip",
    "Dropdown",
    "Form",
  ]) {
    assert.ok(antd.components[component], `missing Ant Design component token: ${component}`);
  }
});

test("page inputs inherit the same hover, focus and selected geometry", () => {
  const { components } = PROX_WORKBENCH_THEME.antd;
  assert.equal(components.Input.activeBorderColor, PROX_WORKBENCH_THEME.token.primary);
  assert.equal(components.InputNumber.hoverBorderColor, "#aac5b5");
  assert.equal(components.Select.hoverBorderColor, "#aac5b5");
  assert.equal(components.Select.activeBorderColor, PROX_WORKBENCH_THEME.token.primary);
  assert.equal(components.Select.optionSelectedBg, PROX_WORKBENCH_THEME.token.primaryLight);
  assert.equal(components.Tabs.inkBarColor, PROX_WORKBENCH_THEME.token.primary);
  assert.equal(components.Segmented.itemSelectedColor, PROX_WORKBENCH_THEME.token.primaryDark);
  assert.equal(components.Table.rowHoverBg, "#f4f8f5");
});

test("sidebar and conversation rows use compact Pro UI component tokens", () => {
  const components = PROX_WORKBENCH_THEME.components;
  assert.equal(components.SidebarNav.itemHeight, "30px");
  assert.equal(components.SidebarNav.itemGap, "1px");
  assert.equal(components.Conversations.itemHeight, "38px");
  assert.equal(components.Conversations.itemGap, "1px");
  assert.equal(components.Sender.radius, "14px");
});
