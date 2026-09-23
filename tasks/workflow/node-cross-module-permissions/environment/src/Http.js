export function updateInvoice(permissions,user,workspace) { return permissions.can(user,workspace,'write') ? 200 : 403; }
