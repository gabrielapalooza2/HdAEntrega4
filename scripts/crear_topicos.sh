#!/usr/bin/env bash
# Crea tenant, namespace y los 12 tópicos del sistema. Se corre UNA vez,
# después de que el broker esté sano y ANTES de levantar los servicios.
set -euo pipefail
PA="docker exec broker bin/pulsar-admin"

echo "==> tenant y namespace"
$PA tenants create hda      2>/dev/null || echo "    hda ya existe"
$PA namespaces create hda/poc 2>/dev/null || echo "    hda/poc ya existe"

echo "==> retención infinita"
# Sin esto, un mensaje confirmado por todas las suscripciones se borra y un
# servicio nuevo no puede reconstruir su proyección leyendo desde el inicio.
$PA namespaces set-retention hda/poc --size -1 --time -1

echo "==> compatibilidad de esquemas BACKWARD"
# El broker RECHAZA a cualquier productor con un esquema incompatible.
# El contrato lo hace cumplir la infraestructura, no la disciplina del equipo.
$PA namespaces set-schema-compatibility-strategy hda/poc --compatibility BACKWARD
$PA namespaces set-is-allow-auto-update-schema hda/poc --enable

echo "==> comandos y eventos delgados (PARTICIONADOS, para escalar el consumo)"
$PA topics create-partitioned-topic persistent://hda/poc/cmd.trabajos       -p 3 2>/dev/null || true
$PA topics create-partitioned-topic persistent://hda/poc/cmd.emparejamiento -p 3 2>/dev/null || true
$PA topics create-partitioned-topic persistent://hda/poc/evt.trabajos       -p 3 2>/dev/null || true
$PA topics create-partitioned-topic persistent://hda/poc/evt.asignaciones   -p 3 2>/dev/null || true
$PA topics create-partitioned-topic persistent://hda/poc/cmd.partners       -p 1 2>/dev/null || true
$PA topics create-partitioned-topic persistent://hda/poc/cmd.proveedores    -p 1 2>/dev/null || true

echo "==> carga de estado (COMPACTADOS y SIN particionar)"
# La compactación conserva el último mensaje por clave DENTRO de cada partición.
# Con varias particiones, un consumidor en frío obtendría una vista parcial.
$PA topics create persistent://hda/poc/evt.partners     2>/dev/null || true
$PA topics create persistent://hda/poc/evt.proveedores  2>/dev/null || true
$PA namespaces set-compaction-threshold hda/poc --threshold 10M

echo "==> tópicos creados:"
$PA topics list hda/poc
