/* One poll loop per page for server-owned publication updates.
 *
 * A failed status probe must never stop the subscription: the next check is
 * always scheduled from `finally`, independent of how the previous probe
 * settled.  The loop never overlaps itself and stops on page teardown.
 */
export function createPublicationPoller({
  probe, apply = async () => ({active: false}),
  immediateMs = 1000, activeMs = 5000, idleMs = 15000, hiddenMs = 20000,
  schedule = (fn, ms) => setTimeout(fn, Math.max(250, ms)),
  clear = id => clearTimeout(id), isHidden = () => false,
}) {
  let timer = null, running = false, stopped = false;
  function plan(delay) {
    if (stopped) return;
    if (timer !== null) clear(timer);
    timer = schedule(tick, delay);
  }
  async function tick() {
    timer = null;
    if (stopped) return;
    if (isHidden()) { plan(hiddenMs); return; }
    if (running) return;
    running = true;
    let delay = idleMs;
    try {
      const status = await probe();
      if (stopped) return;
      const result = await apply(status);
      delay = result && result.active ? activeMs : idleMs;
    } catch (_) {
      // Keep the last good cards and keep checking; a transient status error
      // is not a reason to abandon the page subscription.
      delay = activeMs;
    } finally {
      running = false;
      if (!stopped) plan(delay);
    }
  }
  return {
    start(delay = immediateMs) { stopped = false; plan(delay); },
    stop() { stopped = true; if (timer !== null) { clear(timer); timer = null; } },
    poke(delay = 0) { plan(delay); },
    get stopped() { return stopped; },
  };
}
