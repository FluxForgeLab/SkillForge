FROM python:3.12-slim

RUN useradd --create-home --uid 1000 --shell /bin/sh sandbox \
    && mkdir -p /workspace/runtime \
    && chown -R sandbox:sandbox /workspace

USER sandbox
WORKDIR /workspace
