const clone = (value) => structuredClone(value);
const same = (left, right) => JSON.stringify(left) === JSON.stringify(right);

export class DurableQueue {
  constructor(store) { this.store = store; this.state = store.load(); }
  enqueue(key, payload) {
    const existing = [...this.state.pending, ...this.state.inFlight].find((job) => job.key === key);
    if (existing) return clone(existing);
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
