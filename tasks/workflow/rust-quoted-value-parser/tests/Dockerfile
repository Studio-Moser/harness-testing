FROM studio-moser/harness-testing-verifier:0.2.0 AS rewardkit-runtime
FROM studio-moser/harness-testing-rust:0.2.0

COPY --from=rewardkit-runtime /usr/local /usr/local
RUN python --version \
    && rewardkit --help >/dev/null \
    && rustc --version \
    && cargo --version

WORKDIR /tests
COPY --chmod=755 . /tests/
