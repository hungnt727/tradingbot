# Single app image for the Phase 6 web + worker services.
#
# The same image runs both — compose overrides the command:
#   web    -> python -m uvicorn web.app:app --host 0.0.0.0 --port 8000
#   worker -> python -m worker.daemon
#
# Bind 0.0.0.0 inside the container; host-side tailnet/firewall isolation lives
# in the compose port mapping (e.g. 127.0.0.1:8000:8000 + `tailscale serve`).

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Runtime libs (curl for healthchecks; ca-certificates for HTTPS to exchanges).
# psycopg2-binary ships its own libpq, so no libpq-dev needed at runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install deps first so requirement-only changes don't bust the code cache.
COPY requirements.txt .
RUN pip install -r requirements.txt

# Application code.
COPY . .

# Non-root user, owns /app.
RUN useradd --create-home --uid 1000 tradingbot \
    && chown -R tradingbot:tradingbot /app
USER tradingbot

EXPOSE 8000

# Default command = web. Compose overrides for the worker service.
CMD ["python", "-m", "uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8000"]
