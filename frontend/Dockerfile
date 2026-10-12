FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --requirement requirements.txt

COPY app.py ./app.py
COPY templates ./templates
COPY static ./static

RUN useradd --create-home --uid 10001 stackplan
USER stackplan

EXPOSE 5173

CMD ["gunicorn", "--bind", "0.0.0.0:5173", "--workers", "2", "--timeout", "1900", "--access-logfile", "-", "--error-logfile", "-", "--capture-output", "app:app"]
