FROM python:3.11-slim

# Without this, Python fully block-buffers stdout when it isn't a TTY (true
# in any container) — print() output only flushes in bursts, so Render's
# log timestamps stop reflecting real execution order/timing. Confirmed
# live (2026-09-30 incident investigation): multiple log lines a real
# fallback-chain grind apart shared the same microsecond timestamp, making
# it impossible to tell whether a request actually exceeded app.py's 60s
# vision timeout or the logs just looked that way.
ENV PYTHONUNBUFFERED=1

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
