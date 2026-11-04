import React, { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Form,
  Input,
  InputNumber,
  Select,
  Slider,
  Space,
  Spin,
  Switch,
  Tag,
  Typography,
} from "antd";
import { Button as ProXButton } from "@pro-ui/x-react";
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  ReloadOutlined,
} from "@ant-design/icons";

const EMPTY_LLM = { models: [], current: {}, api_keys: {} };

function withBasePath(path) {
  const root = String(window.APP_ROOT_PATH || "").replace(/\/+$/, "");
  if (!root || root === "/") return path;
  return String(path).startsWith("/") ? root + path : `${root}/${path}`;
}

function modelLabel(model) {
  if (!model) return "模型参数";
  return model.label || model.model_key || model.key || "模型参数";
}

function providerHint(model) {
  if (!model) return "";
  const provider = model.provider || "";
  const envByProvider = {
    qwen: "DASHSCOPE_API_KEY",
    deepseek: "DEEPSEEK_API_KEY",
    team: "TEAM_API_KEY",
    anthropic: "ANTHROPIC_API_KEY",
  };
  const bits = [`provider: ${provider || "unknown"}`, `max_output: ${model.max_output_tokens ?? "-"}`];
  if (envByProvider[provider]) bits.push(`需要环境变量 ${envByProvider[provider]}`);
  if (model.supports_thinking) bits.push("支持思考模式");
  return bits.join(" · ");
}

function keyStatus(info) {
  if (!info?.present) return { text: "未配置", color: "default" };
  return { text: `已配置 · ${info.masked || ""} · ${info.source === "env" ? "env" : "file"}`, color: "success" };
}

function valuesFromLlm(llm) {
  const current = llm?.current || {};
  const models = Array.isArray(llm?.models) ? llm.models : [];
  const selected = models.find((item) => item.model_key === current.model_key) || models[0] || {};
  return {
    modelKey: current.model_key || selected.model_key || selected.key || "",
    maxTokens: Number(current.max_tokens ?? selected.default_max_tokens ?? 8192),
    temperature: Number(current.temperature ?? selected.default_temperature ?? 1),
    thinking: !!current.thinking,
  };
}

export default function ProUiSettingsPage() {
  const [loading, setLoading] = useState(true);
  const [llm, setLlm] = useState(EMPTY_LLM);
  const [values, setValues] = useState(() => valuesFromLlm(EMPTY_LLM));
  const [apiKeys, setApiKeys] = useState({ anthropic: "", qwen: "", deepseek: "" });
  const [status, setStatus] = useState({ type: "info", text: "" });
  const [saving, setSaving] = useState(false);

  const models = Array.isArray(llm.models) ? llm.models : [];
  const selectedModel = useMemo(
    () => models.find((item) => (item.model_key || item.key) === values.modelKey) || models[0] || null,
    [models, values.modelKey],
  );
  const maxOutput = Number(selectedModel?.max_output_tokens || 200000);
  const supportsThinking = !!selectedModel?.supports_thinking;

  const applyLlm = (next) => {
    setLlm(next || EMPTY_LLM);
    setValues(valuesFromLlm(next || EMPTY_LLM));
  };

  useEffect(() => {
    let disposed = false;
    const load = async () => {
      try {
        const response = await fetch(withBasePath("api/meta"), { cache: "no-store" });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const meta = await response.json();
        if (disposed) return;
        applyLlm(meta.llm);
      } catch (error) {
        if (!disposed) setStatus({ type: "error", text: `加载模型配置失败: ${error.message || error}` });
      } finally {
        if (!disposed) setLoading(false);
      }
    };
    const onSnapshot = (event) => {
      applyLlm(event.detail);
      setLoading(false);
    };
    const onUpdated = (event) => applyLlm(event.detail);
    load();
    window.addEventListener("bi-settings-snapshot", onSnapshot);
    window.addEventListener("bi-settings-updated", onUpdated);
    return () => {
      disposed = true;
      window.removeEventListener("bi-settings-snapshot", onSnapshot);
      window.removeEventListener("bi-settings-updated", onUpdated);
    };
  }, []);

  useEffect(() => {
    if (!supportsThinking && values.thinking) {
      setValues((previous) => ({ ...previous, thinking: false }));
    }
  }, [supportsThinking, values.thinking]);

  const setValue = (name, value) => setValues((previous) => ({ ...previous, [name]: value }));

  const resetDefaults = () => {
    if (!selectedModel) return;
    setValues((previous) => ({
      ...previous,
      maxTokens: Number(selectedModel.default_max_tokens ?? previous.maxTokens),
      temperature: Number(selectedModel.default_temperature ?? previous.temperature),
      thinking: !!selectedModel.supports_thinking && previous.thinking,
    }));
  };

  const save = async () => {
    setSaving(true);
    setStatus({ type: "info", text: "保存中…" });
    const payload = {
      model_key: values.modelKey,
      max_tokens: Number(values.maxTokens),
      temperature: Number(values.temperature),
      thinking: supportsThinking && !!values.thinking,
    };
    if (apiKeys.anthropic.trim()) payload.anthropic_api_key = apiKeys.anthropic.trim();
    if (apiKeys.qwen.trim()) payload.qwen_api_key = apiKeys.qwen.trim();
    if (apiKeys.deepseek.trim()) payload.deepseek_api_key = apiKeys.deepseek.trim();
    try {
      const response = await fetch(withBasePath("api/config"), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: response.statusText }));
        throw new Error(error.detail || "保存失败");
      }
      const next = await response.json();
      applyLlm(next);
      setApiKeys({ anthropic: "", qwen: "", deepseek: "" });
      window.dispatchEvent(new CustomEvent("bi-settings-updated", { detail: next }));
      setStatus({ type: "success", text: "已保存 · 下一轮对话立即生效" });
      window.setTimeout(() => window.dispatchEvent(new CustomEvent("bi-settings-close")), 900);
    } catch (error) {
      setStatus({ type: "error", text: `保存失败: ${error.message || error}` });
    } finally {
      setSaving(false);
    }
  };

  const clearKey = async (provider) => {
    if (!window.confirm(`确定清除 ${provider} 的 API key?(仅清除配置文件中的值;环境变量不受影响)`)) return;
    const fieldByProvider = {
      anthropic: "anthropic_api_key",
      qwen: "qwen_api_key",
      deepseek: "deepseek_api_key",
    };
    try {
      const response = await fetch(withBasePath("api/config"), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ [fieldByProvider[provider]]: "" }),
      });
      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: response.statusText }));
        throw new Error(error.detail || "清除失败");
      }
      const next = await response.json();
      applyLlm(next);
      window.dispatchEvent(new CustomEvent("bi-settings-updated", { detail: next }));
      setStatus({ type: "success", text: `${provider} key 已清除` });
    } catch (error) {
      setStatus({ type: "error", text: `清除失败: ${error.message || error}` });
    }
  };

  const keyRows = [
    ["anthropic", "Anthropic (Claude)", "sk-ant-api03-…  (留空则不修改)", "ANTHROPIC_API_KEY"],
    ["qwen", "DashScope (Qwen)", "sk-…  (留空则不修改)", "DASHSCOPE_API_KEY"],
    ["deepseek", "DeepSeek", "sk-…  (留空则不修改)", "DEEPSEEK_API_KEY"],
  ];

  if (loading) {
    return <div className="pro-ui-settings-loading"><Spin size="small" /> 正在加载模型配置…</div>;
  }

  return (
    <div className="pro-ui-settings">
      <Form layout="vertical" className="pro-ui-settings-form">
        <Form.Item label="模型" extra={providerHint(selectedModel)}>
          <Select
            aria-label="模型"
            value={values.modelKey || undefined}
            options={models.map((item) => ({
              value: item.model_key || item.key,
              label: `${item.label || item.model_key || item.key}  [${item.provider || "-"}]`,
            }))}
            onChange={(value) => setValue("modelKey", value)}
          />
        </Form.Item>

        <Form.Item label="最大输出长度 max_tokens" extra="单次响应的最大输出 token 数,范围 256–200000。">
          <InputNumber
            aria-label="最大输出长度"
            min={256}
            max={maxOutput}
            step={256}
            value={values.maxTokens}
            onChange={(value) => setValue("maxTokens", Number(value || 0))}
            style={{ width: "100%" }}
          />
        </Form.Item>

        <Form.Item label={`采样温度 temperature ${Number(values.temperature).toFixed(2)}`} extra="0 最确定性,1 平衡,2 最发散。Qwen 建议 ≤1.2。">
          <Slider
            aria-label="采样温度"
            min={0}
            max={2}
            step={0.05}
            value={Number(values.temperature)}
            onChange={(value) => setValue("temperature", value)}
          />
        </Form.Item>

        <Form.Item
          label={<Space size={8}>扩展思考 <Tag color={supportsThinking ? "success" : "default"}>{supportsThinking ? "可用" : "本模型不支持"}</Tag></Space>}
          extra="开启后模型会先输出推理过程再给最终回答。仅对支持思考模式的模型生效; Claude 模型在启用思考时会自动锁定 temperature=1.0。"
        >
          <Space>
            <Switch
              aria-label="启用思考模式"
              checked={supportsThinking && values.thinking}
              disabled={!supportsThinking}
              onChange={(checked) => setValue("thinking", checked)}
            />
            <Typography.Text>启用思考模式</Typography.Text>
          </Space>
        </Form.Item>

        <div className="pro-ui-settings-divider">API 密钥</div>

        {keyRows.map(([provider, label, placeholder, envName]) => {
          const current = keyStatus(llm.api_keys?.[provider]);
          return (
            <Form.Item
              key={provider}
              label={<Space size={8}>{label} <Tag color={current.color}>{current.text}</Tag></Space>}
              extra={<>也可设为环境变量 <code>{envName}</code>(优先级更高)。</>}
            >
              <Space.Compact block>
                <Input.Password
                  aria-label={`${label} API key`}
                  value={apiKeys[provider]}
                  placeholder={placeholder}
                  autoComplete="off"
                  onChange={(event) => setApiKeys((previous) => ({ ...previous, [provider]: event.target.value }))}
                />
                <ProXButton
                  type="text"
                  aria-label={`清除 ${label} API key`}
                  icon={current.text === "未配置" ? <CloseCircleOutlined /> : <CheckCircleOutlined />}
                  onClick={() => clearKey(provider)}
                />
              </Space.Compact>
            </Form.Item>
          );
        })}
      </Form>

      {status.text ? (
        <Alert
          className="pro-ui-settings-status"
          type={status.type === "success" ? "success" : status.type === "error" ? "error" : "info"}
          showIcon
          message={status.text}
        />
      ) : null}

      <div className="pro-ui-settings-footer">
        <ProXButton icon={<ReloadOutlined />} onClick={resetDefaults}>恢复默认</ProXButton>
        <span className="pro-ui-settings-spacer" />
        <ProXButton onClick={() => window.dispatchEvent(new CustomEvent("bi-settings-close"))}>返回</ProXButton>
        <ProXButton type="primary" loading={saving} onClick={save}>保存</ProXButton>
      </div>
    </div>
  );
}
