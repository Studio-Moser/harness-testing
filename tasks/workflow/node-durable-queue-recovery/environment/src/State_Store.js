import {appendFileSync, mkdirSync, readFileSync, writeFileSync} from 'node:fs';
import {dirname} from 'node:path';

export const emptyState = () => ({version: 1, nextId: 1, pending: [], inFlight: [], completed: []});

export class StateStore {
  constructor(path, fault = () => {}) { this.path = path; this.fault = fault; }
  load() {
    try { return JSON.parse(readFileSync(this.path, 'utf8')); }
    catch (error) { if (error.code === 'ENOENT') return emptyState(); throw error; }
  }
  save(state) {
    mkdirSync(dirname(this.path), {recursive: true});
    const contents = JSON.stringify(state);
    const split = Math.ceil(contents.length / 2);
    writeFileSync(this.path, contents.slice(0, split));
    this.fault('before-commit');
    appendFileSync(this.path, contents.slice(split));
  }
}
