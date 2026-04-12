FROM python:3.11-slim

LABEL org.opencontainers.image.title="AI K8s SRE Operator"
LABEL org.opencontainers.image.description="AI-powered Kubernetes SRE operator"
LABEL org.opencontainers.image.version="0.1.0"
LABEL org.opencontainers.image.authors="Anil Thotakura"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEMO_MODE=1 \
    LOG_LEVEL=INFO

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd -r -u 1001 -g root sreoperator && \
    chown -R sreoperator:root /app && \
    chmod -R g=u /app

USER 1001

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
