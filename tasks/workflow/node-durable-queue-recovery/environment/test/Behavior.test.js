import {mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {afterEach, describe, expect, it} from 'vitest';
import {DurableQueue} from '../src/Durable_Queue.js';
import {StateStore} from '../src/State_Store.js';
import {runNext} from '../src/Worker.js';

const directories = [];
afterEach(() => { for (const directory of directories.splice(0)) rmSync(directory, {recursive: true}); });
const fixture = (fault) => {
  const directory = mkdtempSync(join(tmpdir(), 'durable-queue-'));
  directories.push(directory);
  const path = join(directory, 'state.json');
  return {path, open: (nextFault = fault) => new DurableQueue(new StateStore(path, nextFault))};
};
const crashAt = (expected) => (stage) => { if (stage === expected) throw new Error(`crash:${stage}`); };

describe('durable queue recovery', () => {
  it('keeps idempotency permanent and duplicate completion stable', () => {
    const {open} = fixture();
    const queue = open();
    const first = queue.enqueue('email:7', {recipient: 'a@example.test'});
    expect(queue.enqueue('email:7', {recipient: 'a@example.test'}).id).toBe(first.id);
    expect(() => queue.enqueue('email:7', {recipient: 'other@example.test'})).toThrow(/idempotency/i);
    const claimed = queue.claim();
    expect(queue.enqueue('email:7', {recipient: 'a@example.test'})).toEqual(claimed);
    expect(() => queue.enqueue('email:7', {recipient: 'other@example.test'})).toThrow(/idempotency/i);
    const completed = queue.complete(claimed.id, {status: 'sent'});
    expect(queue.complete(claimed.id, {status: 'sent'})).toEqual(completed);
    expect(queue.enqueue('email:7', {recipient: 'a@example.test'})).toEqual(completed);
    expect(queue.snapshot()).toMatchObject({pending: [], inFlight: [], completed: [completed]});
  });

  it('recovers claimed work once across repeated restarts and preserves FIFO attempts', () => {
    const {open} = fixture();
    const queue = open();
    queue.enqueue('first', {value: 1});
    queue.enqueue('second', {value: 2});
    expect(() => runNext(queue, () => 'never', crashAt('after-claim'))).toThrow('crash:after-claim');
    const recovered = open();
    expect(recovered.snapshot()).toMatchObject({pending: [{key: 'first'}, {key: 'second'}], inFlight: []});
    expect(recovered.enqueue('first', {value: 1})).toMatchObject({key: 'first', attempts: 1});
    expect(() => recovered.enqueue('first', {value: 99})).toThrow(/idempotency/i);
    const reopened = open();
    expect(reopened.snapshot().pending).toHaveLength(2);
    const seen = [];
    runNext(reopened, (payload, job) => { seen.push([payload.value, job.attempts]); return payload.value; });
    runNext(reopened, (payload, job) => { seen.push([payload.value, job.attempts]); return payload.value; });
    expect(seen).toEqual([[1, 2], [2, 1]]);
  });

  it('does not rerun work after the completion boundary survives a crash', () => {
    const {open} = fixture();
    const queue = open();
    queue.enqueue('report:9', {month: 9});
    expect(() => runNext(queue, () => ({path: 'report.pdf'}), crashAt('after-complete'))).toThrow('crash:after-complete');
    const recovered = open();
    let calls = 0;
    expect(runNext(recovered, () => { calls += 1; })).toBeNull();
    expect(calls).toBe(0);
    expect(recovered.enqueue('report:9', {month: 9})).toMatchObject({result: {path: 'report.pdf'}});
  });

  it('keeps the previous committed snapshot when persistence faults before commit', () => {
    const {path, open} = fixture();
    const queue = open();
    queue.enqueue('safe', {value: 1});
    const faulting = new DurableQueue(new StateStore(path, crashAt('before-commit')));
    expect(() => faulting.enqueue('torn', {value: 2})).toThrow('crash:before-commit');
    expect(open().snapshot()).toMatchObject({pending: [{key: 'safe'}], inFlight: [], completed: []});
  });

  it('keeps claim and completion transitions at their last committed boundary', () => {
    const claimFixture = fixture();
    claimFixture.open().enqueue('claim', {value: 1});
    const claimFault = new DurableQueue(new StateStore(claimFixture.path, crashAt('before-commit')));
    expect(() => claimFault.claim()).toThrow('crash:before-commit');
    expect(claimFixture.open().snapshot()).toMatchObject({pending: [{key: 'claim', attempts: 0}], inFlight: []});

    const completeFixture = fixture();
    const original = completeFixture.open();
    original.enqueue('complete', {value: 2});
    original.claim();
    let fail = false;
    const completeFault = new DurableQueue(new StateStore(completeFixture.path, () => {
      if (fail) throw new Error('crash:before-commit');
    }));
    const retried = completeFault.claim();
    fail = true;
    expect(() => completeFault.complete(retried.id, {status: 'done'})).toThrow('crash:before-commit');
    expect(completeFixture.open().snapshot()).toMatchObject({
      pending: [{key: 'complete', attempts: 2}], inFlight: [], completed: [],
    });
  });
});
