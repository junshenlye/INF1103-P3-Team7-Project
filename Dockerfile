FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --requirement requirements.txt

COPY src ./src

ENTRYPOINT ["python", "-m", "src.main"]
