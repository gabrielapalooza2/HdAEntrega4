import io
import json
import logging
import os
from pathlib import Path

from fastavro import parse_schema, schemaless_reader, schemaless_writer

log = logging.getLogger("bff.avro")

CONTRATOS_DIR = Path(os.getenv("CONTRATOS_DIR", "/app/contratos"))

# Que carpeta guarda cada tipo. Es el mismo mapa que usan los demas servicios.
CARPETA_DE_TIPO = {
    # comandos que el BFF publica
    "RegistrarPartner": "cmd.partners",
    "ActualizarReglaDePartner": "cmd.partners",
    "AcreditarProveedor": "cmd.proveedores",
    "SuspenderProveedor": "cmd.proveedores",
    "CrearTrabajo": "cmd.trabajos",
    # eventos que el BFF consume
    "ReglaDePartnerActualizada": "evt.partners",
    "EstadoDeHabilitacionCambiado": "evt.proveedores",
    "TrabajoCreado": "evt.trabajos",
    "TrabajoRechazado": "evt.trabajos",
    "TrabajoAsignado": "evt.trabajos",
    "AsignacionAceptadaPorReglaPartner": "evt.asignaciones",
    "AsignacionRechazadaPorReglaPartner": "evt.asignaciones",
    "AsignacionConfirmadaPorHabilitacion": "evt.asignaciones",
    "AsignacionRechazadaPorHabilitacion": "evt.asignaciones",
}

_cache: dict[str, dict] = {}

ESQUEMA_SOBRE = parse_schema({
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


def ruta_de(tipo: str) -> Path:
    carpeta = CARPETA_DE_TIPO.get(tipo)
    if carpeta is None:
        raise KeyError(f"tipo de mensaje desconocido para el BFF: {tipo}")
    return CONTRATOS_DIR / "esquemas" / carpeta / f"{tipo}.avsc"


def cargar(tipo: str) -> dict:
    if tipo not in _cache:
        ruta = ruta_de(tipo)
        if not ruta.is_file():
            raise FileNotFoundError(
                f"contrato Avro no encontrado: {ruta}. Revisa CONTRATOS_DIR."
            )
        _cache[tipo] = parse_schema(json.loads(ruta.read_text(encoding="utf-8")))
    return _cache[tipo]


def _campos_del_payload(tipo: str) -> list[str]:
    esquema = cargar(tipo)
    campo_data = next(c for c in esquema["fields"] if c["name"] == "data")
    registro = next(t for t in campo_data["type"] if isinstance(t, dict))
    return [c["name"] for c in registro["fields"]]


def completar(tipo: str, payload: dict) -> dict:
    """Rellena con None los campos del contrato que el BFF no usa.

    Avro exige el registro COMPLETO al codificar. Dejar los ajenos explicitos en
    None documenta que sabemos que existen y que decidimos no llenarlos.
    """
    return {campo: payload.get(campo) for campo in _campos_del_payload(tipo)}


def codificar(sobre: dict) -> bytes:
    buf = io.BytesIO()
    schemaless_writer(buf, cargar(sobre["type"]), sobre)
    return buf.getvalue()


def decodificar(crudo: bytes) -> dict | None:
    """Bytes del cable -> dict completo, o None si el tipo no nos interesa.

    Devolver None NO es un error: los topicos son por agregado, no por tipo de
    mensaje, asi que recibir tipos que el BFF no modela es lo esperado.
    """
    if not crudo:
        return None


    if crudo[:1] == b"{":
        try:
            datos = json.loads(crudo.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return datos if isinstance(datos, dict) and datos.get("type") in CARPETA_DE_TIPO else None

    try:
        cabecera = schemaless_reader(io.BytesIO(crudo), ESQUEMA_SOBRE)
    except Exception:                                      # noqa: BLE001
        return None

    tipo = (cabecera or {}).get("type")
    if tipo not in CARPETA_DE_TIPO:
        return None

    try:
        return schemaless_reader(io.BytesIO(crudo), cargar(tipo))
    except Exception:                                      # noqa: BLE001
        log.warning("sobre legible pero cuerpo no decodificable: %s", tipo)
        return None
