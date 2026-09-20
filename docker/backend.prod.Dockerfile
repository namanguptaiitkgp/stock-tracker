FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Drop to a non-root user for the runtime layer.
RUN useradd --create-home --shell /usr/sbin/nologin app \
    && chown -R app:app /app
USER app

# Multi-worker uvicorn, no reload, proxy headers honored so X-Forwarded-* from
# the reverse proxy is trusted. Tune --workers via WORKERS env.
ENV WORKERS=4
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${WORKERS} --proxy-headers --forwarded-allow-ips=* --no-server-header"]
