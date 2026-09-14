"""Prueba de EVOLUCIÓN DE ESQUEMAS.

Es la evidencia ejecutable del requisito «Event Stream Versioning» del enunciado:
demuestra que un consumidor con el esquema nuevo puede leer mensajes escritos con
el esquema viejo (política BACKWARD), y que un cambio prohibido rompe.

Correr esta prueba en integración continua convierte la regla de compatibilidad
en algo que falla el build, y no en una recomendación del README.
"""
import copy
import io
import json

import pytest
from fastavro import parse_schema, schemaless_reader, schemaless_writer
from pulsar.schema import AvroSchema

from motor_reglas.modulos.partners.infraestructura.schema.v1.eventos import (
    EventoReglaDePartnerActualizada,
)

MENSAJE_V1 = {
    "id": "abc", "time": 1, "ingestion": 1, "specversion": "v1",
    "type": "ReglaDePartnerActualizada", "datacontenttype": "AVRO",
    "service_name": "motor-reglas-partner", "correlation_id": "corr-1",
    "data": {
        "partner_id": "p31", "convenio_id": "c1", "nombre": "Aseguradora Andina",
        "tipo_partner": "ASEGURADORA", "activo": True,
        "vigencia_desde": 1, "vigencia_hasta": 0, "version_regla": 1,
        "cobertura_contratada": ["PLOMERIA"], "sla_minutos": 120,
        "monto_maximo_sin_aprobacion": {"monto": 5000000, "moneda": "COP"},
        "pasos_de_aprobacion": ["ANALISTA"], "red_homologada": ["prov-001"],
        "porcentaje_comision": 12.5, "moneda_tarifa": "COP",
    },
}


def esquema_v1() -> dict:
    return json.loads(AvroSchema(EventoReglaDePartnerActualizada).schema_info().schema())


def _payload(esquema: dict) -> dict:
    campo = [f for f in esquema["fields"] if f["name"] == "data"][0]
    tipo = campo["type"]
    return tipo if isinstance(tipo, dict) else [x for x in tipo if isinstance(x, dict)][0]


def _escribir(esquema, registro) -> bytes:
    buf = io.BytesIO()
    schemaless_writer(buf, parse_schema(esquema), registro)
    return buf.getvalue()


def test_agregar_campo_opcional_es_compatible():
    """PERMITIDO: campo nuevo, opcional y con default."""
    v2 = copy.deepcopy(esquema_v1())
    _payload(v2)["fields"].append(
        {"name": "canal_preferido", "type": ["null", "string"], "default": None}
    )
    leido = schemaless_reader(
        io.BytesIO(_escribir(esquema_v1(), MENSAJE_V1)),
        parse_schema(esquema_v1()), parse_schema(v2),
    )
    assert leido["data"]["partner_id"] == "p31"
    assert leido["data"]["canal_preferido"] is None   # el default rellena el hueco


def test_agregar_campo_obligatorio_rompe():
    """PROHIBIDO: sin default, el consumidor nuevo no puede leer lo viejo."""
    v2 = copy.deepcopy(esquema_v1())
    _payload(v2)["fields"].append({"name": "canal_preferido", "type": "string"})
    with pytest.raises(Exception):
        schemaless_reader(
            io.BytesIO(_escribir(esquema_v1(), MENSAJE_V1)),
            parse_schema(esquema_v1()), parse_schema(v2),
        )


def test_renombrar_campo_rompe():
    """PROHIBIDO: renombrar es borrar y crear. Se hace con un tipo nuevo, no con
    una versión nueva del mismo."""
    v2 = copy.deepcopy(esquema_v1())
    for f in _payload(v2)["fields"]:
        if f["name"] == "sla_minutos":
            f["name"] = "sla_en_minutos"
    with pytest.raises(Exception):
        schemaless_reader(
            io.BytesIO(_escribir(esquema_v1(), MENSAJE_V1)),
            parse_schema(esquema_v1()), parse_schema(v2),
        )
