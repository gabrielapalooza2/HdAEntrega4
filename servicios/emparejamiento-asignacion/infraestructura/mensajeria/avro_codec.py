from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from pulsar.schema import AvroSchema, Record

from infraestructura.schema.v1.eventos import (
    EventoAsignacionConfirmadaPorHabilitacion,
    EventoAsignacionRechazadaPorHabilitacion,
    EventoEstadoDeHabilitacionCambiado,
    EventoReglaDePartnerActualizada,
    EventoTrabajoAsignado,
    EventoTrabajoCreado,
    EventoTrabajoRechazado,
)

CLASES_POR_TIPO = {
    "ReglaDePartnerActualizada": EventoReglaDePartnerActualizada,
    "EstadoDeHabilitacionCambiado": EventoEstadoDeHabilitacionCambiado,
    "TrabajoCreado": EventoTrabajoCreado,
    "TrabajoRechazado": EventoTrabajoRechazado,
    "TrabajoAsignado": EventoTrabajoAsignado,
    "AsignacionRechazadaPorHabilitacion": EventoAsignacionRechazadaPorHabilitacion,
    "AsignacionConfirmadaPorHabilitacion": EventoAsignacionConfirmadaPorHabilitacion,
}


def cargar_avsc(contratos_dir: Path, topico: str, nombre: str) -> dict:
    candidatos = [
        contratos_dir / "esquemas" / topico / f"{nombre}.avsc",
        contratos_dir / topico / f"{nombre}.avsc",
    ]
    for ruta in candidatos:
        if ruta.is_file():
            return json.loads(ruta.read_text(encoding="utf-8"))
    raise FileNotFoundError(
        "Contrato Avro no encontrado: " + " | ".join(str(c) for c in candidatos)
    )


def schema_pulsar(avsc: dict) -> AvroSchema:
    return AvroSchema(None, schema_definition=avsc)


def schema_record(tipo: str) -> AvroSchema:
    clase = CLASES_POR_TIPO[tipo]
    return AvroSchema(clase)


def record_to_plain(obj: Any) -> Any:
    if obj is None or isinstance(obj, (str, int, float, bool, bytes)):
        return obj
    if isinstance(obj, dict):
        return {k: record_to_plain(v) for k, v in obj.items() if not str(k).startswith("_")}
    if isinstance(obj, (list, tuple)):
        return [record_to_plain(x) for x in obj]
    if isinstance(obj, Record) or hasattr(obj, "__dict__"):
        d = getattr(obj, "__dict__", None)
        if isinstance(d, dict) and d:
            return {k: record_to_plain(v) for k, v in d.items() if not str(k).startswith("_")}
    return obj


def encode_avro(avsc: dict, record: dict) -> bytes:
    return AvroSchema(None, schema_definition=avsc).encode(record_to_plain(record))


def decode_avro(avsc: dict, data: bytes) -> dict:
    obj = AvroSchema(None, schema_definition=avsc).decode(data)
    return record_to_plain(obj)


def encode_tipo(tipo: str, record: dict) -> bytes:
    return schema_record(tipo).encode(record_to_plain(record))


def decode_tipo(tipo: str, data: bytes) -> dict:
    return record_to_plain(schema_record(tipo).decode(data))


def decode_evt_trabajos(data: bytes, avscs: dict[str, dict]) -> Optional[dict]:
    """Tópico multi-tipo. Prueba cada .avsc oficial y filtra por type."""
    return decode_multi_tipo(data, avscs)


def decode_multi_tipo(data: bytes, avscs: dict[str, dict]) -> Optional[dict]:
    for tipo, avsc in avscs.items():
        try:
            rec = decode_avro(avsc, data)
        except Exception:
            continue
        if rec.get("type") == tipo:
            return rec
    return None
