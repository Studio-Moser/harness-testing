export function runNext(queue, handler, fault = () => {}) {
  const job = queue.claim();
  if (!job) return null;
  fault('after-claim', job);
  const result = handler(job.payload, job);
  const completed = queue.complete(job.id, result);
  fault('after-complete', completed);
  return completed;
}
