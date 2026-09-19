FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY scripts/ ./scripts/
ENV PYTHONPATH=/app/src

EXPOSE 5000
HEALTHCHECK --interval=10s --timeout=3s --retries=10 \
  CMD curl -fsS http://localhost:5000/health || exit 1

# Un worker por proceso: los hilos del relay y del consumidor viven dentro del
# proceso, y con varios workers de gunicorn habría un relay por worker compitiendo
# por las mismas filas del outbox. Para escalar se suben RÉPLICAS del contenedor,
# que es justamente lo que mide el escenario de escalabilidad.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "8", \
     "--access-logfile", "-", "motor_reglas.main:app"]
