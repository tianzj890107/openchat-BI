import React, { useState } from "react";
import { Alert, Form, Input, Space, Switch, Typography } from "antd";
import { Button as ProXButton } from "@pro-ui/x-react";

const NAME_KEY = "bi.userName";
const THEME_KEY = "bi.theme.v2";

function readPref(key, fallback) {
  try { return localStorage.getItem(key) || fallback; } catch (_) { return fallback; }
}

function writePref(key, value) {
  try { localStorage.setItem(key, value); } catch (_) { /* storage may be disabled */ }
}

export default function ProUiAccountPage() {
  const [name, setName] = useState(() => readPref(NAME_KEY, ""));
  const [light, setLight] = useState(() => readPref(THEME_KEY, "light") === "light");
  const [saved, setSaved] = useState(false);

  const save = () => {
    const nextName = String(name || "").trim() || "分析员";
    const theme = light ? "light" : "dark";
    writePref(NAME_KEY, nextName);
    writePref(THEME_KEY, theme);
    document.documentElement.classList.toggle("theme-light", theme === "light");
    setName(nextName);
    setSaved(true);
    window.dispatchEvent(new CustomEvent("bi-account-updated", { detail: { name: nextName, theme } }));
    window.setTimeout(() => setSaved(false), 2000);
  };

  return (
    <div className="pro-ui-settings">
      <Form layout="vertical" className="pro-ui-settings-form">
        <Form.Item label="用户名" extra="显示在左下角账号区,仅保存在本机浏览器(localStorage)。">
          <Input
            aria-label="用户名"
            value={name}
            maxLength={24}
            placeholder="分析员"
            autoComplete="off"
            onChange={(event) => setName(event.target.value)}
          />
        </Form.Item>
        <Form.Item label="界面主题" extra="关闭为深色。默认使用 CEO 驾驶舱风格的浅色画布；主题偏好保存在本机浏览器。">
          <Space>
            <Switch aria-label="浅色主题" checked={light} onChange={setLight} />
            <Typography.Text>浅色主题</Typography.Text>
          </Space>
        </Form.Item>
      </Form>
      {saved ? <Alert type="success" showIcon message="已保存" /> : null}
      <div className="pro-ui-settings-footer">
        <span className="pro-ui-settings-spacer" />
        <ProXButton type="primary" onClick={save}>保存</ProXButton>
      </div>
    </div>
  );
}
