import test from 'node:test';
import assert from 'node:assert/strict';

import {createPublicationPoller} from '../bi_agent/web/static/cockpit/publication-poll.js';

function harness(probe, apply = async () => ({active: false}), isHidden = () => false) {
  const jobs = [];
  const cleared = [];
  const poller = createPublicationPoller({
    probe, apply, isHidden,
    schedule: (fn, ms) => { jobs.push({fn, ms}); return jobs.length; },
    clear: id => { cleared.push(id); },
    immediateMs: 10, activeMs: 5000, idleMs: 15000, hiddenMs: 20000,
  });
  return {poller, jobs, cleared};
}

test('a failed status probe never stops the subscription', async () => {
  let calls = 0;
  const {poller, jobs} = harness(async () => {
    calls += 1;
    if (calls === 1) throw new Error('status endpoint unavailable');
    return {update: {status: 'idle'}};
  });
  poller.start();
  assert.deepEqual(jobs.map(job => job.ms), [10]);
  await jobs.shift().fn();
  // Failure keeps the short retry cadence instead of dropping the loop.
  assert.deepEqual(jobs.map(job => job.ms), [5000]);
  await jobs.shift().fn();
  assert.deepEqual(jobs.map(job => job.ms), [15000]);
  assert.equal(calls, 2);
});

test('an active server refresh polls faster than an idle one', async () => {
  const {poller, jobs} = harness(
    async () => ({update: {status: 'running'}}),
    async () => ({active: true}),
  );
  poller.start(0);
  await jobs.shift().fn();
  assert.deepEqual(jobs.map(job => job.ms), [5000]);
});

test('hidden tabs back off without stopping the loop', async () => {
  const {poller, jobs} = harness(async () => ({update: {status: 'idle'}}), undefined, () => true);
  poller.start(0);
  await jobs.shift().fn();
  assert.deepEqual(jobs.map(job => job.ms), [20000]);
});

test('a stopped poller never schedules another probe', async () => {
  const {poller, jobs, cleared} = harness(async () => ({update: {status: 'idle'}}));
  poller.start(0);
  const pending = jobs.shift();
  poller.stop();
  assert.equal(cleared.length, 1);
  await pending.fn();
  assert.equal(jobs.length, 0);
  assert.equal(poller.stopped, true);
});

test('poll ticks never overlap', async () => {
  let resolveProbe;
  let calls = 0;
  const {poller, jobs} = harness(() => {
    calls += 1;
    return new Promise(resolve => { resolveProbe = resolve; });
  });
  poller.start(0);
  const first = jobs.shift().fn();
  await Promise.resolve();
  // A poke while the current probe is in flight must not start a second one.
  poller.poke(0);
  const second = jobs.shift().fn();
  await Promise.resolve();
  assert.equal(calls, 1);
  resolveProbe({update: {status: 'idle'}});
  await Promise.all([first, second]);
  assert.equal(calls, 1);
  assert.deepEqual(jobs.map(job => job.ms), [15000]);
});
