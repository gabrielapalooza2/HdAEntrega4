FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

ENV PYTHONPATH=/app
ENV CONTRATOS_DIR=/app/contratos
ENV HTTP_HOST=0.0.0.0
ENV HTTP_PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=40s --retries=12 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "infraestructura.http.api:app", "--host", "0.0.0.0", "--port", "8000"]
