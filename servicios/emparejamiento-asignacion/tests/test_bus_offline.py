"""Simula el bus con los .avsc oficiales, sin Pulsar: otros MS no están."""
from __future__ import annotations

from pathlib import Path

from infraestructura.mensajeria.avro_codec import cargar_avsc, decode_avro, decode_evt_trabajos, encode_avro
from aplicacion.servicios import ServicioAsignacion, ServicioProyecciones
from tests.test_casos_uso import MemRepo, MemUoW, PubMem, RelojFijo, _ce

CONTRATOS = Path(__file__).resolve().parents[1] / "contratos"


def test_flujo_optimista_sobre_avsc_oficiales():
    avsc_regla = cargar_avsc(CONTRATOS, "evt.partners", "ReglaDePartnerActualizada")
    avsc_hab = cargar_avsc(CONTRATOS, "evt.proveedores", "EstadoDeHabilitacionCambiado")
    avsc_creado = cargar_avsc(CONTRATOS, "evt.trabajos", "TrabajoCreado")
    avsc_asignado = cargar_avsc(CONTRATOS, "evt.trabajos", "TrabajoAsignado")
    avsc_rechazado = cargar_avsc(CONTRATOS, "evt.trabajos", "TrabajoRechazado")
    avsc_rechazo = cargar_avsc(CONTRATOS, "evt.asignaciones", "AsignacionRechazadaPorHabilitacion")

    mem, pub = MemRepo(), PubMem()
    proy = ServicioProyecciones(lambda: MemUoW(mem))
    svc = ServicioAsignacion(lambda: MemUoW(mem), pub, RelojFijo())

    regla = _ce(
        "ReglaDePartnerActualizada",
        {
            "partner_id": "partner-31",
            "convenio_id": "conv-31",
            "nombre": "P31",
            "tipo_partner": "ASEGURADORA",
            "activo": True,
            "vigencia_desde": 1,
            "vigencia_hasta": 0,
            "version_regla": 1,
            "cobertura_contratada": ["PLOMERIA"],
            "sla_minutos": 120,
            "monto_maximo_sin_aprobacion": {"monto": 1, "moneda": "COP"},
            "pasos_de_aprobacion": [],
            "red_homologada": ["prov-b", "prov-a"],
            "porcentaje_comision": 0.0,
            "moneda_tarifa": "COP",
        },
        eid="regla-1",
    )
    proy.aplicar_regla_partner(decode_avro(avsc_regla, encode_avro(avsc_regla, regla)))

    for pid in ("prov-a", "prov-b"):
        hab = _ce(
            "EstadoDeHabilitacionCambiado",
            {
                "proveedor_id": pid,
                "nombre": pid,
                "estado": "HABILITADO",
                "categorias": ["PLOMERIA"],
                "ciudades": ["Bogota"],
                "motivo": "",
                "vigente_hasta": 0,
            },
            eid=f"hab-{pid}",
        )
        proy.aplicar_habilitacion(decode_avro(avsc_hab, encode_avro(avsc_hab, hab)))

    creado = _ce(
        "TrabajoCreado",
        {
            "trabajo_id": "t-1",
            "partner_id": "partner-31",
            "mercado_id": "CO",
            "categoria": "PLOMERIA",
            "urgencia": "ALTA",
            "ciudad": "Bogota",
            "sla_minutos": 120,
            "requiere_aprobacion": False,
        },
        eid="creado-1",
        corr="corr-1",
    )
    raw_creado = encode_avro(avsc_creado, creado)
    payload = decode_evt_trabajos(
        raw_creado,
        {
            "TrabajoCreado": avsc_creado,
            "TrabajoAsignado": avsc_asignado,
            "TrabajoRechazado": avsc_rechazado,
        },
    )
    r = svc.on_evento_trabajos(payload)
    assert r.evento is not None
    assert r.asignacion.proveedor_id == "prov-a"

    bus = decode_avro(avsc_asignado, encode_avro(avsc_asignado, r.evento.a_dict()))
    assert bus["type"] == "TrabajoAsignado"
    assert bus["service_name"] == "emparejamiento-asignacion"
    assert bus["correlation_id"] == "corr-1"
    assert bus["data"]["origen_habilitacion"] == "PROYECCION_LOCAL"
    assert bus["data"]["partner_id"] == "partner-31"

    rechazo = _ce(
        "AsignacionRechazadaPorHabilitacion",
        {
            "trabajo_id": "t-1",
            "asignacion_id": r.asignacion.asignacion_id,
            "proveedor_id": "prov-a",
            "estado_real": "SUSPENDIDO",
            "motivo": "demo",
            "verificado_en": 1,
        },
        eid="rej-1",
    )
    rr = svc.on_rechazo_habilitacion(decode_avro(avsc_rechazo, encode_avro(avsc_rechazo, rechazo)))
    assert rr.asignacion.estado.value == "RECHAZADO"
    assert len(pub.eventos) == 1
