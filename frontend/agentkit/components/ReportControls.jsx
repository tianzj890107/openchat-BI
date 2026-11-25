import React, {useEffect, useState} from "react";

import {listReports, uploadReport} from "../api.js";
import reportPlan from "../reportPlan.json";
import {SettingsDialog} from "./Settings.jsx";

const maxReports = 5;
const planStorageKey = "agentkit.reportPlan";
const fields = reportPlan.flatMap((step) => step.fields);

function initialPlan() {
  const defaults = Object.fromEntries(fields.map(({key, initial}) => [key, initial]));
  try { return {...defaults, ...JSON.parse(localStorage.getItem(planStorageKey) || "{}")}; }
  catch { return defaults; }
}

function planFields(values) {
  const custom = values.rulePlan.includes("自定义");
  return fields.filter(({key}) => custom ? key !== "ruleItems" : key !== "customRule");
}

function planText(values) {
  return planFields(values).map(({key, label}) => {
    const value = values[key];
    return [label, Array.isArray(value) ? value.join("、") : value];
  });
}

function ReportWizard({onGenerate, onClose}) {
  const [step, setStep] = useState(0);
  const [plan, setPlan] = useState(initialPlan);
  const [notice, setNotice] = useState("");
  const [saving, setSaving] = useState(false);
  const current = reportPlan[step];
  const isLast = step === reportPlan.length - 1;
  const change = (key, value) => setPlan((previous) => ({...previous, [key]: value}));
  const submit = async (event) => {
    event.preventDefault();
    if (!isLast) { setStep(step + 1); return; }
    setSaving(true);
    try {
      await onGenerate(
        "【标准报表生成任务】\n请按以下配置使用业务本体和数据库逐步取数。\n" +
        planText(plan).filter(([, value]) => value).map(([label, value]) => `${label}：${value}`).join("\n") +
        "\n先核对指标口径，再逐项取数。用 TableGenerate 输出含对比基期的表格，用 ChartGenerate 输出所选图表，最后给出管理层评述。");
      onClose();
    } catch (error) { setNotice(error.message); }
    finally { setSaving(false); }
  };
  return (
    <SettingsDialog title="标准报表生成" onClose={onClose}>
      <nav className="ak-question-rail" aria-label="报表配置步骤">
        {reportPlan.map(({title}, index) => <button type="button" className="ak-ghost" key={title}
          aria-current={step === index ? "step" : undefined} disabled={saving} onClick={() => setStep(index)}>{title}</button>)}
      </nav>
      <form className="ak-settings-form" onSubmit={submit}>
        <fieldset disabled={saving}>
          <legend>{current.title}</legend>
          {isLast ? <dl>{planText(plan).map(([label, value]) => <React.Fragment key={label}>
            <dt>{label}</dt><dd>{value || "—"}</dd>
          </React.Fragment>)}</dl> : planFields(plan).filter((field) => current.fields.includes(field)).map(({key, label, type, options}) => {
            if (type === "select") return <label className="ak-settings-field" key={key}>{label}
              <select value={plan[key]} onChange={(event) => change(key, event.target.value)}>
                {options.map((option) => <option key={option}>{option}</option>)}
              </select></label>;
            if (type === "textarea") return <label className="ak-settings-field" key={key}>{label}
              <textarea rows={4} value={plan[key]} onChange={(event) => change(key, event.target.value)} /></label>;
            return <fieldset className="ak-plan-options" key={key}><legend>{label}</legend>
              {options.map((option) => <label className="ak-settings-check" key={option}>
                <input type={type} name={key} checked={type === "radio" ? plan[key] === option : plan[key].includes(option)}
                  onChange={(event) => change(key, type === "radio" ? option :
                    event.target.checked ? [...plan[key], option] : plan[key].filter((value) => value !== option))} />
                {option}
              </label>)}</fieldset>;
          })}
          {notice ? <p role="status">{notice}</p> : null}
          <div className="ak-inline-actions">
            <button type="button" className="ak-ghost" onClick={() => {
              try { localStorage.setItem(planStorageKey, JSON.stringify(plan)); setNotice("方案已保存"); }
              catch { setNotice("无法保存方案"); }
            }}>存为方案</button>
            {step > 0 ? <button type="button" className="ak-ghost" onClick={() => setStep(step - 1)}>上一步</button> : null}
            <button type="submit" className="ak-primary">{saving ? "准备中…" : isLast ? "确认 · 开启报表生成" : "下一步"}</button>
          </div>
        </fieldset>
      </form>
    </SettingsDialog>
  );
}

function AttachmentPicker({active, withDb, onActivate, onDetach, onClose}) {
  const [reports, setReports] = useState([]);
  const [selected, setSelected] = useState(() => active.map((report) => report.id));
  const [status, setStatus] = useState("正在加载报表…");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let ignore = false;
    listReports().then((result) => {
      if (ignore) return;
      setReports(result.items || []);
      setStatus("");
    }, (error) => { if (!ignore) setStatus(error.message); });
    return () => { ignore = true; };
  }, []);
  const upload = async (event) => {
    const files = Array.from(event.target.files || []);
    event.target.value = "";
    if (!files.length) return;
    if (files.length + selected.length > maxReports) {
      setStatus(`一次最多选取 ${maxReports} 份报表`);
      return;
    }
    setBusy(true);
    const uploaded = [];
    const errors = [];
    for (const file of files) {
      try { uploaded.push(await uploadReport(file)); }
      catch (error) { errors.push(`${file.name} · ${error.message}`); }
    }
    setReports((current) => [...uploaded, ...current.filter((item) => !uploaded.some((report) => report.id === item.id))]);
    setSelected((current) => [...new Set([...current, ...uploaded.map((report) => report.id)])]);
    setStatus(errors.length ? errors.join("；") : "上传完成，请确认启用");
    setBusy(false);
  };
  const useReports = async (ids) => {
    setBusy(true);
    try { await onActivate(ids, withDb); onClose(); }
    catch (error) { setStatus(error.message); }
    finally { setBusy(false); }
  };
  return (
    <SettingsDialog title="选择或上传报表" onClose={onClose}>
      <form className="ak-settings-form" onSubmit={async (event) => {
        event.preventDefault();
        await useReports(selected);
      }}>
        <fieldset disabled={busy}>
          <legend>最近上传</legend>
          <label className="ak-settings-field">上传 PDF 或 Word
            <input type="file" multiple accept=".pdf,.docx" onChange={upload} />
          </label>
          {reports.length > 1 ? <div className="ak-inline-actions">
            <button type="button" className="ak-ghost" onClick={() => setSelected(reports.slice(0, maxReports)
              .map((report) => report.id))}>选择最近报表</button>
            <button type="button" className="ak-ghost" onClick={() => setSelected([])}>清除选择</button>
          </div> : null}
          <div className="ak-report-list">
            {reports.map((report) => <section key={report.id} className="ak-report-item">
              <div className="ak-inline-actions">
                <label className="ak-settings-check">
                  <input type="checkbox" checked={selected.includes(report.id)}
                    disabled={!selected.includes(report.id) && selected.length >= maxReports}
                    onChange={(event) => setSelected((current) => event.target.checked
                      ? [...current, report.id] : current.filter((id) => id !== report.id))} />
                  {report.filename || report.title || report.id}
                </label>
                <button type="button" className="ak-ghost" onClick={() => useReports([report.id])}>仅用此份</button>
              </div>
              {report.uploaded_at ? <small>{String(report.uploaded_at).slice(0, 10)} · {report.page_count} 页 · {report.tables_count} 表</small> : null}
              {report.preview ? <p className="ak-card-note">{report.preview}</p> : null}
            </section>)}
          </div>
          {status ? <p role="status">{status}</p> : null}
          <div className="ak-inline-actions">
            <button className="ak-primary" type="submit" disabled={!selected.length}>{busy ? "处理中…" : `启用报表（${selected.length}/${maxReports}）`}</button>
            {active.length && !selected.length ? <button type="button" className="ak-ghost"
              onClick={() => { onDetach(); onClose(); }}>移除全部当前附件</button> : null}
          </div>
        </fieldset>
      </form>
    </SettingsDialog>
  );
}

export default function ReportControls({context, busy, onActivate, onWithDb, onGenerate, onDetach}) {
  const [dialog, setDialog] = useState("");
  const [updating, setUpdating] = useState(false);
  const [error, setError] = useState("");
  const active = context.active_reports || [];
  const withDb = context.with_db !== false;
  return (
    <div className="ak-report-controls">
      <div className="ak-inline-actions">
        <button type="button" className="ak-ghost" disabled={busy} onClick={() => setDialog("attach")}>选择或上传报表</button>
        <button type="button" className="ak-ghost" disabled={busy} onClick={() => setDialog("generate")}>标准报表生成</button>
        <label className="ak-settings-check"><input type="checkbox" checked={withDb} disabled={busy || updating}
          onChange={async (event) => {
            setUpdating(true); setError("");
            try { await onWithDb(event.target.checked); }
            catch (failure) { setError(failure.message); }
            finally { setUpdating(false); }
          }} />启用数据库查询</label>
        {context.has_session ? <button type="button" className="ak-ghost" disabled={busy}
          onClick={onDetach}>结束当前报表分析</button> : null}
      </div>
      {active.length ? <p className="ak-report-attachments">{active.map((report) => report.filename || report.id).join(" · ")}</p> : null}
      {error ? <p role="alert">{error}</p> : null}
      {dialog === "attach" ? <AttachmentPicker active={active} withDb={withDb} onActivate={onActivate}
        onDetach={onDetach} onClose={() => setDialog("")} /> : null}
      {dialog === "generate" ? <ReportWizard onGenerate={onGenerate} onClose={() => setDialog("")} /> : null}
    </div>
  );
}
