/* Server-owned AI slot publications.
 *
 * This client only reads persisted cards.  It never waits for AP queries,
 * metrics or a model job, and a failed poll leaves the last payloads in place.
 */
export const AI_PUBLICATION_REGISTRY = 'cockpit-ai-slots-v1';

export function createAiPublicationClient({
  apiBase, id, request = fetch, onUpdate = () => {}, onError = () => {},
  pollMs = 15000, activeMs = 5000, hiddenMs = 30000,
  isHidden = () => false,
  schedule = (fn, ms) => setTimeout(fn, Math.max(250, ms)),
  clear = token => clearTimeout(token),
}) {
  let timer = null, running = false, stopped = true, generation = 0;
  let currentScope = 'default', lastVersion = '';

  function url(scope) {
    const query = new URLSearchParams({id: String(id), uiScope: scope});
    return `${apiBase}/ai-publications?${query}`;
  }

  async function load({uiScope = currentScope, preserve = true, force = false} = {}) {
    const token = ++generation;
    const scope = String(uiScope || 'default');
    try {
      const response = await request(url(scope), {headers: {Accept: 'application/json'}});
      let body;
      try { body = await response.json(); } catch (_) { throw new Error('AI 卡片响应无效'); }
      if (!response.ok) throw new Error(typeof body?.detail === 'string' ? body.detail : 'AI 卡片读取失败');
      if (token !== generation) return null;
      const unchanged = !force && body.version === lastVersion && currentScope === scope;
      currentScope = scope;
      lastVersion = body.version || '';
      onUpdate(body, {unchanged, preserve, scope});
      return body;
    } catch (error) {
      if (token !== generation) return null;
      onError(error);
      return null;
    }
  }

  function plan(delay) {
    if (stopped) return;
    if (timer !== null) clear(timer);
    timer = schedule(tick, delay);
  }

  async function tick() {
    timer = null;
    if (stopped || running) return;
    if (isHidden()) { plan(hiddenMs); return; }
    running = true;
    try {
      const value = await load({uiScope: currentScope, preserve: true});
      plan(value?.updatingCount || value?.manualUpdate?.status==='running' ? activeMs : pollMs);
    } finally {
      running = false;
      if (!stopped && timer === null) plan(pollMs);
    }
  }

  return {
    load,
    start(scope = currentScope) {
      currentScope = String(scope || 'default');
      stopped = false;
      plan(0);
    },
    poke(delay = 0, scope = currentScope) {
      currentScope = String(scope || currentScope);
      plan(delay);
    },
    stop() {
      stopped = true;
      generation += 1;
      if (timer !== null) { clear(timer); timer = null; }
    },
    get scope() { return currentScope; },
    get version() { return lastVersion; },
  };
}
