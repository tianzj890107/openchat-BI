import React, {useEffect, useId, useRef, useState} from "react";

import {loadSources, requestJson, updateModelConfig} from "../api.js";
import {readPreferences} from "../preferences.js";
import {sourceSelection} from "../sourcePreference.js";

// The local Excel + PostgreSQL pair is delivered as one named source.
const LOCAL_PAIR_LABEL = "亿纬锂能dev";

const localModes = [
  {value: "semantic", label: "语义检索"},
  {value: "graph", label: "图谱检索"},
];

function optionsWithActive(options, active, label) {
  return [...new Set([...(options || []), active].filter(Boolean))]
    .map((value) => ({value, label: label?.(value) || value}));
}

function sourceValues(data, preference) {
  return {
    ontology: data.ontology?.active || "",
    database: data.database?.active || "",
    retrieval_mode: data.retrieval?.mode || "semantic",
    graph: data.retrieval?.graph?.active || "",
    doris_database: data.doris?.database || "",
    doris_api_url: data.doris?.api_url || "",
    doris_jdbc_url: data.doris?.jdbc_url || "",
    doris_driver: data.doris?.driver || "",
    doris_username: data.doris?.username || "",
    ...preference,
  };
}

function SelectField({label, name, value, options, onChange, allowEmpty = false}) {
  return (
    <label className="ak-settings-field">
      <span>{label}</span>
      <select name={name} value={value} onChange={(event) => onChange(name, event.target.value)}>
        {allowEmpty || value === "" ? <option value="">{allowEmpty ? "默认" : "请选择"}</option> : null}
        {options.map((item) => <option key={item.value} value={item.value} disabled={item.disabled}>{item.label}</option>)}
      </select>
    </label>
  );
}

function SourcesForm({data, preference, hasConversation, busy, onSave}) {
  const [values, setValues] = useState(() => sourceValues(data, preference));
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState(null);
  const [builtGraphs, setBuiltGraphs] = useState([]);
  const pairs = data.ontology?.remote_repositories || [];
  const postgres = data.database?.local_postgres;
  const production = data.ontology?.production;
  const hasBinding = (pair) => Boolean(pair.databaseValue && pair.namespace !== "");
  const selectedRepo = pairs.find((pair) => pair.value === values.ontology);
  const isRemote = Boolean(selectedRepo || (production?.value && values.ontology === production.value));
  const genericDoris = data.doris?.value && values.database === data.doris.value && !isRemote;
  // Local files show their basename; platform entries are explicit so a local
  // session still sees 本体平台 as a switchable target.
  const ontologyOptions = optionsWithActive(data.ontology?.options, values.ontology, (value) => {
    const remote = pairs.find((pair) => pair.value === value);
    if (remote) return hasBinding(remote) ? `${remote.name}（本体平台）` : `${remote.name}（本体平台 · 缺少数据源配置）`;
    if (value === production?.value) return `${production.label}（本体平台）`;
    if (postgres?.ontology && value === postgres.ontology) return LOCAL_PAIR_LABEL;
    if (/\.(xlsx|xlsm|xls)$/i.test(value)) return `${value.split("/").pop()}（本地）`;
    return value;
  }).map((option) => {
    const remote = pairs.find((pair) => pair.value === option.value);
    return remote && !hasBinding(remote) && option.value !== values.ontology
      ? {...option, disabled: true} : option;
  });
  const databaseOptions = optionsWithActive(data.database?.options, values.database, (value) => {
    const related = pairs.find((pair) => pair.databaseValue === value);
    if (related) return `${related.dorisDatabase || related.name} · ${related.name}（本体平台）`;
    if (value === postgres?.value) return LOCAL_PAIR_LABEL;
    if (value === data.doris?.value) return "Doris（自定义）";
    if (/\.db$/i.test(value)) return `${value.split("/").pop()}（本地 SQLite）`;
    return value;
  }).map((option) => {
    const remote = pairs.find((pair) => pair.databaseValue === option.value);
    return remote && !hasBinding(remote) && option.value !== values.database
      ? {...option, disabled: true} : option;
  });

  const change = (name, value) => {
    setStatus(null);
    setValues((current) => {
      const next = {...current, [name]: value};
      if (name === "ontology") {
        const pair = pairs.find((item) => item.value === value);
        if (pair?.databaseValue) next.database = pair.databaseValue;
        else if (value === postgres?.ontology) next.database = postgres.value;
        else if (current.database === postgres?.value || pairs.some((item) => item.databaseValue === current.database)) {
          next.database = databaseOptions.find((item) => item.value !== postgres?.value
            && !pairs.some((pair) => pair.databaseValue === item.value))?.value || "";
        }
      }
      if (name === "database") {
        const pair = pairs.find((item) => item.databaseValue === value);
        if (pair) next.ontology = pair.value;
        else if (value === postgres?.value) next.ontology = postgres.ontology;
        else if (isRemote) {
          next.ontology = ontologyOptions.find((item) => item.value !== production?.value
            && !pairs.some((pair) => pair.value === item.value))?.value || "";
        }
      }
      return next;
    });
  };

  const submit = async (event) => {
    event.preventDefault();
    setSaving(true);
    setStatus(null);
    const {graph, doris_database: schema, ...binding} = values;
    try {
      const saved = await onSave({
        ...sourceSelection(binding),
        ...(genericDoris ? Object.fromEntries(Object.entries(binding).filter(([key, value]) => key.startsWith("doris_") && value)) : {}),
        graph: !isRemote && values.retrieval_mode === "graph" ? graph : "",
        doris_database: genericDoris ? schema : "",
      });
      setValues((current) => ({...current, ...saved, graph: saved.graph || ""}));
      setStatus({text: "数据源已保存"});
    } catch (error) {
      setStatus({text: error.message, error: true});
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} className="ak-settings-form">
      <fieldset disabled={saving}>
        <legend>本体与数据源</legend>
        <SelectField label="本体库" name="ontology" value={values.ontology} options={ontologyOptions} onChange={change} />
        <SelectField label="业务数据源" name="database" value={values.database} options={databaseOptions} onChange={change} />
        <SelectField label="检索模式" name="retrieval_mode" value={values.retrieval_mode} options={localModes} onChange={change} />
        {!isRemote && values.retrieval_mode === "graph" ? <>
          <SelectField label="本地图库" name="graph" value={values.graph}
            options={optionsWithActive([...(data.retrieval?.graph?.options || []), ...builtGraphs], values.graph)} onChange={change} />
          <button type="button" className="ak-ghost" disabled={busy || !values.ontology} onClick={async () => {
            setSaving(true);
            try {
              const {graph} = await requestJson("api/graph/build", {method: "POST", body: {ontology: values.ontology}});
              setBuiltGraphs((current) => [...current, graph]);
              change("graph", graph);
              setStatus({text: "图库已构建，保存后生效"});
            } catch (error) { setStatus({text: error.message, error: true}); }
            finally { setSaving(false); }
          }}>从当前本体构建图库</button>
        </> : null}
        {genericDoris ? (
          <label className="ak-settings-field">
            <span>Doris 数据库名</span>
            <input value={values.doris_database} onChange={(event) => change("doris_database", event.target.value)} />
          </label>
        ) : null}
        {genericDoris ? <details className="ak-advanced">
          <summary>Doris 连接配置</summary>
          {[["doris_api_url", "HTTP API 地址"], ["doris_jdbc_url", "JDBC 地址"], ["doris_driver", "驱动"],
            ["doris_username", "用户名"], ["doris_password", "密码"]].map(([key, label]) =>
            <label className="ak-settings-field" key={key}>{label}
              <input name={key} type={key === "doris_password" ? "password" : "text"}
                value={values[key] || ""} onChange={(event) => change(key, event.target.value)} />
            </label>)}
        </details> : null}
        {hasConversation ? <p className="ak-settings-hint">保存后开启新会话，已有对话可从历史打开。</p> : null}
        {status ? <p role={status.error ? "alert" : "status"}>{status.text}</p> : null}
        <button type="submit" className="ak-primary" disabled={busy || !values.ontology || !values.database}>
          {saving ? "保存中…" : "保存本体库与数据源"}
        </button>
      </fieldset>
    </form>
  );
}

export function modelKey(model) {
  return model?.model_key || model?.key || "";
}

const providers = [
  ["anthropic", "Anthropic"], ["qwen", "通义千问"], ["deepseek", "DeepSeek"], ["team", "Team 网关"],
];

function ModelForm({config, busy, onSaved}) {
  const models = config.models || [];
  const [values, setValues] = useState(config.current || {});
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState(null);
  const [keys, setKeys] = useState({});
  const model = models.find((item) => modelKey(item) === values.model_key) || models[0];

  const change = (name, value) => {
    setStatus(null);
    setValues((current) => ({...current, [name]: value}));
  };

  const submit = async (event) => {
    event.preventDefault();
    setSaving(true);
    setStatus(null);
    try {
      const saved = await updateModelConfig({
        model_key: modelKey(model),
        max_tokens: Number(values.max_tokens),
        temperature: Number(values.temperature),
        thinking: Boolean(model.supports_thinking && values.thinking),
        ...Object.fromEntries(Object.entries(keys).filter(([, value]) => value.trim())
          .map(([provider, value]) => [`${provider}_api_key`, value.trim()])),
      });
      setValues(saved.current);
      setKeys({});
      onSaved(saved);
      setStatus({text: "模型已保存，下一轮对话生效"});
    } catch (error) {
      setStatus({text: error.message, error: true});
    } finally {
      setSaving(false);
    }
  };

  if (!model) return <p role="status">当前没有可选模型。</p>;
  return (
    <form onSubmit={submit} className="ak-settings-form">
      <fieldset disabled={saving}>
        <legend>模型参数</legend>
        <SelectField label="模型" name="model_key" value={modelKey(model)}
          options={models.map((item) => ({value: modelKey(item), label: item.label || modelKey(item)}))}
          onChange={(name, value) => {
            const next = models.find((item) => modelKey(item) === value);
            setStatus(null);
            setValues({
              [name]: value, max_tokens: next.default_max_tokens ?? 8192,
              temperature: next.default_temperature ?? 1,
              thinking: Boolean(next.supports_thinking && values.thinking),
            });
          }} />
        <label className="ak-settings-field">
          <span>最大输出 Token</span>
          <input name="max_tokens" type="number" required min="256" max={model.max_output_tokens || 200000}
            value={values.max_tokens ?? ""} onChange={(event) => change("max_tokens", event.target.value)} />
        </label>
        <label className="ak-settings-field">
          <span>温度</span>
          <input name="temperature" type="number" required min="0" max="2" step="any"
            value={values.temperature ?? ""} onChange={(event) => change("temperature", event.target.value)} />
        </label>
        <label className="ak-settings-check">
          <input name="thinking" type="checkbox" checked={Boolean(model.supports_thinking && values.thinking)}
            disabled={!model.supports_thinking} onChange={(event) => change("thinking", event.target.checked)} />
          <span>思考模式</span>
        </label>
        {config.api_keys ? <details className="ak-advanced">
          <summary>模型服务 API Key</summary>
          {providers.filter(([key]) => Object.hasOwn(config.api_keys, key)).map(([provider, label]) => {
            const info = config.api_keys[provider];
            return <div className="ak-model-key" key={provider}>
              <label className="ak-settings-field">{label}
                <input type="password" autoComplete="new-password" value={keys[provider] || ""}
                  placeholder={info?.present ? "已配置" : "输入 API Key"}
                  onChange={(event) => setKeys((current) => ({...current, [provider]: event.target.value}))} />
              </label>
              {info?.present && info.source !== "env" ? <button type="button" className="ak-ghost" disabled={busy}
                onClick={async () => {
                  if (!window.confirm(`清除已保存的 ${label} API Key？`)) return;
                  setSaving(true);
                  try {
                    const saved = await updateModelConfig({[`${provider}_api_key`]: ""});
                    setKeys((current) => ({...current, [provider]: ""}));
                    onSaved(saved);
                    setStatus({text: `已清除 ${label} API Key`});
                  } catch (error) { setStatus({text: error.message, error: true}); }
                  finally { setSaving(false); }
                }}>清除</button> : null}
            </div>;
          })}
        </details> : null}
        <p className="ak-settings-hint">模型配置会应用到当前分析服务的后续对话。</p>
        {status ? <p role={status.error ? "alert" : "status"}>{status.text}</p> : null}
        <button type="submit" className="ak-primary" disabled={busy}>{saving ? "保存中…" : "保存模型"}</button>
      </fieldset>
    </form>
  );
}

function SettingsContent({result, label, children}) {
  if (!result) return <p role="status">正在加载{label}…</p>;
  if (result.error) return <p role="alert">{label}加载失败：{result.error}</p>;
  return children(result.data);
}

export function SettingsDialog({name, title, busy, onClose, children}) {
  const dialog = useRef(null);
  const heading = useId();
  const label = title || `${name}设置`;
  useEffect(() => {
    const element = dialog.current;
    if (typeof element.showModal === "function") element.showModal();
    else element.setAttribute("open", "");
    return () => element.close?.();
  }, []);

  return (
    <dialog className="ak-settings" ref={dialog} aria-labelledby={heading}
      onCancel={(event) => { event.preventDefault(); onClose(); }}>
      <header className="ak-settings-head">
        <h2 id={heading}>{label}</h2>
        <button type="button" className="ak-ghost ak-close" aria-label={`关闭${name || title}`} title={`关闭${name || title}`} onClick={onClose}>×</button>
      </header>
      {busy ? <p className="ak-settings-hint">当前分析结束后可以保存设置。</p> : null}
      {children}
    </dialog>
  );
}

export function SourceSettings({sessionId, preference, hasConversation, busy, onSaveSources, onClose}) {
  const [sources, setSources] = useState(null);
  useEffect(() => {
    const controller = new AbortController();
    loadSources(sessionId, controller.signal).then(
      (data) => { if (!controller.signal.aborted) setSources({data}); },
      (error) => { if (!controller.signal.aborted) setSources({error: error.message}); },
    );
    return () => controller.abort();
  }, [sessionId]);
  return (
    <SettingsDialog name="切换本体库/数据源" busy={busy} onClose={onClose}>
      <SettingsContent result={sources} label="切换本体库/数据源">
        {(data) => <SourcesForm data={data} preference={preference}
          hasConversation={hasConversation} busy={busy} onSave={onSaveSources} />}
      </SettingsContent>
    </SettingsDialog>
  );
}

function PreferencesForm({sessionId, busy, onSaved}) {
  const [values, setValues] = useState(readPreferences);
  const [options, setOptions] = useState(null);
  const [status, setStatus] = useState(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    requestJson(`api/roles?session_id=${encodeURIComponent(sessionId)}`, {signal: controller.signal}).then((roles) => {
      if (controller.signal.aborted) return;
      setOptions(roles);
      setValues((current) => ({...current, user_role: current.user_role ?? roles.user_role ?? "",
        agent_pref: current.agent_pref ?? roles.agent_pref ?? ""}));
    }, (error) => { if (!controller.signal.aborted) setStatus({error: error.message}); });
    return () => controller.abort();
  }, [sessionId]);
  const change = (key, value) => setValues((current) => ({...current, [key]: value}));
  return <form className="ak-settings-form" onSubmit={async (event) => {
    event.preventDefault();
    setSaving(true);
    try {
      await onSaved(values);
      setStatus({text: "偏好已保存"});
    } catch (error) { setStatus({error: error.message}); }
    finally { setSaving(false); }
  }}>
    <fieldset disabled={busy || saving}>
      <legend>个人偏好</legend>
      <label className="ak-settings-field">称呼<input value={values.name} maxLength={40}
        onChange={(event) => change("name", event.target.value)} /></label>
      <SelectField name="theme" label="界面主题" value={values.theme}
        options={[{value: "light", label: "浅色"}, {value: "dark", label: "深色"}]} onChange={change} />
      {[["user_role", "我的角色"], ["agent_pref", "回答风格"]].map(([key, label]) =>
        <SelectField key={key} name={key} label={label} value={values[key] || ""} allowEmpty
          options={(options?.[`${key}_options`] || []).map(({key, label}) => ({value: key, label}))} onChange={change} />)}
      {status ? <p role={status.error ? "alert" : "status"}>{status.error || status.text}</p> : null}
      <button type="submit" className="ak-primary" disabled={!options}>保存个人偏好</button>
    </fieldset>
  </form>;
}

export function ModelSettings({config, busy, onSaved, onClose, sessionId, onSavePreferences}) {
  return (
    <SettingsDialog name="模型" busy={busy} onClose={onClose}>
      <SettingsContent result={config} label="模型配置">
        {(data) => <ModelForm config={data} busy={busy} onSaved={onSaved} />}
      </SettingsContent>
      <PreferencesForm sessionId={sessionId} busy={busy} onSaved={onSavePreferences} />
    </SettingsDialog>
  );
}
