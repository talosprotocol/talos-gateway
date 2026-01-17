# Talos Gateway - Dockerfile
FROM python:3.11-slim

LABEL org.opencontainers.image.licenses="Apache-2.0"

WORKDIR /app

# Install curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Copy requirements first for caching
COPY services/gateway/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Install local SDK
COPY sdks/python /sdks/python
RUN pip install --no-cache-dir /sdks/python

# Install Contracts
COPY contracts/python /contracts/python
RUN pip install --no-cache-dir /contracts/python

# Copy application
COPY services/gateway/ .

# Environment
ENV PYTHONUNBUFFERED=1
ENV TALOS_GATEWAY_PORT=8080

# Health check
HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
