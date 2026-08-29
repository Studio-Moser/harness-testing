FROM studio-moser/harness-testing-verifier:0.1.0

COPY Scenario.json /opt/harness-contract/Scenario.json
RUN mkdir -p /var/log/harness

CMD ["python", "-m", "harness_testing.Contract_Stub_Server", "--scenario", "/opt/harness-contract/Scenario.json", "--events", "/var/log/harness/Events.jsonl"]
