FROM node:22.23.2-bookworm-slim@sha256:83f487e0a63425e5b4d146fb5e5be574bcbe1b7b843d3ebafdd95eaf7767a7e5

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        build-essential \
        ca-certificates \
        git \
        jq \
        ripgrep \
    && rm -rf /var/lib/apt/lists/*

RUN npm install --global --no-audit --no-fund \
        @anthropic-ai/claude-code@2.1.236 \
        @openai/codex@0.150.1 \
    && claude --version \
    && codex --version

WORKDIR /app
