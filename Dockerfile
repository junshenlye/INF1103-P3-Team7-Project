FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --requirement requirements.txt

RUN useradd --create-home appuser
COPY --chown=appuser:appuser src ./src
USER appuser

ENTRYPOINT ["python", "-m", "src.main"]
