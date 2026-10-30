import assert from "node:assert/strict";
import test from "node:test";
import { bootUrlPrompt, submitPromptFromUrl } from "../../bi_agent/web/static/url-prompt.mjs";

function browser(href) {
  const location = { href };
  const history = {
    state: { navigation: "workbench" },
    replaceState(state, title, url) {
      assert.equal(state, this.state);
      location.href = url;
    },
  };
  return { location, history };
}

test("waits for bootstrap, decodes the prompt, and preserves other URL state", async () => {
  const prompt = "分析采购 & 利润 + 成本\n本月/上月? #明细";
  const page = browser(`https://example.com/api/analytics/workbench?layout=single&prompt=${encodeURIComponent(prompt)}&theme=light#chat`);
  let resolveReady;
  const ready = new Promise((resolve) => { resolveReady = resolve; });
  const sent = [];
  const pending = submitPromptFromUrl({ ...page, ready, submit: (text) => sent.push(text) });
  await Promise.resolve();
  assert.deepEqual(sent, []);
  assert.ok(new URL(page.location.href).searchParams.has("prompt"));
  resolveReady();
  assert.equal(await pending, true);
  assert.deepEqual(sent, [prompt]);
  assert.equal(page.location.href, "https://example.com/api/analytics/workbench?layout=single&theme=light#chat");
});

test("missing or whitespace-only prompts do not submit", async () => {
  for (const query of ["", "?prompt=", "?prompt=%20%0A%09"]) {
    const page = browser(`https://example.com/${query}`);
    const original = page.location.href;
    assert.equal(await submitPromptFromUrl({ ...page, submit: () => assert.fail("unexpected submit") }), false);
    assert.equal(page.location.href, original);
  }
});

test("concurrent initialization and refresh submit only once", async () => {
  const page = browser("https://example.com/?prompt=first&prompt=second");
  const sent = [];
  const options = { ...page, submit: (text) => sent.push(text) };
  await Promise.all([submitPromptFromUrl(options), submitPromptFromUrl(options)]);
  assert.deepEqual(sent, ["first"]);
  assert.equal(page.location.href, "https://example.com/");
  assert.equal(await submitPromptFromUrl(options), false);
});

test("a failed request is consumed without automatic retries", async () => {
  const page = browser("https://example.com/workbench?prompt=hello");
  await assert.rejects(submitPromptFromUrl({ ...page, submit: async () => { throw new Error("offline"); } }), /offline/);
  assert.equal(await submitPromptFromUrl({ ...page, submit: () => assert.fail("unexpected retry") }), false);
});

test("the page module waits for runtime bindings and submits through the composer", async () => {
  const page = browser("https://example.com/workbench?prompt=%E9%87%87%E8%B4%AD%2B%E6%88%90%E6%9C%AC");
  const window = Object.assign(new EventTarget(), page, { Event });
  const events = [];
  const input = { value: "", dispatchEvent: (event) => events.push(event.type) };
  const sent = [];
  const button = { click: () => sent.push(input.value) };
  const document = {
    body: { dataset: {} },
    getElementById: (id) => id === "chat-input" ? input : button,
  };
  const pending = bootUrlPrompt(window, document);
  await Promise.resolve();
  assert.deepEqual(sent, []);
  document.body.dataset.layout = "single";
  window.dispatchEvent(new Event("bi-viewport-mode"));
  assert.equal(await pending, true);
  assert.deepEqual(sent, ["采购+成本"]);
  assert.deepEqual(events, ["input"]);
  assert.equal(await bootUrlPrompt(window, document), false);
});
