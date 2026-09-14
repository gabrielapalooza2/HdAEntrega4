#!/usr/bin/env bash
# Deja el sistema listo para una toma nueva, SIN rearmar el cluster.
#
# Borra los datos de los dos servicios y vuelve a sembrar reglas y proveedores.
# Tarda segundos, a diferencia de `make limpiar && make infra`, que tarda minutos.
set -euo pipefail
cd "$(dirname "$0")/.."

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
for _ in $(seq 1 60); do
  r=$(docker exec db-trabajos psql -U trabajos -d trabajos -tAc \
      "SELECT count(*) FROM proyeccion_regla_partner" 2>/dev/null | tr -d ' ')
  h=$(curl -s --max-time 2 localhost:8000/health 2>/dev/null | grep -o '"habilitaciones":[0-9]*' | cut -d: -f2)
  [ "${r:-0}" -ge 4 ] && [ "${h:-0}" -ge 3 ] && break
  printf .
done
echo " listo"
echo
echo "    orquestacion:   $(curl -s localhost:5001/health)"
echo "    emparejamiento: $(curl -s localhost:8000/health)"
echo
echo "Listo para grabar."
