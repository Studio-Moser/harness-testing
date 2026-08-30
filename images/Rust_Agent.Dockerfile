FROM node:22.23.2-bookworm-slim@sha256:83f487e0a63425e5b4d146fb5e5be574bcbe1b7b843d3ebafdd95eaf7767a7e5 AS agent-tools

RUN npm install --global --no-audit --no-fund \
        @anthropic-ai/claude-code@2.1.236 \
        @openai/codex@0.150.1 \
    && claude --version \
    && codex --version

FROM rust:1.89.0-bookworm@sha256:948f9b08a66e7fe01b03a98ef1c7568292e07ec2e4fe90d88c07bb14563c84ff

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        build-essential \
        ca-certificates \
        git \
        jq \
        ripgrep \
    && rm -rf /var/lib/apt/lists/*

COPY --from=agent-tools /usr/local/bin/node /usr/local/bin/node
COPY --from=agent-tools /usr/local/lib/node_modules /usr/local/lib/node_modules

RUN ln -s ../lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe /usr/local/bin/claude \
    && ln -s ../lib/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex

RUN printf '%s\n' 'export PATH="${CARGO_HOME:-/usr/local/cargo}/bin:$PATH"' \
        > /etc/profile.d/rust-path.sh

RUN node --version \
    && claude --version \
    && codex --version \
    && rustc --version \
    && cargo --version

WORKDIR /app
