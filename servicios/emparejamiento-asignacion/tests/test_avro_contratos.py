from __future__ import annotations

from pathlib import Path

from infraestructura.mensajeria.avro_codec import decode_avro, encode_avro, cargar_avsc
from infraestructura.schema.v1.eventos import EventoTrabajoAsignado, TrabajoAsignadoPayload
from pulsar.schema import AvroSchema


CONTRATOS = Path(__file__).resolve().parents[1] / "contratos"


def test_trabajo_asignado_roundtrip_contrato_oficial():
    avsc = cargar_avsc(CONTRATOS, "evt.trabajos", "TrabajoAsignado")
    record = {
        "id": "11111111-1111-1111-1111-111111111111",
        "time": 1_700_000_000_000,
        "ingestion": 1_700_000_000_000,
        "specversion": "v1",
        "type": "TrabajoAsignado",
        "datacontenttype": "AVRO",
        "service_name": "emparejamiento-asignacion",
        "correlation_id": "22222222-2222-2222-2222-222222222222",
        "data": {
            "trabajo_id": "t-1",
            "asignacion_id": "a-1",
            "proveedor_id": "prov-a",
            "partner_id": "partner-31",
            "sla_vence_en": 1_700_000_000_000 + 120 * 60 * 1000,
            "origen_habilitacion": "PROYECCION_LOCAL",
        },
    }
    raw = encode_avro(avsc, record)
    back = decode_avro(avsc, raw)
    assert back["type"] == "TrabajoAsignado"
    assert back["service_name"] == "emparejamiento-asignacion"
    assert back["data"]["trabajo_id"] == "t-1"
    assert back["data"]["origen_habilitacion"] == "PROYECCION_LOCAL"
    assert back["data"]["partner_id"] == "partner-31"
    assert "verificadoEn" not in back
    assert "verificado_en" not in back
    assert "verificado_en" not in (back.get("data") or {})


def test_record_copiado_encode_coincide_con_avsc_oficial():
    avsc = cargar_avsc(CONTRATOS, "evt.trabajos", "TrabajoAsignado")
    rec = EventoTrabajoAsignado(
        id="11111111-1111-1111-1111-111111111111",
        time=1_700_000_000_000,
        ingestion=1_700_000_000_000,
        specversion="v1",
        type="TrabajoAsignado",
        datacontenttype="AVRO",
        service_name="emparejamiento-asignacion",
        correlation_id="22222222-2222-2222-2222-222222222222",
        data=TrabajoAsignadoPayload(
            trabajo_id="t-1",
            asignacion_id="a-1",
            proveedor_id="prov-a",
            partner_id="partner-31",
            sla_vence_en=1_700_000_000_000 + 120 * 60 * 1000,
            origen_habilitacion="PROYECCION_LOCAL",
        ),
    )
    raw_record = AvroSchema(EventoTrabajoAsignado).encode(rec)
    back = decode_avro(avsc, raw_record)
    assert back["type"] == "TrabajoAsignado"
    assert back["data"]["origen_habilitacion"] == "PROYECCION_LOCAL"


def test_esquemas_oficiales_existen_y_no_se_inventan():
    for topico, nombre in (
        ("evt.trabajos", "TrabajoCreado"),
        ("evt.trabajos", "TrabajoAsignado"),
        ("evt.trabajos", "TrabajoRechazado"),
        ("evt.partners", "ReglaDePartnerActualizada"),
        ("evt.proveedores", "EstadoDeHabilitacionCambiado"),
        ("evt.asignaciones", "AsignacionRechazadaPorHabilitacion"),
        ("evt.asignaciones", "AsignacionConfirmadaPorHabilitacion"),
        ("evt.asignaciones", "AsignacionAceptadaPorReglaPartner"),
        ("evt.asignaciones", "AsignacionRechazadaPorReglaPartner"),
        ("cmd.emparejamiento", "AsignarProveedor"),
    ):
        avsc = cargar_avsc(CONTRATOS, topico, nombre)
        assert avsc["type"] == "record"
        names = {f["name"] for f in avsc["fields"]}
        assert names >= {
            "id",
            "time",
            "ingestion",
            "specversion",
            "type",
            "datacontenttype",
            "service_name",
            "correlation_id",
            "data",
        }
