FROM studio-moser/harness-testing-node:0.2.0

# The developer's shell is zsh with default options, so an unquoted glob that
# matches nothing aborts the command with "no matches found".
RUN apt-get update \
    && apt-get install --yes --no-install-recommends zsh=5.9-4+b15 \
    && rm -rf /var/lib/apt/lists/* \
    && chsh --shell /bin/zsh root \
    && chsh --shell /bin/zsh node \
    && touch /root/.zshrc /home/node/.zshrc \
    && chown node:node /home/node/.zshrc
ENV SHELL=/bin/zsh

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
