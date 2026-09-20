FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends gcc curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY scripts/ ./scripts/
COPY tests/ ./tests/
ENV PYTHONPATH=/app/src CONTRATOS_DIR=/app/contratos

EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --retries=12 \
  CMD curl -fsS http://localhost:8080/health || exit 1

# Un solo worker: los consumidores de la proyeccion viven como hilos dentro del
# proceso. Con varios workers habria una proyeccion por worker y las respuestas
# variarian segun a cual cayera la peticion. Para escalar se suben REPLICAS.
CMD ["uvicorn", "bff.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
