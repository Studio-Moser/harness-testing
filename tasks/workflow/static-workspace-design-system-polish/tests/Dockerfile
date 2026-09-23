FROM studio-moser/harness-testing-node:0.2.0 AS node-runtime
FROM studio-moser/harness-testing-verifier:0.2.0 AS verifier-runtime
FROM mcr.microsoft.com/playwright/python:v1.62.0-noble@sha256:aa81288e738725378becba5b3e06cb0f3a7f012a610e87e8d767a090ea3f740d
COPY --from=verifier-runtime /usr/local /usr/local
RUN python -m pip install --no-cache-dir playwright==1.62.0

COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node-runtime /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && node --version \
    && npm --version

COPY Verifier/package.json Verifier/package-lock.json /opt/static-sentinel/
RUN cd /opt/static-sentinel \
    && npm ci --ignore-scripts --no-audit --no-fund

COPY --chmod=755 . /tests/
