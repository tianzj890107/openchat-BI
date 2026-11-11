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
