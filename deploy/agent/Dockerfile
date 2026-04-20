FROM python:3.11-alpine

LABEL org.opencontainers.image.title="AI SRE Log Reader Agent"

WORKDIR /app
COPY log_reader_agent.py .

RUN addgroup -S sre && adduser -S sre -G sre
USER sre

ENV OPERATOR_API_URL="http://ai-sre-operator-api.ai-sre.svc:8000" \
    TARGET_NAMESPACES="dev,qa,default" \
    TAIL_LINES="100" \
    REPORT_INTERVAL="30" \
    LOG_LEVEL="INFO"

ENTRYPOINT ["python", "log_reader_agent.py"]
