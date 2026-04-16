FROM python:3.11-alpine

LABEL org.opencontainers.image.title="AI K8s SRE Agent"
LABEL org.opencontainers.image.description="Lightweight sidecar agent for application log monitoring"
LABEL org.opencontainers.image.source="https://github.com/anil-114912/ai-k8s-sre-operator"

# Only need PyYAML — stdlib covers everything else (urllib, re, threading, json)
RUN pip install --no-cache-dir pyyaml==6.0.1

WORKDIR /app

COPY agent/ ./agent/

# Non-root user
RUN addgroup -S sre && adduser -S sre -G sre
USER sre

# Buffer dir writable by sre user
RUN mkdir -p /tmp/apm_buffer

ENV LOG_PATH="/var/log/app/app.log" \
    OPERATOR_API_URL="http://ai-sre-operator.ai-sre.svc:8000" \
    REPORT_INTERVAL_SECS="30" \
    LOG_LEVEL="INFO"

ENTRYPOINT ["python", "-m", "agent.main"]
