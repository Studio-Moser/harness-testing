Work in `/app`. Tasklog 3.0 removed the `--legacy-sync` flag; its replacement is `--sync=full`. Update every Markdown page under docs/ that still mentions `--legacy-sync` to say `--sync=full` instead, and change nothing else in those pages. Leave docs/History.txt as it is: it records past releases.

Preserve existing tests, package metadata and build configuration. Complete the local task; do not publish or deploy.
