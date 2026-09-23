export function runInvoiceJob(permissions,job) { return permissions.can(job.user,job.workspace,'write') ? 'updated' : 'denied'; }
