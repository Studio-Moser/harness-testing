export default {
  root: "src",
  output: process.env.HARNESS_DASHBOARD_OUTPUT ?? "dist",
  title: "Harness Testing",
  home: "Results",
  preserveExtension: true,
  sidebar: false,
  theme: [],
  pager: false,
  pages: [],
  globalStylesheets: [
    "https://cdn.jsdelivr.net/npm/@tabler/core@1.5.1/dist/css/tabler.min.css"
  ],
  head: `<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' fill='%23206bc4'/%3E%3Cpath d='M9 10h14v3H9zm0 5h9v3H9zm0 5h14v3H9z' fill='white'/%3E%3C/svg%3E">`,
  header: `<nav class="navbar navbar-expand-md navbar-light" aria-label="Primary">
    <div class="container-xl">
      <a class="navbar-brand" href="/">Studio Moser <span class="text-secondary fw-normal ms-2">Harness Testing</span></a>
      <ul class="navbar-nav flex-row flex-wrap gap-3">
        <li class="nav-item"><a class="nav-link" data-nav="results" href="/">Results</a></li>
        <li class="nav-item"><a class="nav-link" data-nav="toolbox" href="/Toolbox.html">Toolbox</a></li>
        <li class="nav-item"><a class="nav-link" data-nav="harnesses" href="/Harnesses.html">Harnesses</a></li>
      </ul>
    </div>
  </nav>`,
  footer: "Studio Moser Harness Testing · local benchmark evidence"
};
