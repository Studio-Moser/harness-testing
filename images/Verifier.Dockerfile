FROM python:3.12.14-slim-bookworm@sha256:0f5b26b9518d002b6173fd61daad821fa340635ebfec5bba471013f9ca114579

RUN python -m pip install --no-cache-dir harbor-rewardkit==0.1.7 \
    && rewardkit --help >/dev/null

WORKDIR /tests
