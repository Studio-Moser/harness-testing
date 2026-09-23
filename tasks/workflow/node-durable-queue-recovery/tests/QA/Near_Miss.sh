#!/usr/bin/env sh
set -eu
cd /app
cat > 'src/Durable_Queue.js' <<'FIXTURE_EOF'
const clone = (value) => structuredClone(value);
const same = (left, right) => JSON.stringify(left) === JSON.stringify(right);

export class DurableQueue {
  constructor(store) {
    this.store = store;
    this.state = store.load();
    if (this.state.inFlight.length) {
      this.state.pending = [...this.state.inFlight, ...this.state.pending];
      this.state.inFlight = [];
      this.store.save(this.state);
    }
  }
  findByKey(key) {
    return [...this.state.pending, ...this.state.inFlight, ...this.state.completed]
      .find((job) => job.key === key);
  }
  enqueue(key, payload) {
    const existing = this.findByKey(key);
    if (existing) {
      if (!same(existing.payload, payload)) throw new Error(`idempotency key ${key} has different input`);
      return clone(existing);
    }
    const job = {id: this.state.nextId++, key, payload: clone(payload), attempts: 0};
    this.state.pending.push(job);
    this.store.save(this.state);
    return clone(job);
  }
  claim() {
    const job = this.state.pending.shift();
    if (!job) return null;
    job.attempts += 1;
    this.state.inFlight.push(job);
    this.store.save(this.state);
    return clone(job);
  }
  complete(id, result) {
    const prior = this.state.completed.find((job) => job.id === id);
    if (prior) return clone(prior);
    const index = this.state.inFlight.findIndex((job) => job.id === id);
    if (index < 0) throw new Error(`job ${id} is not in flight`);
    const [job] = this.state.inFlight.splice(index, 1);
    const completed = {...job, result: clone(result)};
    this.state.completed.push(completed);
    this.store.save(this.state);
    return clone(completed);
  }
  snapshot() { return clone(this.state); }
}
FIXTURE_EOF
