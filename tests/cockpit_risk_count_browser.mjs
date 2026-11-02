/* Run against tests/cockpit_performance_preview.py only. No real AP/model/user data. */
import assert from 'node:assert/strict';

const base = process.env.COCKPIT_QA_URL || 'http://127.0.0.1:8896';
if (!['127.0.0.1', 'localhost'].includes(new URL(base).hostname)) {
  throw new Error('Browser tests are restricted to localhost QA fixtures');
}
const cdp = process.env.COCKPIT_QA_CDP || 'http://127.0.0.1:9337';
const target = await (await fetch(cdp + '/json/new?about:blank', {method: 'PUT'})).json();
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise(resolve => { ws.onopen = resolve; });

let sequence = 0;
const pending = new Map();
const exceptions = [];
ws.onmessage = event => {
  const message = JSON.parse(event.data);
  if (message.id) {
    const call = pending.get(message.id);
    if (call) {
      pending.delete(message.id);
      message.error ? call.reject(new Error(JSON.stringify(message.error))) : call.resolve(message.result);
    }
  }
  if (message.method === 'Runtime.exceptionThrown') {
    exceptions.push(message.params.exceptionDetails.exception?.description || message.params.exceptionDetails.text);
  }
};

const send = (method, params = {}) => new Promise((resolve, reject) => {
  pending.set(++sequence, {resolve, reject});
  ws.send(JSON.stringify({id: sequence, method, params}));
});
const evaluate = async expression => {
  const result = await send('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true});
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
  return result.result?.value;
};
const wait = async (expression, timeout = 20000) => {
  const until = Date.now() + timeout;
  while (Date.now() < until) {
    if (await evaluate(expression)) return;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error('Browser condition timeout: ' + expression);
};
const change = body => fetch(base + '/debug/change', {
  method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
});
const navigate = page => send('Page.navigate', {url: base + '/cockpit/' + page + '?id=1'});
const assertNoLoadError = async () => {
  assert.equal(await evaluate('document.querySelector(".cockpit-state.error")?.innerText || ""'), '');
  assert.ok(!(await evaluate('document.body.innerText')).includes('看板配置加载失败'));
};

try {
  await fetch(base + '/debug/reset', {method: 'POST'});
  await change({runtimeDelayMs: 1500, fail: false});
  await fetch(base + '/debug/seed-risk-cards?count=3', {method: 'POST'});
  await send('Page.enable');
  await send('Runtime.enable');
  await send('Network.enable');
  await send('Network.setCacheDisabled', {cacheDisabled: true});

  await navigate('overview');
  await wait('!!document.querySelector("#app:not([v-cloak]) .cockpit-board")');
  await wait('document.body.innerText.includes("3条风险")');
  await assertNoLoadError();
  const timing = await evaluate(`performance.getEntriesByType('resource')
    .filter(entry => entry.name.includes('/api/cockpit/ai-publications') || entry.name.includes('/metadata/runtime.json'))
    .map(entry => ({name: entry.name, end: entry.responseEnd}))`);
  const cards = timing.filter(entry => entry.name.includes('/api/cockpit/ai-publications')).at(-1);
  const runtime = timing.filter(entry => entry.name.includes('/metadata/runtime.json')).at(-1);
  assert.ok(cards && runtime, 'AI publication and runtime resource timings must exist');
  assert.ok(cards.end < runtime.end, 'AI cards must return before runtime binding');
  console.log('PASS AI cards bind before runtime without a load error');

  for (const page of ['operations', 'analysis']) {
    await navigate(page);
    await wait('!!document.querySelector("#app:not([v-cloak]) .cockpit-board")');
    await assertNoLoadError();
    console.log('PASS initial page ' + page);
  }

  await navigate('overview');
  await wait('!!document.querySelector("#app:not([v-cloak]) .cockpit-board")');
  for (const [label, page] of [['运营360整体分析', 'operations'], ['穿透式问题分析', 'analysis']]) {
    await evaluate(`[...document.querySelectorAll('.pro-bi-tab-container__tab')]
      .find(element => element.textContent.trim() === ${JSON.stringify(label)}).click()`);
    await wait(`location.pathname.endsWith('/cockpit/${page}')`);
    await wait('!!document.querySelector("#app:not([v-cloak]) .cockpit-board")');
    await assertNoLoadError();
    console.log('PASS tab ' + page);
  }

  await navigate('overview');
  await wait('!!document.querySelector("#app:not([v-cloak]) .cockpit-board")');
  await wait('document.body.innerText.includes("3条风险")');
  await evaluate(`[...document.querySelectorAll('.pro-radio-button')]
    .find(element => element.textContent.trim() === "月度").click()`);
  await wait(`[...document.querySelectorAll('.pro-radio-button.is-active')]
    .some(element => element.textContent.trim() === "月度")`);
  await wait('!!document.querySelector("#app:not([v-cloak]) .cockpit-board")');
  await wait('document.body.innerText.includes("3条风险")');
  await assertNoLoadError();
  assert.deepEqual(exceptions, []);
  console.log('PASS filter rebuild keeps the bound risk labels and raises no exceptions');
} finally {
  await send('Page.close');
  ws.close();
}
