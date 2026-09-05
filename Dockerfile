FROM python:3.11-slim

WORKDIR /app

# System deps for Pillow's image codecs.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg62-turbo \
    zlib1g \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY fridge_to_fork ./fridge_to_fork
COPY app.py ./
COPY templates ./templates

RUN pip install --no-cache-dir .

# Cloud Run injects $PORT and routes traffic to it — never hardcode 8000 here.
ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT}"]
