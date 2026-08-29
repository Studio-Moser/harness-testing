FROM studio-moser/harness-testing-rust:0.1.0

COPY Cargo.toml Cargo.lock ./
COPY src ./src
COPY tests ./tests
RUN cargo metadata --locked --offline --no-deps >/dev/null
