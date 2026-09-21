#!/usr/bin/env bash
# DEMOSTRACION DEL ESCENARIO DE MODIFICABILIDAD — flujo completo, dos fases.
#
# Se corre desde la RAIZ del monorepo, con los cuatro servicios arriba:
#   ./servicios/motor-reglas-partner/scripts/demo_flujo_completo.sh
#
# Que demuestra, en una sola pasada:
#   FASE 1  se registra el partner 31   -> acto administrativo, NO crea ningun trabajo
#   FASE 2  llegan DOS trabajos de ese partner:
#             - PLOMERIA    -> ACEPTADO, con el SLA de 120 min que trae SU regla
#             - CARPINTERIA -> RECHAZADO, porque no esta en SU cobertura contratada
#
# El contraste es el argumento entero: mismo codigo, dos resultados distintos,
# y la diferencia esta en una FILA de la base de datos, no en un condicional.
set -euo pipefail
MOTOR="${MOTOR:-http://localhost:5002}"
PAUSA="${PAUSA:-6}"

hr(){ printf '\n\033[1m%s\033[0m\n%s\n' "$1" "────────────────────────────────────────────────────────────"; }
pausa(){ printf '\033[2m(esperando %ss a que el evento se propague…)\033[0m\n' "$PAUSA"; sleep "$PAUSA"; }

hr "ESTADO INICIAL — imagenes en ejecucion"
docker ps --format '{{.Names}}\t{{.Image}}' | sort | tee /tmp/antes.txt

hr "FASE 1 (administrativa) — registrar el partner 31"
echo "Acto del area comercial. NO crea ningun trabajo."
RESP=$(curl -sS -X POST "$MOTOR/partners" -H 'Content-Type: application/json' -d '{
  "nombre": "Aseguradora Andina",
  "tipo_partner": "ASEGURADORA",
  "convenio_numero": "CONV-2026-031",
  "vigencia_desde": "2026-01-01T00:00:00Z",
  "porcentaje_comision": 12.5,
  "regla": {
    "cobertura_contratada": ["PLOMERIA", "ELECTRICIDAD"],
    "sla_minutos": 120,
    "monto_maximo_sin_aprobacion": {"monto": 50000000, "moneda": "COP"},
    "pasos_de_aprobacion": ["ANALISTA_SINIESTROS"],
    "red_homologada": ["prov-001", "prov-002"]
  }}')
echo "$RESP"
PARTNER=$(echo "$RESP" | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')
echo "partner_id = $PARTNER"

hr "La regla quedo como DATO en la base de datos de ESTE servicio"
docker exec db-partners psql -U partners -d partners -c \
  "SELECT nombre, regla_version, sla_minutos, cobertura, red_homologada FROM partners WHERE id='$PARTNER';"

hr "El outbox la encolo dentro de la MISMA transaccion"
docker exec db-partners psql -U partners -d partners -c \
  "SELECT tipo, clave, publicado FROM outbox ORDER BY fecha_creacion DESC LIMIT 3;"
pausa

hr "Y viajo a evt.partners con CARGA DE ESTADO (la regla completa)"
docker exec broker bin/pulsar-client consume \
  persistent://hda/poc/evt.partners -s "demo-$RANDOM" -p Earliest -n 1 2>/dev/null | tail -14

hr "FASE 2 (operativa) — trabajo de PLOMERIA, que SI esta en su cobertura"
docker exec motor-reglas-partner python scripts/enviar_trabajo.py \
  --partner-id "$PARTNER" --categoria PLOMERIA
pausa

hr "FASE 2b — trabajo de CARPINTERIA, que NO esta en su cobertura"
docker exec motor-reglas-partner python scripts/enviar_trabajo.py \
  --partner-id "$PARTNER" --categoria CARPINTERIA
pausa

hr "Lo que salio a evt.trabajos"
echo "Se esperan DOS eventos: un TrabajoCreado con sla_minutos=120 y un TrabajoRechazado."
docker exec broker bin/pulsar-client consume \
  persistent://hda/poc/evt.trabajos -s "demo-t-$RANDOM" -p Earliest -n 4 2>/dev/null | tail -30

hr "MEDIDA 1 — cero condicionales por partner en el codigo"
COINC=$(grep -rnE --include='*.py' \
  '(partner_id|partnerId|mercado_id|mercadoId)[[:space:]]*==[[:space:]]*["'"'"'0-9]' \
  "$(dirname "$0")/../src/motor_reglas/modulos/"*/dominio/ \
  "$(dirname "$0")/../src/motor_reglas/modulos/"*/aplicacion/ 2>/dev/null \
  | grep -vE ':[[:space:]]*#' | wc -l)
echo "condicionales por partner en dominio/ y aplicacion/: $COINC"
[ "$COINC" -eq 0 ] && echo ">> CUMPLE" || echo ">> NO CUMPLE"

hr "MEDIDA 2 — cero componentes redesplegados"
docker ps --format '{{.Names}}\t{{.Image}}' | sort > /tmp/despues.txt
if diff -q /tmp/antes.txt /tmp/despues.txt >/dev/null; then
  echo ">> CUMPLE: ninguna imagen cambio. El partner entro sin construir ni desplegar nada."
else
  diff /tmp/antes.txt /tmp/despues.txt || true
fi
echo
