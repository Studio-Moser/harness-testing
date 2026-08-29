FROM python:3.12.14-slim-bookworm@sha256:0f5b26b9518d002b6173fd61daad821fa340635ebfec5bba471013f9ca114579

RUN python -m pip install --no-cache-dir harbor-rewardkit==0.1.7 \
    && rewardkit --help >/dev/null

COPY src/harness_testing/__init__.py src/harness_testing/Contract_Criteria.py \
    src/harness_testing/Contract_Stub_Server.py \
    src/harness_testing/Trajectory_Events.py src/harness_testing/Workflow_Criteria.py \
    /usr/local/lib/python3.12/site-packages/harness_testing/

WORKDIR /tests
