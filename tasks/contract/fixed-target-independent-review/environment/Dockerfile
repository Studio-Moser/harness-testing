FROM studio-moser/harness-testing-node:0.1.0

COPY --chmod=755 Harness_Stub.mjs /usr/local/bin/harness-stub
COPY Fixture/ /app/

RUN git init --quiet \
    && git config user.name "Benchmark Author" \
    && git config user.email "benchmark@example.invalid" \
    && git add src/Policy.ts \
    && GIT_AUTHOR_DATE="2025-01-01T00:00:00Z" \
       GIT_COMMITTER_DATE="2025-01-01T00:00:00Z" \
       git commit --quiet -m "Frozen review target" \
    && test "$(git rev-parse HEAD)" = "ef4d5362c2b7f262cc0a6f85574a004e5313eb43"
