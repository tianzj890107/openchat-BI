import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Alert,
  Checkbox,
  Divider,
  Flex,
  Input,
  InputNumber,
  Radio,
  Segmented,
  Select,
  Slider,
  Steps,
  Switch,
  Tabs,
  Tag,
  Tooltip,
} from "antd";
import {
  Button as ProXButton,
  ProXConfigProvider,
} from "@pro-ui/x-react";
import {
  CloseOutlined,
  CompressOutlined,
  DeleteOutlined,
  ExpandOutlined,
} from "@ant-design/icons";
import { PROX_WORKBENCH_THEME } from "./proUiTheme.js";

const CONTROL_SELECTOR = [
  "button.btn",
  "button.dashboard-collapse",
  "button.dashboard-reopen",
  "button.modal-close",
  "button.history-close",
  "button.history-use",
  "button.history-del",
  "select.settings-select",
  "select.rg-input",
  "input.settings-input",
  "input.settings-slider",
  "input.rg-input",
  "textarea.rg-input",
  ".rg-stepper",
  ".rg-note",
  ".settings-divider",
  "#view-model .toggle",
  "#view-account .toggle",
  ".rg-check",
  ".role-option",
  ".page-header.tab-bar",
  ".workspace-pane-switcher",
  ".ontology-filters",
].join(",");

const SKIP_SELECTOR = [
  "#antd-sidebar-root",
  ".runtime-sidebar-bridge",
  ".composer",
  ".attach-row",
  ".pro-ui-control-host",
].join(",");

const bridgedRoots = new WeakMap();
const mirroredProperties = new WeakSet();
const globalState = {
  observer: null,
  roots: new Set(),
};

function readBooleanAttribute(element, name) {
  return element.hasAttribute(name);
}

function mirrorPropertyWrites(element, property) {
  if (!element || mirroredProperties.has(element)) return;
  const descriptor = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(element), property);
  if (!descriptor?.get || !descriptor?.set) return;
  Object.defineProperty(element, property, {
    configurable: true,
    enumerable: descriptor.enumerable,
    get() {
      return descriptor.get.call(this);
    },
    set(value) {
      descriptor.set.call(this, value);
      this.dispatchEvent(new Event("pro-ui-mirror-sync"));
    },
  });
  mirroredProperties.add(element);
}

function useLegacySnapshot(element, read) {
  const readRef = useRef(read);
  readRef.current = read;
  const [snapshot, setSnapshot] = useState(() => read());

  useEffect(() => {
    let frame = 0;
    let lastKey = "";
    const sync = () => {
      if (frame) return;
      frame = window.setTimeout(() => {
        frame = 0;
        const next = readRef.current();
        const key = JSON.stringify(next);
        if (key === lastKey) return;
        lastKey = key;
        setSnapshot(next);
      }, 0);
    };
    const observer = new MutationObserver(sync);
    observer.observe(element, {
      attributes: true,
      attributeFilter: ["class", "disabled", "hidden", "aria-selected", "title", "style"],
      childList: true,
      characterData: true,
      subtree: true,
    });
    const timer = window.setInterval(sync, 240);
    element.addEventListener("input", sync);
    element.addEventListener("change", sync);
    element.addEventListener("pro-ui-mirror-sync", sync);
    sync();
    return () => {
      window.clearInterval(timer);
      window.clearTimeout(frame);
      observer.disconnect();
      element.removeEventListener("input", sync);
      element.removeEventListener("change", sync);
      element.removeEventListener("pro-ui-mirror-sync", sync);
    };
  }, [element]);

  return snapshot;
}

function dispatchNativeChange(element, eventName = "change") {
  element.dispatchEvent(new Event(eventName, { bubbles: true }));
}

function buttonSnapshot(element) {
  const selected = element.classList.contains("active")
    || element.classList.contains("is-selected")
    || element.classList.contains("is-on")
    || element.classList.contains("selected")
    || element.getAttribute("aria-selected") === "true";
  return {
    text: element.textContent.replace(/\s+/g, " ").trim(),
    title: element.getAttribute("title") || "",
    disabled: !!element.disabled,
    hidden: readBooleanAttribute(element, "hidden")
      || element.style.display === "none"
      || element.closest("[hidden]") !== null,
    selected,
    primary: element.classList.contains("btn-primary"),
    ghost: element.classList.contains("btn-ghost"),
    filter: element.classList.contains("ontology-filter"),
    tab: element.classList.contains("tab")
      || element.classList.contains("workspace-pane-tab"),
    role: element.classList.contains("role-option"),
  };
}

function ButtonIcon({ element }) {
  if (element.classList.contains("settings-key-clear")
      || element.classList.contains("modal-close")
      || element.classList.contains("history-close")) {
    return <CloseOutlined />;
  }
  if (element.classList.contains("dashboard-clear")) return <DeleteOutlined />;
  if (element.classList.contains("dashboard-collapse")) return <CompressOutlined />;
  if (element.classList.contains("dashboard-reopen")) return <ExpandOutlined />;
  return null;
}

function ProUiButtonControl({ element }) {
  const snapshot = useLegacySnapshot(element, () => buttonSnapshot(element));

  const special = element.classList.contains("settings-key-clear")
    || element.classList.contains("modal-close")
    || element.classList.contains("history-close");
  const icon = <ButtonIcon element={element} />;
  const label = snapshot.text && !(special && /^[×✕]$/.test(snapshot.text)) ? snapshot.text : "";
  const type = special
    ? "text"
    : snapshot.primary
      ? "primary"
      : snapshot.tab || snapshot.filter
        ? "text"
        : "default";
  const className = [
    "pro-ui-page-button",
    snapshot.filter ? "pro-ui-page-filter" : "",
    snapshot.tab ? "pro-ui-page-tab" : "",
    snapshot.role ? "pro-ui-role-option" : "",
    snapshot.selected ? "is-selected" : "",
    snapshot.ghost ? "is-ghost" : "",
  ].join(" ").trim();

  return (
    <Tooltip title={snapshot.title || undefined} mouseEnterDelay={0.35}>
      <ProXButton
        className={className}
        type={type}
        size={snapshot.filter ? "small" : undefined}
        icon={icon || undefined}
        disabled={snapshot.disabled}
        danger={special && !label}
        block={snapshot.role}
        data-selected={snapshot.selected ? "true" : "false"}
        onClick={() => element.click()}
      >
        {label || undefined}
      </ProXButton>
    </Tooltip>
  );
}

function selectSnapshot(element) {
  return {
    value: element.value,
    hidden: readBooleanAttribute(element, "hidden") || element.closest("[hidden]") !== null,
    disabled: !!element.disabled,
    options: Array.from(element.options).map((option) => ({
      value: option.value,
      label: option.textContent.trim(),
      disabled: option.disabled,
    })),
  };
}

function ProUiSelectControl({ element }) {
  const snapshot = useLegacySnapshot(element, () => selectSnapshot(element));
  return (
    <Select
      className="pro-ui-page-select"
      value={snapshot.value || undefined}
      options={snapshot.options}
      disabled={snapshot.disabled}
      placeholder="加载中…"
      showSearch
      optionFilterProp="label"
      onChange={(value) => {
        element.value = String(value);
        dispatchNativeChange(element);
      }}
    />
  );
}

function inputSnapshot(element) {
  return {
    value: element.value,
    type: element.type || "text",
    multiline: element instanceof HTMLTextAreaElement,
    rows: Number(element.getAttribute("rows") || 0),
    min: element.min,
    max: element.max,
    step: element.step,
    placeholder: element.getAttribute("placeholder") || "",
    maxLength: element.getAttribute("maxlength"),
    disabled: !!element.disabled,
    hidden: readBooleanAttribute(element, "hidden") || element.closest("[hidden]") !== null,
  };
}

function inlineInputClass(element) {
  return element.closest(".settings-keyrow, [style*='display:flex'], [style*='display: flex']")
    ? "pro-ui-inline-control"
    : "";
}

function ProUiInputControl({ element }) {
  const snapshot = useLegacySnapshot(element, () => inputSnapshot(element));
  const className = inlineInputClass(element);
  const common = {
    className,
    value: snapshot.value,
    placeholder: snapshot.placeholder,
    disabled: snapshot.disabled,
    maxLength: snapshot.maxLength ? Number(snapshot.maxLength) : undefined,
  };
  const update = (value, eventName) => {
    element.value = value == null ? "" : String(value);
    dispatchNativeChange(element, eventName);
  };

  if (snapshot.type === "number") {
    return (
      <InputNumber
        {...common}
        min={snapshot.min === "" ? undefined : Number(snapshot.min)}
        max={snapshot.max === "" ? undefined : Number(snapshot.max)}
        step={snapshot.step === "" ? undefined : Number(snapshot.step)}
        onChange={(value) => update(value, "input")}
      />
    );
  }
  if (snapshot.type === "password") {
    return <Input.Password {...common} onChange={(event) => update(event.target.value, "input")} />;
  }
  if (snapshot.multiline) {
    return (
      <Input.TextArea
        {...common}
        rows={snapshot.rows || 5}
        autoSize={{ minRows: snapshot.rows || 5, maxRows: 10 }}
        onChange={(event) => update(event.target.value, "input")}
      />
    );
  }
  return <Input {...common} onChange={(event) => update(event.target.value, "input")} />;
}

function ProUiRangeControl({ element }) {
  const snapshot = useLegacySnapshot(element, () => inputSnapshot(element));
  return (
    <Slider
      className="pro-ui-page-slider"
      min={Number(snapshot.min || 0)}
      max={Number(snapshot.max || 100)}
      step={Number(snapshot.step || 1)}
      value={Number(snapshot.value || 0)}
      disabled={snapshot.disabled}
      onChange={(value) => {
        element.value = String(value);
        dispatchNativeChange(element, "input");
      }}
    />
  );
}

function toggleSnapshot(element) {
  const input = element.querySelector("input[type='checkbox']");
  return {
    checked: !!input?.checked,
    disabled: !!input?.disabled,
    hidden: readBooleanAttribute(element, "hidden") || element.closest("[hidden]") !== null,
    label: element.querySelector(".toggle-label")?.textContent?.trim() || "",
    title: element.getAttribute("title") || "",
  };
}

function ProUiToggleControl({ element }) {
  const snapshot = useLegacySnapshot(element, () => toggleSnapshot(element));
  const input = element.querySelector("input[type='checkbox']");
  const setChecked = (checked) => {
    if (!input) return;
    input.checked = checked;
    dispatchNativeChange(input);
  };
  const control = (
    <span className="pro-ui-page-toggle">
      <Switch size="small" checked={snapshot.checked} disabled={snapshot.disabled} onChange={setChecked} />
      <span className="pro-ui-page-toggle-label" onClick={() => !snapshot.disabled && setChecked(!snapshot.checked)}>
        {snapshot.label}
      </span>
    </span>
  );
  return snapshot.title ? <Tooltip title={snapshot.title}>{control}</Tooltip> : control;
}

function checkSnapshot(element) {
  const input = element.querySelector("input");
  return {
    checked: !!input?.checked,
    disabled: !!input?.disabled,
    type: input?.type || "checkbox",
    name: input?.name || "",
    label: element.textContent.replace(/\s+/g, " ").trim(),
    hidden: readBooleanAttribute(element, "hidden") || element.closest("[hidden]") !== null,
  };
}

function ProUiCheckControl({ element }) {
  const snapshot = useLegacySnapshot(element, () => checkSnapshot(element));
  const input = element.querySelector("input");
  const update = (checked) => {
    if (!input) return;
    input.checked = checked;
    dispatchNativeChange(input);
  };
  if (snapshot.type === "radio") {
    return (
      <Radio className="pro-ui-page-check" checked={snapshot.checked} disabled={snapshot.disabled} onChange={(event) => update(event.target.checked)}>
        {snapshot.label}
      </Radio>
    );
  }
  return (
    <Checkbox className="pro-ui-page-check" checked={snapshot.checked} disabled={snapshot.disabled} onChange={(event) => update(event.target.checked)}>
      {snapshot.label}
    </Checkbox>
  );
}

function roleSnapshot(element) {
  return {
    label: element.querySelector(".role-opt-label")?.textContent?.trim() || "",
    description: element.querySelector(".role-opt-desc")?.textContent?.trim() || "",
    selected: element.classList.contains("selected"),
    hidden: readBooleanAttribute(element, "hidden") || element.closest("[hidden]") !== null,
  };
}

function ProUiRoleOptionControl({ element }) {
  const snapshot = useLegacySnapshot(element, () => roleSnapshot(element));
  return (
    <ProXButton
      className={`pro-ui-page-role-option${snapshot.selected ? " is-selected" : ""}`}
      type={snapshot.selected ? "primary" : "default"}
      block
      onClick={() => element.click()}
    >
      <span className="pro-ui-page-role-copy">
        <strong>{snapshot.label}</strong>
        {snapshot.description ? <small>{snapshot.description}</small> : null}
      </span>
    </ProXButton>
  );
}

function stepperSnapshot(element) {
  const steps = Array.from(element.querySelectorAll(".rg-step"));
  const current = steps.findIndex((step) => step.classList.contains("active"));
  return {
    hidden: readBooleanAttribute(element, "hidden") || element.closest("[hidden]") !== null,
    current: current < 0 ? 0 : current,
    items: steps.map((step) => ({
      title: step.querySelector("span")?.textContent?.trim() || step.textContent.trim(),
    })),
  };
}

function ProUiStepperControl({ element }) {
  const snapshot = useLegacySnapshot(element, () => stepperSnapshot(element));
  if (!snapshot.items.length) return null;
  return (
    <Steps
      className="pro-ui-page-steps"
      size="small"
      current={snapshot.current}
      responsive={false}
      items={snapshot.items}
    />
  );
}

function noteSnapshot(element) {
  return {
    hidden: readBooleanAttribute(element, "hidden") || element.closest("[hidden]") !== null,
    text: element.textContent.replace(/^[ℹ✓⚠]\s*/, "").replace(/\s+/g, " ").trim(),
    kind: element.classList.contains("error") || element.classList.contains("rg-note-error")
      ? "error"
      : element.classList.contains("warn") || element.classList.contains("rg-note-warn")
        ? "warning"
        : "info",
  };
}

function ProUiNoteControl({ element }) {
  const snapshot = useLegacySnapshot(element, () => noteSnapshot(element));
  if (!snapshot.text) return null;
  return (
    <Alert
      className="pro-ui-page-note"
      type={snapshot.kind}
      showIcon
      message={snapshot.text}
    />
  );
}

function dividerSnapshot(element) {
  return {
    hidden: readBooleanAttribute(element, "hidden") || element.closest("[hidden]") !== null,
    text: element.textContent.trim(),
  };
}

function ProUiDividerControl({ element }) {
  const snapshot = useLegacySnapshot(element, () => dividerSnapshot(element));
  return (
    <Divider className="pro-ui-page-divider" plain orientation="left" orientationMargin={0}>
      {snapshot.text}
    </Divider>
  );
}

function tabKey(button, index) {
  return button.dataset?.tab
    || button.dataset?.pane
    || button.getAttribute("data-kind")
    || `tab-${index}`;
}

function tabLabel(button) {
  const clone = button.cloneNode(true);
  const count = clone.querySelector(".tab-count")?.textContent?.trim() || "";
  clone.querySelectorAll(".tab-count").forEach((node) => node.remove());
  return {
    label: clone.textContent.replace(/\s+/g, " ").trim(),
    count,
  };
}

function isActiveButton(button) {
  return button.classList.contains("active")
    || button.classList.contains("is-on")
    || button.getAttribute("aria-selected") === "true"
    || button.getAttribute("aria-pressed") === "true";
}

function tabsSnapshot(element) {
  const buttons = [...element.querySelectorAll(":scope > button, :scope > .workspace-pane-tab")];
  const activeIndex = Math.max(0, buttons.findIndex(isActiveButton));
  return {
    activeKey: buttons[activeIndex] ? tabKey(buttons[activeIndex], activeIndex) : undefined,
    items: buttons.map((button, index) => ({
      key: tabKey(button, index),
      ...tabLabel(button),
    })),
  };
}

function activateNativeButton(element, key) {
  const buttons = [...element.querySelectorAll(":scope > button, :scope > .workspace-pane-tab")];
  const index = buttons.findIndex((button, position) => tabKey(button, position) === key);
  if (index >= 0) buttons[index].click();
}

function ProUiTabsControl({ element }) {
  const snapshot = useLegacySnapshot(element, () => tabsSnapshot(element));
  if (!snapshot.items.length) return null;
  return (
    <Tabs
      className="pro-ui-page-tabs"
      activeKey={snapshot.activeKey}
      items={snapshot.items.map((item) => ({
        key: item.key,
        label: (
          <span className="pro-ui-page-tab-label">
            {item.label}
            {item.count ? <Tag bordered={false} className="pro-ui-page-tab-count">{item.count}</Tag> : null}
          </span>
        ),
      }))}
      onChange={(key) => activateNativeButton(element, key)}
    />
  );
}

function ProUiSegmentedControl({ element }) {
  const snapshot = useLegacySnapshot(element, () => tabsSnapshot(element));
  if (!snapshot.items.length) return null;
  return (
    <Segmented
      className="pro-ui-page-segmented"
      size="small"
      value={snapshot.activeKey}
      options={snapshot.items.map((item) => ({ label: item.label, value: item.key }))}
      onChange={(key) => activateNativeButton(element, key)}
    />
  );
}

function filtersSnapshot(element) {
  return {
    items: [...element.querySelectorAll("button.ontology-filter")].map((button, index) => ({
      key: button.dataset.kind || `filter-${index}`,
      label: button.textContent.replace(/\s+/g, " ").trim(),
      checked: button.classList.contains("is-on")
        || button.classList.contains("active")
        || button.getAttribute("aria-pressed") === "true",
    })),
  };
}

function ProUiFilterControl({ element }) {
  const snapshot = useLegacySnapshot(element, () => filtersSnapshot(element));
  return (
    <Flex className="pro-ui-page-filters" wrap gap={6} role="toolbar" aria-label="本体类型筛选">
      {snapshot.items.map((item) => (
        <Tag.CheckableTag
          key={item.key}
          checked={item.checked}
          className="pro-ui-page-filter-tag"
          onChange={() => {
            const button = [...element.querySelectorAll("button.ontology-filter")]
              .find((node, index) => (node.dataset.kind || `filter-${index}`) === item.key);
            button?.click();
          }}
        >
          {item.label}
        </Tag.CheckableTag>
      ))}
    </Flex>
  );
}

function ProUiPageControl({ element, kind }) {
  let control = null;
  if (kind === "button") control = <ProUiButtonControl element={element} />;
  else if (kind === "select") control = <ProUiSelectControl element={element} />;
  else if (kind === "range") control = <ProUiRangeControl element={element} />;
  else if (kind === "input") control = <ProUiInputControl element={element} />;
  else if (kind === "toggle") control = <ProUiToggleControl element={element} />;
  else if (kind === "check") control = <ProUiCheckControl element={element} />;
  else if (kind === "role") control = <ProUiRoleOptionControl element={element} />;
  else if (kind === "stepper") control = <ProUiStepperControl element={element} />;
  else if (kind === "note") control = <ProUiNoteControl element={element} />;
  else if (kind === "divider") control = <ProUiDividerControl element={element} />;
  else if (kind === "tabs") control = <ProUiTabsControl element={element} />;
  else if (kind === "segmented") control = <ProUiSegmentedControl element={element} />;
  else if (kind === "filters") control = <ProUiFilterControl element={element} />;
  return <ProXConfigProvider theme={PROX_WORKBENCH_THEME}>{control}</ProXConfigProvider>;
}

function controlKind(element) {
  if (element.matches(".page-header.tab-bar")) return "tabs";
  if (element.matches(".workspace-pane-switcher")) return "segmented";
  if (element.matches(".ontology-filters")) return "filters";
  if (element.matches("button")) return "button";
  if (element.matches("select")) return "select";
  if (element.matches("input[type='range']")) return "range";
  if (element.matches("input, textarea")) return "input";
  if (element.matches(".toggle")) return "toggle";
  if (element.matches(".rg-check")) return "check";
  if (element.matches(".role-option")) return "role";
  if (element.matches(".rg-stepper")) return "stepper";
  if (element.matches(".rg-note")) return "note";
  if (element.matches(".settings-divider")) return "divider";
  return "";
}

function mountControl(element) {
  if (!element || bridgedRoots.has(element)) return;
  if (element.closest(SKIP_SELECTOR)) return;
  const kind = controlKind(element);
  if (!kind) return;

  const host = document.createElement("div");
  host.className = "pro-ui-control-host";
  host.dataset.proUiControl = kind;
  element.dataset.proUiNative = "true";
  // Native anchors are sometimes hidden directly (for example the wizard's
  // previous/confirm buttons) and sometimes through a hidden parent field.
  // React should always mount the visible component; this host-level mirror
  // prevents a directly hidden anchor from surfacing its sibling control.
  const syncHostVisibility = () => {
    host.hidden = element.hidden || element.style.display === "none";
  };
  const visibilityObserver = new MutationObserver(syncHostVisibility);
  visibilityObserver.observe(element, { attributes: true, attributeFilter: ["hidden", "style"] });
  syncHostVisibility();
  if (kind === "select" || kind === "input" || kind === "range") mirrorPropertyWrites(element, "value");
  if (kind === "toggle" || kind === "check") {
    mirrorPropertyWrites(element.querySelector("input"), "checked");
  }
  element.after(host);
  const root = createRoot(host);
  root.render(<ProUiPageControl element={element} kind={kind} />);
  bridgedRoots.set(element, { host, root, visibilityObserver });
  globalState.roots.add(root);
}

function scan(root) {
  root.querySelectorAll(CONTROL_SELECTOR).forEach(mountControl);
}

export function mountProUiPageControls(root = document) {
  if (!root) return () => {};
  scan(root);
  if (globalState.observer) return () => {};
  globalState.observer = new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      mutation.addedNodes.forEach((node) => {
        if (!(node instanceof Element)) return;
        if (node.matches?.(CONTROL_SELECTOR)) mountControl(node);
        node.querySelectorAll?.(CONTROL_SELECTOR).forEach(mountControl);
      });
    }
  });
  globalState.observer.observe(root, { childList: true, subtree: true });
  return () => {
    globalState.observer?.disconnect();
    globalState.observer = null;
  };
}

export default mountProUiPageControls;
