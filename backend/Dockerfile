# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data/fastf1-cache /data/imports \
    && chown -R appuser:appuser /data

COPY pyproject.toml README.md alembic.ini ./
COPY migrations ./migrations
COPY src ./src

RUN python -m pip install --no-cache-dir .

USER appuser

FROM base AS development

USER root
RUN python -m pip install --no-cache-dir -e '.[dev]'
USER appuser

FROM base AS production

CMD ["f1-api"]
