FROM python:3.12-slim AS base

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --requirement requirements.txt

COPY src ./src
COPY helpers ./helpers

RUN useradd --create-home --uid 10001 stackplan
USER stackplan


FROM base AS runtime

ENTRYPOINT ["python", "-m", "src.main"]


FROM base AS test

USER root
COPY requirements-dev.txt ./requirements-dev.txt
RUN python -m pip install --no-cache-dir --requirement requirements-dev.txt
COPY tests ./tests
COPY frontend ./frontend
COPY pyproject.toml ./pyproject.toml
RUN mkdir -p /app/test-results && chown stackplan:stackplan /app/test-results
USER stackplan

ENV COVERAGE_FILE=/tmp/stackplan.coverage
ENTRYPOINT ["python", "tests/verify.py", "container"]

FROM node:22-slim AS presentation-test
WORKDIR /app
COPY frontend/static ./frontend/static
COPY frontend/package.json ./frontend/package.json
COPY tests/frontend ./tests/frontend
ENTRYPOINT ["npm", "run", "check", "--prefix", "frontend"]
