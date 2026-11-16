export const NUMBER_TOKEN = /\d[\d,]*(?:\.\d+)?(?:\/\d+)?(?:\s*(?:亿元|个百分点|GWh|个|%|天))?/g

export function highlightNumbers(value) {
  const text = String(value ?? '')
  const parts = []
  let last = 0
  for (const match of text.matchAll(NUMBER_TOKEN)) {
    if (match.index > last) parts.push({text: text.slice(last, match.index), num: false})
    parts.push({text: match[0], num: true})
    last = match.index + match[0].length
  }
  if (last < text.length) parts.push({text: text.slice(last), num: false})
  return parts
}

// Ontology codes (RK01 风险、RC/AC 原因与建议、R01/B01/C01/S01/O01 指标、BR-Q02
// 规则、IS/DQ/DR、P0-01 子环节) are internal identifiers.  Card text shows only
// the wording; a bare stage name such as P0 or P2 is business text and stays.
const ONTOLOGY_CODE = String.raw`(?:BR-(?:DQ|[QACDL])|RK|RC|AC|IS|DQ|DR|[RBCSO])\d{2}(?:-[A-Z]+)*|P\d-\d{2}`
const ONTOLOGY_CODE_RUN = new RegExp(
  String.raw`(?<![A-Za-z0-9])(?:${ONTOLOGY_CODE})(?:\s*[–—~～/、,，和与及-]\s*(?:${ONTOLOGY_CODE}))*(?![A-Za-z0-9])`, 'g')

export function stripOntologyCodes(value) {
  const text = String(value ?? '')
  if (!text) return text
  ONTOLOGY_CODE_RUN.lastIndex = 0
  if (!ONTOLOGY_CODE_RUN.test(text)) return text
  return text
    .replace(ONTOLOGY_CODE_RUN, '')
    // Brackets left with no wording: （R13）、（本体 DR04）、(BR-Q04)
    .replace(/[（(]\s*(?:本体|按|见|即|规则|指标|口径)?\s*[)）]/g, '')
    // A colon that only followed a code: "BR-Q01：所选年度" → "所选年度"
    .replace(/(^|[，,；;。、（(\n])\s*[：:]\s*/g, '$1')
    .replace(/([、，,；;])\s*(?=[、，,；;。）)]|$)/g, '')
    .replace(/[ \t]{2,}/g, ' ')
    .replace(/([一-鿿（）【】])[ \t]+(?=[一-鿿（）【】])/g, '$1')
    .replace(/([，。；：、！？])[ \t]+/g, '$1')
    .replace(/[ \t]+(?=[，。；：、！？])/g, '')
    .replace(/^[\s、，,；;：:—-]+/, '')
    .trim()
}
