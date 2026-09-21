#!/usr/bin/env bash
# ESCENARIO DE DISPONIBILIDAD - operación degradada.
#
# Qué demuestra: los consumidores siguen operando con Motor reglas partner caído,
# porque el evento lleva CARGA DE ESTADO y ellos guardan una proyección local.
# Si el evento fuera delgado, tendrían que venir a preguntar y esto fallaría.
set -euo pipefail

echo "== 1. Última regla conocida de cada partner, leída del tópico COMPACTADO =="
echo "   (esto es lo que un consumidor reconstruye al arrancar en frío)"
docker exec broker bin/pulsar-client consume \
  persistent://hda/poc/evt.partners -s chequeo-$RANDOM -p Earliest -n 10 2>/dev/null | grep -c "content" || true

echo
echo "== 2. Apagando Motor reglas partner =="
docker stop motor-reglas-partner
docker ps --format '{{.Names}}' | grep -q motor-reglas-partner && echo "sigue arriba" || echo "   caído"

echo
echo "== 3. El tópico conserva el estado: un consumidor nuevo lo reconstruye igual =="
docker exec broker bin/pulsar-client consume \
  persistent://hda/poc/evt.partners -s consumidor-frio-$RANDOM -p Earliest -n 5 2>/dev/null | tail -15

echo
echo "   >> Aquí los servicios consumidores (Orquestación, Emparejamiento) deben"
echo "      seguir resolviendo trabajos. Ejecuten su carga ahora."
echo
read -r -p "Presione ENTER para volver a levantar el servicio..."
docker start motor-reglas-partner
echo "== 4. Servicio restablecido. El outbox drena lo pendiente automáticamente. =="
