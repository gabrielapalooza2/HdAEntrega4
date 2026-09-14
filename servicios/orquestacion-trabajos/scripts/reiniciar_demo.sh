#!/usr/bin/env bash
# Deja el sistema listo para una toma nueva, SIN rearmar el cluster.
#
# Borra los datos de los dos servicios y vuelve a sembrar reglas y proveedores.
# Tarda segundos, a diferencia de `make limpiar && make infra`, que tarda minutos.
set -euo pipefail
cd "$(dirname "$0")/.."

# Se fijan ACA y no se confia en el entorno del que llama. Sin PULSAR_LISTENER,
# el broker le responde a un cliente del host con la direccion interna
# (broker:6650), que en el host no resuelve: la siembra falla EN SILENCIO y
# despues todo sale PARTNER_DESCONOCIDO. Es el fallo mas facil de cometer y el
# mas dificil de diagnosticar en medio de una grabacion.
: "${PULSAR_URL:=pulsar://localhost:6650}"
: "${PULSAR_LISTENER:=external}"
export PULSAR_URL PULSAR_LISTENER

echo "==> borrando datos de orquestacion"
docker exec db-trabajos psql -U trabajos -d trabajos -q -c \
  "TRUNCATE eventos_trabajo, outbox, proyeccion_trabajo, mensajes_procesados, proyeccion_regla_partner;"

echo "==> borrando datos de emparejamiento"
docker exec db-emparejamiento psql -U emparejamiento -d emparejamiento -tAc \
  "SELECT 'TRUNCATE '||string_agg(quote_ident(tablename),', ')||';' FROM pg_tables WHERE schemaname='public'" \
  | xargs -0 -I{} docker exec db-emparejamiento psql -U emparejamiento -d emparejamiento -q -c "{}" 2>/dev/null || true

echo "==> sembrando reglas de partner"
./.venv/bin/python scripts/seed.py >/dev/null

echo "==> sembrando proveedores (simula Acreditacion, que no existe)"
./.venv/bin/python scripts/sembrar_proveedores.py >/dev/null

echo -n "==> esperando a que las proyecciones carguen"
reglas=0; habs=0
for _ in $(seq 1 60); do
  reglas=$(docker exec db-trabajos psql -U trabajos -d trabajos -tAc \
      "SELECT count(*) FROM proyeccion_regla_partner" 2>/dev/null | tr -d ' \r' || echo 0)
  habs=$(curl -s --max-time 2 localhost:8000/health 2>/dev/null \
      | grep -o '"habilitaciones":[0-9]*' | cut -d: -f2 || echo 0)
  if [ "${reglas:-0}" -ge 4 ] && [ "${habs:-0}" -ge 3 ]; then break; fi
  printf .
  sleep 0.5
done
echo

# Verificacion DURA. Antes esto se quedaba callado si la siembra no llegaba, y
# el problema recien aparecia grabando, con todos los trabajos rechazados.
if [ "${reglas:-0}" -lt 4 ] || [ "${habs:-0}" -lt 3 ]; then
  echo
  echo "  ✗ LA SIEMBRA NO LLEGO  (reglas=$reglas de 4, habilitaciones=$habs de 3)"
  echo
  echo "    Revisa:"
  echo "      - los servicios estan arriba?   docker compose ps"
  echo "      - el broker responde?           curl -s localhost:5001/health"
  echo "      - hay otro Pulsar en el 6650?   docker ps | grep 6650"
  echo
  exit 1
fi

echo "  ✓ reglas=$reglas   habilitaciones=$habs"
echo "    orquestacion:   $(curl -s localhost:5001/health)"
echo "    emparejamiento: $(curl -s localhost:8000/health)"
echo
echo "Listo para grabar."
