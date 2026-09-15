#!/usr/bin/env bash
# ESCENARIO 6 - MODIFICABILIDAD
# "Incorporar el partner 31 sin agregar condicionales dentro de Orquestacion de trabajos"
#
# LA DEMO TIENE DOS FASES Y LAS DOS SON NECESARIAS.
#
#   FASE 1 - administrativa: se registra el partner. Ocurre una vez, la dispara el
#            area comercial, y NO crea ningun trabajo.
#   FASE 2 - operativa: llega un trabajo DE ESE partner y se resuelve con SU regla.
#
# Sin la fase 2 no se demuestra nada: insertar una fila en una base de datos no
# prueba modificabilidad. Lo que la prueba es que el trabajo del partner nuevo
# obtiene su SLA y su red homologada SIN QUE NADIE HAYA DESPLEGADO DOMINIO.
set -euo pipefail
API="${API:-http://localhost:5002}"

hr() { printf '\n%s\n' "------------------------------------------------------------"; }

hr
echo "ESTADO INICIAL - imagenes en ejecucion (se compara al final)"
docker ps --format '{{.Names}}\t{{.Image}}' | sort | tee /tmp/imagenes_antes.txt

hr
echo "FASE 1 (administrativa) - registrar el partner 31"
echo "   Acto del area comercial. Frecuencia: ~30 veces en la historia de la empresa."
RESP=$(curl -sS -X POST "$API/partners" -H 'Content-Type: application/json' -d '{
  "nombre": "Aseguradora Andina",
  "tipo_partner": "ASEGURADORA",
  "convenio_numero": "CONV-2026-031",
  "vigencia_desde": "2026-01-01T00:00:00Z",
  "porcentaje_comision": 12.5,
  "moneda_tarifa": "COP",
  "regla": {
    "cobertura_contratada": ["PLOMERIA", "ELECTRICIDAD"],
    "sla_minutos": 120,
    "monto_maximo_sin_aprobacion": {"monto": 50000000, "moneda": "COP"},
    "pasos_de_aprobacion": ["ANALISTA_SINIESTROS"],
    "red_homologada": ["prov-001", "prov-002"]
  }
}')
echo "$RESP"
PARTNER_ID=$(echo "$RESP" | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')

echo
echo "   >> NO se creo ningun trabajo. Solo se configuro con quien trabajamos."

hr
echo "   La regla quedo como DATO en la base de datos:"
docker exec db-partners psql -U partners -d partners -t -c \
  "SELECT nombre, regla_version, sla_minutos, cobertura, red_homologada FROM partners WHERE id='$PARTNER_ID';" \
  2>/dev/null || curl -sS "$API/partners/$PARTNER_ID" | python3 -m json.tool

hr
echo "   Y viajo al bus con CARGA DE ESTADO (la regla completa, no un aviso):"
docker exec broker bin/pulsar-client consume \
  persistent://hda/poc/evt.partners -s demo-esc6-$RANDOM -p Earliest -n 1 2>/dev/null | tail -12

hr
echo "FASE 2 (operativa) - llega un trabajo DEL partner 31"
echo "   Actor distinto, frecuencia distinta: 12.000 al dia. Es lo que de verdad"
echo "   prueba el escenario."
echo
if ! docker ps --format '{{.Names}}' | grep -q orquestacion-trabajos; then
  echo "   [OMITIDA] Orquestacion de trabajos no esta corriendo."
  echo "   Esta fase la ejecuta el equipo cuando los 4 servicios esten arriba."
  echo "   Comando:"
  echo "     python scripts/enviar_trabajo.py --partner-id $PARTNER_ID --categoria PLOMERIA"
  echo
  echo "   Lo que debe observarse:"
  echo "     - el TrabajoCreado sale con slaMinutos=120, tomado de la regla del partner 31"
  echo "     - Emparejamiento solo considera prov-001 y prov-002 (su red homologada)"
  echo "     - un trabajo de categoria CARPINTERIA del partner 31 se RECHAZA:"
  echo "       esta fuera de su cobertura contratada, y eso lo decide un dato, no un if"
else
  python3 scripts/enviar_trabajo.py --partner-id "$PARTNER_ID" --categoria PLOMERIA
  sleep 3
  echo "   Eventos resultantes:"
  docker exec broker bin/pulsar-client consume \
    persistent://hda/poc/evt.trabajos -s demo-esc6-t-$RANDOM -p Earliest -n 2 2>/dev/null | tail -20
fi

hr
echo "MEDIDA 1 - cero condicionales por partner en el codigo"
COINCIDENCIAS=$(grep -rnE --include='*.py' \
  '(partner_id|partnerId|mercado_id|mercadoId)[[:space:]]*==[[:space:]]*["'"'"'0-9]' \
  src/motor_reglas/modulos/*/dominio/ src/motor_reglas/modulos/*/aplicacion/ 2>/dev/null \
  | grep -vE ':[[:space:]]*#' | wc -l)
echo "   condicionales por partner en dominio/ y aplicacion/: $COINCIDENCIAS"
[ "$COINCIDENCIAS" -eq 0 ] && echo "   >> CUMPLE" || echo "   >> NO CUMPLE"

hr
echo "MEDIDA 2 - cero componentes de dominio redesplegados"
docker ps --format '{{.Names}}\t{{.Image}}' | sort > /tmp/imagenes_despues.txt
if diff -q /tmp/imagenes_antes.txt /tmp/imagenes_despues.txt >/dev/null; then
  echo "   >> CUMPLE: ninguna imagen cambio. El partner entro sin desplegar nada."
else
  echo "   >> NO CUMPLE:"; diff /tmp/imagenes_antes.txt /tmp/imagenes_despues.txt || true
fi
hr
