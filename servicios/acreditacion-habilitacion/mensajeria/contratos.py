"""Toda la traduccion entre el dominio de Acreditacion y el contrato Avro
del grupo vive en este unico modulo -- misma convencion que uso Sofia en
Orquestacion de Trabajos.

Contiene:
  - Carga de los .avsc desde CONTRATOS_DIR (carpeta compartida del repo,
    montada por volumen en el contenedor, NO copiada ni duplicada aqui).
  - Codificacion/decodificacion Avro binaria (fastavro).
  - Construccion del sobre CloudEvents (id, time, specversion, type,
    correlation_id, data{...}) a partir de los eventos de dominio.
  - El "type" se envia TAMBIEN como propiedad del mensaje de Pulsar (no
    solo dentro del payload binario), porque evt.trabajos lleva varios
    tipos de record en el mismo topico y un consumidor necesita saber que
    .avsc usar ANTES de decodificar bytes Avro puros.
"""
from __future__ import annotations

import io
import json
import os
import uuid
from datetime import datetime, timezone

import fastavro

from dominio.eventos import (
    AsignacionConfirmadaPorHabilitacion,
    AsignacionRechazadaPorHabilitacion,
    EstadoDeHabilitacionCambiado,
)

SERVICE_NAME = os.getenv("SERVICE_NAME", "acreditacion-habilitacion")
CONTRATOS_DIR = os.getenv("CONTRATOS_DIR", "/app/contratos")

# Mapa: nombre logico de topico -> ruta relativa dentro de CONTRATOS_DIR.
# Ajustar estos nombres de archivo si difieren de como el equipo organizo
# la carpeta contratos/ compartida (confirmar con quien la armo).
_RUTAS_SCHEMA = {
    "AcreditarProveedor": "esquemas/cmd.proveedores/AcreditarProveedor.avsc",
    "SuspenderProveedor": "esquemas/cmd.proveedores/SuspenderProveedor.avsc",
    "TrabajoAsignado": "esquemas/evt.trabajos/TrabajoAsignado.avsc",
    "AsignacionAceptadaPorReglaPartner": "esquemas/evt.asignaciones/AsignacionAceptadaPorReglaPartner.avsc",
    "EstadoDeHabilitacionCambiado": "esquemas/evt.proveedores/EstadoDeHabilitacionCambiado.avsc",
    "AsignacionRechazadaPorHabilitacion": "esquemas/evt.asignaciones/AsignacionRechazadaPorHabilitacion.avsc",
    "AsignacionConfirmadaPorHabilitacion": "esquemas/evt.asignaciones/AsignacionConfirmadaPorHabilitacion.avsc",
}

_cache_schemas: dict[str, dict] = {}


def _cargar_schema(tipo: str) -> dict:
    if tipo not in _cache_schemas:
        ruta = os.path.join(CONTRATOS_DIR, _RUTAS_SCHEMA[tipo])
        with open(ruta, "r", encoding="utf-8") as f:
            crudo = json.load(f)
        _cache_schemas[tipo] = fastavro.parse_schema(crudo)
    return _cache_schemas[tipo]


def _epoch_millis(dt: datetime | None) -> int | None:
    if dt is None:
        return None
    return int(dt.timestamp() * 1000)


def _epoch_millis_a_datetime(valor: int | None) -> datetime | None:
    if valor is None:
        return None
    return datetime.fromtimestamp(valor / 1000, tz=timezone.utc)


# ------------------------------------------------ codificar (publicar)

def codificar_evento(evento, correlation_id: str) -> tuple[bytes, dict]:
    """Devuelve (payload_avro_binario, propiedades_pulsar) para un evento
    de integracion de este servicio."""
    if isinstance(evento, EstadoDeHabilitacionCambiado):
        tipo = "EstadoDeHabilitacionCambiado"
        data = {
            "proveedor_id": evento.proveedor_id, "nombre": evento.nombre, "estado": evento.estado,
            "categorias": evento.categorias, "ciudades": evento.ciudades, "motivo": evento.motivo,
            "vigente_hasta": _epoch_millis(evento.vigente_hasta),
        }
    elif isinstance(evento, AsignacionRechazadaPorHabilitacion):
        tipo = "AsignacionRechazadaPorHabilitacion"
        data = {
            "trabajo_id": evento.trabajo_id, "asignacion_id": evento.asignacion_id,
            "proveedor_id": evento.proveedor_id, "estado_real": evento.estado_real,
            "motivo": evento.motivo, "verificado_en": _epoch_millis(evento.verificado_en),
        }
    elif isinstance(evento, AsignacionConfirmadaPorHabilitacion):
        tipo = "AsignacionConfirmadaPorHabilitacion"
        data = {
            "trabajo_id": evento.trabajo_id, "asignacion_id": evento.asignacion_id,
            "proveedor_id": evento.proveedor_id, "estado_real": evento.estado_real,
            "verificado_en": _epoch_millis(evento.verificado_en),
        }
    else:
        raise NotImplementedError(f"contratos.py no sabe codificar {type(evento).__name__}")

    sobre = {
        "id": str(uuid.uuid4()),
        "time": _epoch_millis(evento.fecha_evento),
        "ingestion": _epoch_millis(datetime.now(timezone.utc)),
        "specversion": "1.0",
        "type": tipo,
        "datacontenttype": "application/json",
        "service_name": SERVICE_NAME,
        "correlation_id": correlation_id,
        "data": data,
    }

    payload = io.BytesIO()
    fastavro.schemaless_writer(payload, _cargar_schema(tipo), sobre)

    propiedades = {"type": tipo, "correlation_id": correlation_id, "specversion": "1.0"}
    return payload.getvalue(), propiedades


# ------------------------------------------------ decodificar (consumir)

# Tipos que este servicio sabe decodificar, agrupados por lo que consume.
TIPOS_CMD_PROVEEDORES = {"AcreditarProveedor", "SuspenderProveedor"}
TIPOS_EVT_ASIGNACIONES = {"AsignacionAceptadaPorReglaPartner"}

_ESQUEMA_SOBRE = fastavro.parse_schema({
    "type": "record",
    "name": "SobreComun",
    "fields": [
        {"name": "id", "type": ["null", "string"]},
        {"name": "time", "type": ["null", "long"]},
        {"name": "ingestion", "type": ["null", "long"]},
        {"name": "specversion", "type": ["null", "string"]},
        {"name": "type", "type": ["null", "string"]},
        {"name": "datacontenttype", "type": ["null", "string"]},
        {"name": "service_name", "type": ["null", "string"]},
        {"name": "correlation_id", "type": ["null", "string"]},
    ],
})


def tipo_del_sobre(payload: bytes) -> str | None:
    """Lee el discriminador CloudEvents sin conocer el esquema del payload.

    Emparejamiento publica TrabajoAsignado como bytes Avro y a veces sin
    propiedad Pulsar `type`. Motor publica AsignacionAceptadaPorReglaPartner
    igual. Sin este peek el consumidor ackea y silencia el paso.
    """
    if not payload:
        return None
    if payload[:1] == b"{":
        try:
            return json.loads(payload.decode("utf-8")).get("type")
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            return None
    try:
        cabecera = fastavro.schemaless_reader(io.BytesIO(payload), _ESQUEMA_SOBRE)
    except Exception:
        return None
    return (cabecera or {}).get("type")


def decodificar(tipo: str, payload: bytes) -> dict:
    schema = _cargar_schema(tipo)
    buffer = io.BytesIO(payload)
    return fastavro.schemaless_reader(buffer, schema)


def epoch_millis_a_datetime(valor: int | None) -> datetime | None:
    return _epoch_millis_a_datetime(valor)
