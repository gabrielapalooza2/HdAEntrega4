"""Avro de los hechos de saga que publica Motor (evt.asignaciones, multi-tipo).

evt.asignaciones ya lleva confirmacion/rechazo de habilitacion. Pulsar registra
un esquema por topico, asi que se publica BytesSchema + fastavro, igual que
Orquestacion y Acreditacion. El tópico compactado evt.partners sigue en
pulsar.schema.AvroSchema: ahi si hay un solo tipo.
"""
from __future__ import annotations

import io
import json
import os
import uuid
from pathlib import Path

import fastavro

from motor_reglas.seedwork.infraestructura import utils

TIPOS_SAGA = {
    "AsignacionAceptadaPorReglaPartner",
    "AsignacionRechazadaPorReglaPartner",
}

_cache: dict[str, dict] = {}


def contratos_dir() -> Path:
    env = os.getenv("CONTRATOS_DIR")
    if env:
        return Path(env)
    for padre in Path(__file__).resolve().parents:
        candidato = padre / "contratos"
        if (candidato / "esquemas").is_dir():
            return candidato
    return Path("/app/contratos")


def _schema(tipo: str) -> dict:
    if tipo not in _cache:
        ruta = contratos_dir() / "esquemas" / "evt.asignaciones" / f"{tipo}.avsc"
        _cache[tipo] = fastavro.parse_schema(
            json.loads(ruta.read_text(encoding="utf-8"))
        )
    return _cache[tipo]


def codificar_evento_saga(tipo: str, data: dict, correlation_id: str) -> bytes:
    sobre = {
        "id": str(uuid.uuid4()),
        "time": utils.time_millis(),
        "ingestion": utils.time_millis(),
        "specversion": "v1",
        "type": tipo,
        "datacontenttype": "AVRO",
        "service_name": utils.service_name(),
        "correlation_id": correlation_id,
        "data": data,
    }
    buf = io.BytesIO()
    fastavro.schemaless_writer(buf, _schema(tipo), sobre)
    return buf.getvalue()


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
    return fastavro.schemaless_reader(io.BytesIO(payload), _schema(tipo))
