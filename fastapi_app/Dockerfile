FROM python:3.10-slim

WORKDIR /app

# Install standard dependencies directly to keep image self-contained
RUN pip install --no-cache-dir \
    fastapi \
    uvicorn \
    prometheus-client \
    opentelemetry-api \
    opentelemetry-sdk \
    opentelemetry-instrumentation-fastapi \
    opentelemetry-exporter-jaeger

COPY main.py .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
