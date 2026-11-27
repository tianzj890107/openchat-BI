import React, {useEffect, useRef, useState} from "react";

import {Paperclip, Plus, X} from "lucide-react";
import {listReports} from "../api.js";
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

export function ReportWizard({onGenerate, onClose}) {
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

export function AttachmentPicker({active, onChange, onClose}) {
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
  const useReports = async (ids) => {
    setBusy(true);
    try { await onChange(ids); onClose(); }
    catch (error) { setStatus(error.message); }
    finally { setBusy(false); }
  };
  return (
    <SettingsDialog title="最近报表" onClose={onClose}>
      <form className="ak-settings-form" onSubmit={async (event) => {
        event.preventDefault();
        await useReports(selected);
      }}>
        <fieldset disabled={busy}>
          <legend>最近上传</legend>
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
            <button className="ak-primary" type="submit" disabled={!selected.length}>{busy ? "处理中…" : `添加所选（${selected.length}/${maxReports}）`}</button>
            {active.length && !selected.length ? <button type="button" className="ak-ghost"
              onClick={() => useReports([])}>移除全部当前附件</button> : null}
          </div>
        </fieldset>
      </form>
    </SettingsDialog>
  );
}

export function AttachmentList({reports, busy, onRemove}) {
  if (!reports.length) return null;
  return <ul className="ak-composer-attachments" aria-label="当前附件">
    {reports.map(({id, filename}) => <li key={id} title={filename || id}>
      <Paperclip size={14} aria-hidden="true" />
      <span>{filename || id}</span>
      <button type="button" className="ak-ghost ak-attachment-remove" disabled={busy}
        aria-label={`移除${filename || id}`} onClick={() => onRemove(id)}><X size={14} aria-hidden="true" /></button>
    </li>)}
  </ul>;
}

export default function ReportControls({context, busy, onUpload, onWithDb, onClearContext, onOpenDialog,
  onNotice, onPrefillIfEmpty}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const fileInput = useRef(null);
  const trigger = useRef(null);
  const active = context.active_reports || [];
  const withDb = context.with_db !== false;
  const upload = async (event) => {
    const files = Array.from(event.target.files || []);
    event.target.value = "";
    if (!files.length) return;
    onNotice("");
    try {
      onNotice(await onUpload(files));
      onPrefillIfEmpty("请分析上传的附件。");
    } catch (error) { onNotice(error.message); }
  };
  const openDialog = (name) => {
    onNotice("");
    setMenuOpen(false);
    onOpenDialog(name);
  };
  return (
    <div className="ak-add-attachment"
      onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setMenuOpen(false); }}
      onKeyDown={(event) => {
        if (event.key === "Escape" && menuOpen) {
          event.stopPropagation();
          setMenuOpen(false);
          trigger.current?.focus();
        }
      }}>
      <input type="file" ref={fileInput} hidden multiple accept=".pdf,.docx" onChange={upload} />
      <button type="button" className="ak-ghost" ref={trigger} aria-label="添加附件" aria-expanded={menuOpen}
        title="添加附件" disabled={busy} onClick={() => setMenuOpen(!menuOpen)}>
        <Plus size={18} aria-hidden="true" />
      </button>
      {menuOpen && !busy ? <div className="ak-attachment-menu" aria-label="附件选项">
        <button type="button" className="ak-ghost" onClick={() => { setMenuOpen(false); fileInput.current?.click(); }}>上传文件</button>
        <button type="button" className="ak-ghost" onClick={() => openDialog("recent")}>最近报表</button>
        <button type="button" className="ak-ghost" onClick={() => openDialog("generate")}>标准报表生成</button>
        {active.length ? <label className="ak-settings-check">
          <input type="checkbox" checked={withDb} onChange={async (event) => {
            setMenuOpen(false);
            onNotice("");
            try { await onWithDb(event.target.checked); }
            catch (error) { onNotice(error.message); }
          }} />启用数据库查询
        </label> : null}
        {context.has_session && !active.length ? <button type="button" className="ak-ghost" onClick={async () => {
          setMenuOpen(false);
          onNotice("");
          try { await onClearContext(); }
          catch (error) { onNotice(error.message); }
        }}>结束报表生成上下文</button> : null}
      </div> : null}
    </div>
  );
}
