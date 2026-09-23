FROM studio-moser/harness-testing-node:0.2.0 AS node-runtime
FROM mcr.microsoft.com/playwright/python:v1.62.0-noble@sha256:aa81288e738725378becba5b3e06cb0f3a7f012a610e87e8d767a090ea3f740d
COPY --from=node-runtime /usr/local /usr/local
RUN python -m pip install --no-cache-dir playwright==1.62.0 \
    && apt-get update && apt-get install -y --no-install-recommends git ripgrep gh \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund

COPY . .

RUN git init --quiet --initial-branch=main \
    && git config user.name "Benchmark Author" \
    && git config user.email "benchmark@example.invalid" \
    && printf '%s\n' \
        'AGENTS.md' \
        'CLAUDE.md' \
        'node_modules/' \
        'target/' \
        'dist/' \
        > .git/info/exclude \
    && git add --all \
    && GIT_AUTHOR_DATE="2025-01-01T00:00:00Z" \
       GIT_COMMITTER_DATE="2025-01-01T00:00:00Z" \
       git commit --quiet -m "Frozen workflow fixture" \
    && test -z "$(git status --porcelain)"
