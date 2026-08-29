FROM python:3.12.14-slim-bookworm@sha256:0f5b26b9518d002b6173fd61daad821fa340635ebfec5bba471013f9ca114579 AS mcp-runtime

RUN python -m pip install --no-cache-dir mcp==2.1.1

FROM studio-moser/harness-testing-node:0.1.0

COPY --from=mcp-runtime /usr/local /usr/local
COPY Fixture/ /app/

RUN python -c "from importlib.metadata import version; print(version('mcp'))"
