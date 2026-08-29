FROM studio-moser/harness-testing-rust:0.1.0

COPY Cargo.toml Cargo.lock ./
COPY crates ./crates
RUN cargo metadata --locked --offline --no-deps >/dev/null
