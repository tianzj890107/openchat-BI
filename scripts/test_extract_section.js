// Standalone test for the dashboard section extractor (app.js).
// Mirrors extractSection / extractConclusion / extractRootCause /
// extractActions so 结论 / 根因 / 建议 sync logic can be verified offline.

const NEXT_SECTION_RE = /[📊🔍💡📎📈📄]/u;
const SECTION_NAMES = [
  "关键结论", "结论",
  "根因分析", "根因证据链", "根因",
  "行动建议", "管理建议", "建议",
  "关键数据", "口径说明", "附图", "分析提醒", "跨维洞察",
];

function stripLineDecor(s) {
  return String(s == null ? "" : s)
    .replace(/^[#>*\-\s]+/, "")
    .replace(/^\d+\.\s*/, "")
    .replace(/^\*+/, "")
    .replace(/^\s+/, "");
}

function nameHeaderOf(line, names) {
  const h = stripLineDecor(line);
  for (const name of names) {
    if (!h.startsWith(name)) continue;
    const rest = h.slice(name.length);
    if (rest === "" || /^[*：:—\-（(、\s]/.test(rest)) return name;
  }
  return null;
}

function cleanLeadingDecoration(raw) {
  return raw.replace(/^\s*>+\s?/, "").replace(/\s+$/, "");
}

function extractSection(text, markers, namePrefixes) {
  if (!text || typeof text !== "string") return null;
  if (typeof markers === "string") markers = [markers];
  namePrefixes = namePrefixes || [];
  const lines = text.split(/\n/);
  const stripDecor = stripLineDecor;

  let startIdx = -1;
  let usedMarker = null;
  for (let i = 0; i < lines.length; i++) {
    const head = stripDecor(lines[i]);
    const m = markers.find((mk) => head.startsWith(mk));
    if (m) { startIdx = i; usedMarker = m; break; }
  }
  if (startIdx < 0 && namePrefixes.length) {
    for (let i = 0; i < lines.length; i++) {
      if (nameHeaderOf(lines[i], namePrefixes)) { startIdx = i; break; }
    }
  }
  if (startIdx < 0) return null;

  const out = [];
  let head = stripDecor(lines[startIdx]).replace(/\*\*/g, "").trim();
  if (usedMarker) head = head.replace(new RegExp("^" + usedMarker + "\\s*"), "");
  for (const name of namePrefixes) {
    head = head.replace(new RegExp("^" + name + "\\s*(?:[\\(（][^\\)）]*[\\)）])?\\s*"), "");
  }
  head = head.replace(/^[—\-:：]+\s*/, "").trim();
  if (head) out.push(head);

  const otherNames = SECTION_NAMES.filter((n) => !namePrefixes.includes(n));

  for (let j = startIdx + 1; j < lines.length; j++) {
    const raw = lines[j];
    const nt = raw.trim();
    if (/^#{1,6}\s/.test(nt)) break;
    const headProbe = stripDecor(nt).replace(/\*\*/g, "");
    const isOwnMarker = markers.some((mk) => headProbe.startsWith(mk));
    const probeFirst = headProbe.slice(0, 4);
    if (!isOwnMarker && NEXT_SECTION_RE.test(probeFirst)) break;
    if (nt && nameHeaderOf(nt, otherNames)) break;
    if (!nt) { if (out.length > 0) out.push(""); continue; }
    out.push(cleanLeadingDecoration(raw));
  }

  while (out.length > 0 && !out[out.length - 1]) out.pop();
  return out.length ? out.join("\n") : null;
}

const C = (t) => extractSection(t, ["📌"], ["关键结论", "结论"]);
const R = (t) => extractSection(t, ["🔍", "🔎"], ["根因分析", "根因证据链", "根因"]);
const A = (t) => extractSection(t, ["💡"], ["行动建议", "管理建议", "建议"]);

let pass = 0, fail = 0;
function ok(name, got, want) {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g === w) { pass++; console.log("  PASS " + name); }
  else { fail++; console.log("  FAIL " + name + "\n    got : " + g + "\n    want: " + w); }
}

console.log("--- canonical emoji template (must still work) ---");
const t1 = [
  "1. **📌 结论(TL;DR)** —— 2024 Q3 收入同比下降 12.4%,主因华东区乏力 [M001]",
  "2. **📊 关键数据**",
  "| a | b |",
  "3. **🔍 根因分析(证据链)**",
  "- 第 1 层:整体趋势下滑",
  "- 第 2 层:华东区贡献 -8pct",
  "4. **💡 行动建议**",
  "- 建议动作:收紧华东区折扣",
  "5. **📎 口径说明** M001",
].join("\n");
// Body lines intentionally keep their list markers (cleanLeadingDecoration
// preserves `- ` / numbered prefixes for buildActionableBody to split on).
ok("emoji-结论", C(t1), "2024 Q3 收入同比下降 12.4%,主因华东区乏力 [M001]");
ok("emoji-根因", R(t1), "- 第 1 层:整体趋势下滑\n- 第 2 层:华东区贡献 -8pct");
ok("emoji-建议", A(t1), "- 建议动作:收紧华东区折扣");

console.log("--- emoji dropped, bold name header (the reported gap) ---");
const t2 = ["**结论**:本期营收 3.42 亿元,环比 +2.1%", "**根因分析**", "- 整体趋势平稳", "**行动建议**", "- 维持现有节奏"].join("\n");
ok("bold-结论", C(t2), "本期营收 3.42 亿元,环比 +2.1%");
ok("bold-根因", R(t2), "- 整体趋势平稳");
ok("bold-建议", A(t2), "- 维持现有节奏");

console.log("--- emoji dropped, ## heading ---");
const t3 = ["## 结论", "收入下降 5%", "## 根因分析", "- 客户流失", "## 行动建议", "- 启动挽留"].join("\n");
ok("h2-结论", C(t3), "收入下降 5%");
ok("h2-根因", R(t3), "- 客户流失");
ok("h2-建议", A(t3), "- 启动挽留");

console.log("--- report-generator 关键结论 / 管理建议 ---");
const t4 = ["📋 报表封面 ……", "📌 关键结论", "1. 收入 12 亿", "2. 销毛率 18%", "💡 管理建议", "1. 优化产业结构"].join("\n");
ok("rg-关键结论", C(t4), "1. 收入 12 亿\n2. 销毛率 18%");
ok("rg-管理建议", A(t4), "1. 优化产业结构");

console.log("--- false-positive guard ---");
const t5 = ["📌 结论:收入正常", "🔍 根因分析", "- 建议各部门留意季节性", "- 结论性判断:无异常"].join("\n");
ok("guard-结论", C(t5), "收入正常");
ok("guard-根因-keeps-body", R(t5), "- 建议各部门留意季节性\n- 结论性判断:无异常");

console.log("--- no markers at all ---");
ok("none", C("就是一段普通文字,没有结构。"), null);

console.log("\n" + pass + " passed, " + fail + " failed");
process.exit(fail ? 1 : 0);
