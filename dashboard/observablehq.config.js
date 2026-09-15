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
  header: `<nav class="toolbox-site-nav" aria-label="Primary">
    <a class="toolbox-site-brand" href="/">Studio Moser <span>Harness Testing</span></a>
    <span class="toolbox-site-current" aria-current="page">Toolbox</span>
  </nav>`,
  footer: "Studio Moser Harness Testing · test definitions only"
};
