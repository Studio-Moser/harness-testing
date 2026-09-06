export default {
  root: "src",
  output: "dist",
  title: "Harness Testing",
  home: "Harness Testing",
  preserveExtension: true,
  pages: [
    {name: "Harness comparison", path: "/Comparisons"},
    {name: "Version history", path: "/Version_History"},
    {name: "Task evidence", path: "/Run_Detail"},
    {name: "Earlier diagnostics", pages: [
      {name: "Run evidence", path: "/Legacy_Run_Detail"},
      {name: "Trends", path: "/Trends"},
      {name: "Task matrix", path: "/Task_Matrix"},
      {name: "Quality and efficiency", path: "/Quality_Versus_Efficiency"}
    ]}
  ],
  footer: "Studio Moser Harness Testing · sanitized summaries only"
};
