import React, {useEffect, useId, useRef, useState} from "react";

import {loadModelConfig, loadSources, updateModelConfig} from "../api.js";
import {sourceSelection} from "../sourcePreference.js";

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
    ...preference,
  };
}

function SelectField({label, name, value, options, onChange}) {
  return (
    <label className="ak-settings-field">
      <span>{label}</span>
      <select name={name} value={value} onChange={(event) => onChange(name, event.target.value)}>
        {value === "" ? <option value="">请选择</option> : null}
        {options.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
      </select>
    </label>
  );
}

function SourcesForm({data, preference, hasConversation, busy, onSave}) {
  const [values, setValues] = useState(() => sourceValues(data, preference));
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState(null);
  const pairs = data.ontology?.remote_repositories || [];
  const production = data.ontology?.production;
  const selectedRepo = pairs.find((pair) => pair.value === values.ontology);
  const isRemote = Boolean(selectedRepo || (production?.value && values.ontology === production.value));
  const genericDoris = data.doris?.value && values.database === data.doris.value && !isRemote;
  const ontologyOptions = optionsWithActive(data.ontology?.options, values.ontology,
    (value) => pairs.find((pair) => pair.value === value)?.name || (value === production?.value ? production.label : ""));
  const databaseOptions = optionsWithActive(data.database?.options, values.database, (value) => {
    const related = pairs.find((pair) => pair.databaseValue === value);
    if (related) return related.dorisDatabase || related.name;
    return value === data.doris?.value ? "Doris" : "";
  });

  const change = (name, value) => {
    setStatus(null);
    setValues((current) => {
      const next = {...current, [name]: value};
      if (name === "ontology") {
        const pair = pairs.find((item) => item.value === value);
        if (pair?.databaseValue) next.database = pair.databaseValue;
        else if (pairs.some((item) => item.databaseValue === current.database)) {
          next.database = databaseOptions.find((item) => !pairs.some((pair) => pair.databaseValue === item.value))?.value || "";
        }
      }
      if (name === "database") {
        const pair = pairs.find((item) => item.databaseValue === value);
        if (pair) next.ontology = pair.value;
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
      const saved = await onSave(sourceSelection({
        ...binding,
        graph: !isRemote && values.retrieval_mode === "graph" ? graph : "",
        doris_database: genericDoris ? schema : "",
      }));
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
        {!isRemote && values.retrieval_mode === "graph" ? (
          <SelectField label="本地图库" name="graph" value={values.graph}
            options={optionsWithActive(data.retrieval?.graph?.options, values.graph)} onChange={change} />
        ) : null}
        {genericDoris ? (
          <label className="ak-settings-field">
            <span>Doris 数据库名</span>
            <input value={values.doris_database} onChange={(event) => change("doris_database", event.target.value)} />
          </label>
        ) : null}
        {hasConversation ? <p className="ak-settings-hint">保存后开启新会话，已有对话可从历史打开。</p> : null}
        {status ? <p role={status.error ? "alert" : "status"}>{status.text}</p> : null}
        <button type="submit" className="ak-primary" disabled={busy || !values.ontology || !values.database}>
          {saving ? "保存中…" : "保存数据源"}
        </button>
      </fieldset>
    </form>
  );
}

function modelKey(model) {
  return model.model_key || model.key;
}

function ModelForm({config, busy}) {
  const models = config.models || [];
  const [values, setValues] = useState(config.current || {});
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState(null);
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
      });
      setValues(saved.current);
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

export default function Settings({sessionId, preference, hasConversation, busy, onSaveSources, onClose}) {
  const dialog = useRef(null);
  const title = useId();
  const [sources, setSources] = useState(null);
  const [model, setModel] = useState(null);

  useEffect(() => {
    const element = dialog.current;
    if (typeof element.showModal === "function") element.showModal();
    else element.setAttribute("open", "");
    return () => element.close?.();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    loadSources(sessionId, controller.signal).then(
      (data) => { if (!controller.signal.aborted) setSources({data}); },
      (error) => { if (!controller.signal.aborted) setSources({error: error.message}); },
    );
    return () => controller.abort();
  }, [sessionId]);
  useEffect(() => {
    const controller = new AbortController();
    loadModelConfig(controller.signal).then(
      (data) => { if (!controller.signal.aborted) setModel({data}); },
      (error) => { if (!controller.signal.aborted) setModel({error: error.message}); },
    );
    return () => controller.abort();
  }, []);

  return (
    <dialog className="ak-settings" ref={dialog} aria-labelledby={title}
      onCancel={(event) => { event.preventDefault(); onClose(); }}>
      <header className="ak-settings-head">
        <h2 id={title}>工作台设置</h2>
        <button type="button" className="ak-ghost" onClick={onClose}>关闭设置</button>
      </header>
      {busy ? <p className="ak-settings-hint">当前分析结束后可以保存设置。</p> : null}
      <div className="ak-settings-grid">
        <SettingsContent result={sources} label="数据源">
          {(data) => <SourcesForm data={data} preference={preference}
            hasConversation={hasConversation} busy={busy} onSave={onSaveSources} />}
        </SettingsContent>
        <SettingsContent result={model} label="模型配置">
          {(data) => <ModelForm config={data} busy={busy} />}
        </SettingsContent>
      </div>
    </dialog>
  );
}
