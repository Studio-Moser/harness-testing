export default {
  root: "src",
  output: "dist",
  title: "Harness Test Toolbox",
  home: "Toolbox",
  preserveExtension: true,
  sidebar: false,
  pager: false,
  pages: [],
  globalStylesheets: [
    "https://cdn.jsdelivr.net/npm/@tabler/core@1.5.1/dist/css/tabler.min.css"
  ],
  head: `<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' fill='%23206bc4'/%3E%3Cpath d='M9 10h14v3H9zm0 5h9v3H9zm0 5h14v3H9z' fill='white'/%3E%3C/svg%3E">`,
  header: `<nav class="toolbox-site-nav" aria-label="Primary">
    <a class="toolbox-site-brand" href="/">Studio Moser <span>Harness Testing</span></a>
    <span class="toolbox-site-current" aria-current="page">Toolbox</span>
  </nav>`,
  footer: "Studio Moser Harness Testing · test definitions only"
};
