#!/usr/bin/env bash
# Conduce la demo escena por escena. Muestra el comando, espera Enter, lo corre.
#
# Existe para no tipear ni pegar nada durante la grabacion: uno se concentra en
# hablar y solo aprieta Enter. Ademas captura solo el trabajo_id, que si no hay
# que copiarlo a mano entre escenas y es donde mas facil se traba una toma.
#
#   ./scripts/demo.sh        todas las escenas, en orden
#   ./scripts/demo.sh 4      arranca desde la escena 4
#   ./scripts/demo.sh 4 6    de la 4 a la 6
set -uo pipefail
cd "$(dirname "$0")/.."

: "${PULSAR_URL:=pulsar://localhost:6650}"
: "${PULSAR_LISTENER:=external}"
export PULSAR_URL PULSAR_LISTENER
PY=./.venv/bin/python
PSQL="docker exec db-trabajos psql -U trabajos -d trabajos"

n=$'\033[0m'; b=$'\033[1m'; cy=$'\033[36m'; am=$'\033[33m'; ve=$'\033[32m'

TRABAJO_ID=""

escena() {
  echo
  echo "${cy}${b}══════════════════════════════════════════════════════════════${n}"
  echo "${cy}${b}  ESCENA $1 · $2${n}"
  echo "${cy}${b}══════════════════════════════════════════════════════════════${n}"
}

# Espera un Enter. Usa /dev/tty para que funcione aunque la salida del script
# este redirigida a un archivo; si no hay terminal -por ejemplo en CI- sigue de
# largo en vez de reventar.
pausa() {
  if [ -e /dev/tty ] && [ -r /dev/tty ]; then
    read -r -s -p "" _ </dev/tty 2>/dev/null || true
  fi
}

# Muestra el comando y espera. Al apretar Enter lo ejecuta.
correr() {
  echo
  echo "${am}\$ $1${n}"
  pausa
  echo
  eval "$1"
  echo
  echo "${ve}[Enter para seguir]${n}"
  pausa
}

# Toma el trabajo_id mas reciente, para no copiarlo a mano entre escenas.
capturar_trabajo() {
  TRABAJO_ID=$($PSQL -tAc "SELECT trabajo_id FROM proyeccion_trabajo ORDER BY actualizado_en DESC LIMIT 1" 2>/dev/null | tr -d ' \r')
  echo "${ve}   trabajo_id capturado: ${b}$TRABAJO_ID${n}"
}

esperar_trabajo() {
  for _ in $(seq 1 60); do
    c=$($PSQL -tAc "SELECT count(*) FROM proyeccion_trabajo" 2>/dev/null | tr -d ' \r')
    [ "${c:-0}" -ge "${1:-1}" ] && return 0
    sleep 0.3
  done
}

desde=${1:-0}; hasta=${2:-11}
hacer() { [ "$1" -ge "$desde" ] && [ "$1" -le "$hasta" ]; }

# ─────────────────────────────────────────────────────────────── escenas ────

if hacer 0; then
escena 0 "APERTURA · la arquitectura"
correr "find src/orquestacion -maxdepth 2 -type d -not -path '*__pycache__*' | sort"
fi

if hacer 1; then
escena 1 "EL CLUSTER"
correr "docker compose ps"
correr "docker exec broker bin/pulsar-admin namespaces get-retention hda/poc"
correr "docker exec broker bin/pulsar-admin topics list hda/poc | sort"
fi

if hacer 2; then
escena 2 "LA CAPA ANTICORRUPCION"
correr "grep -n 'zona\\|ciudad' src/orquestacion/mensajeria/contratos.py | head -12"
correr "grep -rn 'cobertura_contratada\\|sla_vence_en\\|excluir_proveedores' src/orquestacion/dominio/ || echo '  el dominio NO conoce los nombres de afuera'"
correr "grep -rn '^import\\|^from' src/orquestacion/dominio/*.py | grep -E 'psycopg|pulsar|flask' || echo '  cero dependencias de infraestructura'"
fi

if hacer 3; then
escena 3 "LAS REGLAS COMO DATO"
correr "$PSQL -c \"SELECT partner_id, regla_version, sla_minutos, activo, categorias_cubiertas FROM proyeccion_regla_partner ORDER BY partner_id;\""
fi

if hacer 4; then
escena 4 "EL CONGELAMIENTO DEL SLA  ***"
correr "$PY scripts/publicar.py CrearTrabajo --partner-id SEGUROS_ALFA --categoria PLOMERIA --zona BOGOTA"
esperar_trabajo 1
capturar_trabajo
correr "$PSQL -c \"SELECT secuencia, tipo, payload->>'sla_minutos' sla, payload->>'regla_version' regla, payload->>'vence_en' vence FROM eventos_trabajo ORDER BY ocurrido_en DESC LIMIT 3;\""
correr "grep -rni 'UPDATE eventos_trabajo\\|DELETE FROM eventos_trabajo' src/ || echo '  NINGUNO'"
fi

if hacer 5; then
escena 5 "LOS RECHAZOS"
correr "$PY scripts/publicar.py CrearTrabajo --partner-id SEGUROS_BETA --categoria PLOMERIA --zona BOGOTA | grep -E '^  ->'"
correr "$PY scripts/publicar.py CrearTrabajo --partner-id PARTNER_DORMIDO --categoria PLOMERIA --zona BOGOTA | grep -E '^  ->'"
fi

if hacer 6; then
escena 6 "IDEMPOTENCIA"
correr "$PY scripts/publicar.py CrearTrabajo --partner-id SEGUROS_ALFA --categoria ELECTRICIDAD --duplicar 3 | grep -E '^  ->'"
fi

if hacer 7; then
escena 7 "CQRS Y EL REZAGO VISIBLE"
[ -z "$TRABAJO_ID" ] && capturar_trabajo
correr "curl -sD- localhost:5001/trabajos/$TRABAJO_ID/estado"
fi

if hacer 8; then
escena 8 "EL UNICO PUNTO ORQUESTADO  ***"
[ -z "$TRABAJO_ID" ] && capturar_trabajo
correr "for P in PROV_1 PROV_2 PROV_3; do $PY scripts/publicar.py AsignacionRechazadaPorHabilitacion --trabajo-id $TRABAJO_ID --proveedor-id \$P | tail -1; sleep 1; done"
correr "$PSQL -c \"SELECT secuencia, tipo, payload->>'proveedor_id' proveedor, payload->>'motivo' motivo FROM eventos_trabajo WHERE trabajo_id='$TRABAJO_ID' ORDER BY secuencia;\""
correr "$PY scripts/escuchar.py cmd.emparejamiento --desde-el-inicio --maximo 2 --espera-segundos 8"
fi

if hacer 9; then
escena 9 "EL BARRIDO DE SLA  (tarda ~90 s)"
correr "$PY scripts/publicar.py CrearTrabajo --partner-id ASISTENCIA_GAMMA --categoria PLOMERIA --zona BOGOTA | grep -E '^  ->'"
echo "${am}   Habla mientras vence. Enter cuando quieras consultar.${n}"
correr "$PSQL -c \"SELECT left(trabajo_id::text,8) id, estado, partner_id, sla_minutos FROM proyeccion_trabajo WHERE partner_id='ASISTENCIA_GAMMA';\""
fi

if hacer 10; then
escena 10 "PUNTA A PUNTA  ***  (mira las tres terminales)"
correr "$PY scripts/publicar.py CrearTrabajo --partner-id SEGUROS_ALFA --categoria PLOMERIA --zona BOGOTA | grep -E '^  ->'"
fi

if hacer 11; then
escena 11 "CIERRE"
correr "head -40 DECISIONES.md"
fi

echo
echo "${ve}${b}  Fin. Para otra toma:  ./scripts/reiniciar_demo.sh${n}"
echo
