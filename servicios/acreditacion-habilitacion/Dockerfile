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
ENV HTTP_PORT=5000

EXPOSE 5000

HEALTHCHECK --interval=10s --timeout=5s --start-period=40s --retries=12 \
    CMD curl -fsS http://localhost:5000/health || exit 1

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "4", "--access-logfile", "-", "--error-logfile", "-", "infraestructura.http.api:app"]
