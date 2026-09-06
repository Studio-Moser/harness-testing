FROM mikefarah/yq:4.47.2@sha256:76def1f56f456ecc1c3173ea275218ee17139bc2018c5a07887b15afd88ec03e AS yaml-tools

FROM node:22.23.2-bookworm-slim@sha256:83f487e0a63425e5b4d146fb5e5be574bcbe1b7b843d3ebafdd95eaf7767a7e5

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        build-essential \
        ca-certificates \
        git \
        gh \
        python3 \
        jq \
        ripgrep \
    && rm -rf /var/lib/apt/lists/*

COPY --from=yaml-tools /usr/bin/yq /usr/local/bin/yq

RUN python3 --version && gh --version && yq --version

RUN npm install --global --no-audit --no-fund \
        @anthropic-ai/claude-code@2.1.236 \
        @openai/codex@0.153.4 \
    && claude --version \
    && codex --version

WORKDIR /app
