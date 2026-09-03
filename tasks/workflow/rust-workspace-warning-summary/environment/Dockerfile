FROM studio-moser/harness-testing-rust:0.2.0

COPY .dockerignore ./
COPY Cargo.toml Cargo.lock ./
COPY crates ./crates
RUN cargo metadata --locked --offline --no-deps >/dev/null

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
