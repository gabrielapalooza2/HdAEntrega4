#!/usr/bin/env bash
# DEMO de la saga coreografiada de asignación (Entrega 5).
#
# Requiere el stack de Entrega 4 arriba (`make todo`).
# Muestra:
#   1. transacción larga exitosa  → saga COMPLETADA
#   2. fallo con compensación     → saga COMPENSADA
# y deja el saga log listo para `scripts/consulta_saga.sql`.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

MOTOR="${MOTOR:-http://localhost:5002}"
ORQ="${ORQ:-http://localhost:5001}"
ACR="${ACR:-http://localhost:5004}"
PAUSA="${PAUSA:-8}"

hr() { printf '\n\033[1m%s\033[0m\n%s\n' "$1" "────────────────────────────────────────────────────────────"; }
esperar() { printf '\033[2m(esperando %ss a la coreografía…)\033[0m\n' "$PAUSA"; sleep "$PAUSA"; }

psql_trabajos() {
  docker exec -i db-trabajos psql -U trabajos -d trabajos -v ON_ERROR_STOP=1 "$@"
}

hr "salud de los tres participantes de la saga"
curl -sf "$ORQ/health"
echo
curl -sf "$MOTOR/health"
echo
curl -sf "$ACR/health"
echo
curl -sf http://localhost:8000/health
echo

hr "semilla: partner con cobertura PLOMERIA (acto administrativo, no es la saga)"
RESP=$(curl -sS -X POST "$MOTOR/partners" -H 'Content-Type: application/json' -d '{
  "nombre": "Aseguradora Saga",
  "tipo_partner": "ASEGURADORA",
  "convenio_numero": "CONV-SAGA",
  "vigencia_desde": "2026-01-01T00:00:00Z",
  "porcentaje_comision": 10,
  "regla": {
    "cobertura_contratada": ["PLOMERIA"],
    "sla_minutos": 120,
    "monto_maximo_sin_aprobacion": {"monto": 50000000, "moneda": "COP"},
    "pasos_de_aprobacion": [],
    "red_homologada": ["11111111-1111-1111-1111-111111111001", "11111111-1111-1111-1111-111111111002"]
  }
}')
echo "$RESP"
PARTNER=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<<"$RESP")
echo "partner_id=$PARTNER"
esperar

hr "CAMINO FELIZ — proveedor habilitado en el dato autoritativo"
curl -sS -X POST "$ACR/proveedores" -H 'Content-Type: application/json' -d '{
  "proveedor_id": "11111111-1111-1111-1111-111111111001",
  "nombre": "Tecnico OK",
  "categorias": ["PLOMERIA"],
  "ciudades": ["Bogota"]
}'
echo
esperar

hr "CrearTrabajo de PLOMERIA en Bogota"
docker exec motor-reglas-partner python scripts/enviar_trabajo.py \
  --partner-id "$PARTNER" --categoria PLOMERIA --ciudad Bogota
esperar

hr "saga log — se espera COMPLETADA"
psql_trabajos -c "SELECT saga_id, estado, proveedor_id, paso_actual FROM saga_asignacion ORDER BY iniciada_en DESC LIMIT 3;"
psql_trabajos -c "SELECT secuencia, servicio, tipo_mensaje, rol, resultado FROM saga_paso ORDER BY ocurrido_en DESC, secuencia DESC LIMIT 8;"
curl -sS "$ORQ/sagas?estado=COMPLETADA"
echo

hr "CAMINO DE COMPENSACIÓN — proyección de emparejamiento desfasada"
curl -sS -X POST "$ACR/proveedores" -H 'Content-Type: application/json' -d '{
  "proveedor_id": "11111111-1111-1111-1111-111111111002",
  "nombre": "Tecnico stale",
  "categorias": ["PLOMERIA"],
  "ciudades": ["Bogota"]
}'
echo
curl -sS -X PATCH "$ACR/proveedores/11111111-1111-1111-1111-111111111002/suspender" \
  -H 'Content-Type: application/json' \
  -d '{"motivo":"LICENCIA_VENCIDA"}'
echo
esperar

hr "forzar proyección local HABILITADO (el desfase que justifica la saga)"
docker exec db-emparejamiento psql -U emparejamiento -d emparejamiento -c \
  "UPDATE proyeccion_habilitacion SET estado='HABILITADO' WHERE proveedor_id='11111111-1111-1111-1111-111111111002';
   SELECT proveedor_id, estado FROM proyeccion_habilitacion WHERE proveedor_id LIKE '11111111-1111-1111-1111-11111111100%';"

docker exec db-emparejamiento psql -U emparejamiento -d emparejamiento -c \
  "UPDATE proyeccion_habilitacion SET estado='SUSPENDIDO' WHERE proveedor_id='11111111-1111-1111-1111-111111111001';"

hr "CrearTrabajo que Emparejamiento asignará al proveedor ya suspendido"
docker exec motor-reglas-partner python scripts/enviar_trabajo.py \
  --partner-id "$PARTNER" --categoria PLOMERIA --ciudad Bogota
esperar

hr "saga log — se espera COMPENSADA y filas rol=COMPENSACION"
psql_trabajos -c "SELECT saga_id, estado, proveedor_id, motivo FROM saga_asignacion ORDER BY iniciada_en DESC LIMIT 3;"
psql_trabajos -c "SELECT saga_id, secuencia, tipo_mensaje, rol, resultado, payload->>'motivo' AS motivo FROM saga_paso WHERE rol='COMPENSACION' ORDER BY ocurrido_en;"
curl -sS "$ORQ/sagas?estado=COMPENSADA"
echo

hr "SQL tutor (timeline completa)"
psql_trabajos < scripts/consulta_saga.sql

echo
echo "Listo. Vuelve a inspeccionar con:"
echo "  docker exec -i db-trabajos psql -U trabajos -d trabajos < scripts/consulta_saga.sql"
echo "  curl -sS $ORQ/sagas"
