#!/usr/bin/env bash
# Crea tenant, namespace y tópicos de la prueba de concepto.
# Ejecutar UNA vez, después de que el broker esté sano y ANTES de levantar los servicios.
set -euo pipefail

PA="docker exec broker bin/pulsar-admin"

echo "==> tenant y namespace"
$PA tenants create hda 2>/dev/null || echo "    tenant hda ya existe"
$PA namespaces create hda/poc 2>/dev/null || echo "    namespace hda/poc ya existe"

echo "==> retención infinita"
# Sin esto, un mensaje confirmado por todas las suscripciones se borra, y un
# servicio nuevo no podría reconstruir su proyección leyendo el tópico desde el inicio.
$PA namespaces set-retention hda/poc --size -1 --time -1

echo "==> política de compatibilidad de esquemas"
# BACKWARD: un consumidor con el esquema nuevo puede leer mensajes escritos con el
# viejo. El broker RECHAZA a cualquier productor que intente registrar un esquema
# incompatible, así que el contrato lo hace cumplir la infraestructura y no la
# disciplina del equipo.
$PA namespaces set-schema-compatibility-strategy hda/poc --compatibility BACKWARD
$PA namespaces set-is-allow-auto-update-schema hda/poc --enable

echo "==> tópicos de comando y de evento delgado (particionados para escalar)"
$PA topics create-partitioned-topic persistent://hda/poc/comandos-partner  -p 3 2>/dev/null || true
$PA topics create-partitioned-topic persistent://hda/poc/comandos-trabajos -p 3 2>/dev/null || true
$PA topics create-partitioned-topic persistent://hda/poc/eventos-trabajos  -p 3 2>/dev/null || true

echo "==> tópicos de CARGA DE ESTADO (compactados, NO particionados)"
# No se particionan: la compactación por clave es por partición, y queremos una
# vista única y completa del último estado de cada partner y cada proveedor.
$PA topics create persistent://hda/poc/eventos-partner     2>/dev/null || true
$PA topics create persistent://hda/poc/eventos-proveedores 2>/dev/null || true
$PA namespaces set-compaction-threshold hda/poc --threshold 10M

echo "==> listado"
$PA topics list hda/poc
echo "LISTO"
