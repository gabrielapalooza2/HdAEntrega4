"""Publica eventos Avro CloudEvents de prueba (otros MS no están). Prueba el DoD de este servicio."""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path

import httpx
import pulsar
from pulsar import ConsumerType, InitialPosition
from pulsar.schema import AvroSchema, BytesSchema

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from infraestructura.mensajeria.avro_codec import cargar_avsc, decode_avro, encode_avro  # noqa: E402

PULSAR_URL = os.environ.get("PULSAR_URL", "pulsar://localhost:6650")
BASE = os.environ.get("EMPAREJAMIENTO_URL", "http://localhost:8000")
CONTRATOS = Path(os.environ.get("CONTRATOS_DIR", str(ROOT / "contratos")))

TOPIC_TRABAJOS = "persistent://hda/poc/evt.trabajos"
TOPIC_PARTNERS = "persistent://hda/poc/evt.partners"
TOPIC_PROVEEDORES = "persistent://hda/poc/evt.proveedores"
TOPIC_ASIGNACIONES = "persistent://hda/poc/evt.asignaciones"


def _ahora_ms() -> int:
    return int(time.time() * 1000)


def esperar_ok(timeout=180):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            r = httpx.get(f"{BASE}/health", timeout=3.0)
            if r.status_code == 200 and r.json().get("status") == "ok":
                return r.json()
        except Exception:
            pass
        time.sleep(2)
    raise SystemExit("timeout esperando /health ok")


def esperar_proyecciones(min_reglas=1, min_habs=2, timeout=60):
    t0 = time.time()
    h = {}
    while time.time() - t0 < timeout:
        h = httpx.get(f"{BASE}/health", timeout=3.0).json()
        p = h.get("proyecciones") or {}
        if p.get("reglas", 0) >= min_reglas and p.get("habilitaciones", 0) >= min_habs:
            return h
        time.sleep(1)
    raise SystemExit(f"proyecciones no hidratadas: {h}")


def send_avro(client, topic, avsc, record, key: str, usar_schema: bool):
    if usar_schema:
        prod = client.create_producer(topic, schema=AvroSchema(None, schema_definition=avsc))
        prod.send(record, partition_key=key)
        prod.close()
    else:
        prod = client.create_producer(topic, schema=BytesSchema())
        prod.send(encode_avro(avsc, record), partition_key=key)
        prod.close()


def cloudevent(tipo: str, service_name: str, data: dict, correlation_id: str, event_id: str | None = None):
    now = _ahora_ms()
    return {
        "id": event_id or str(uuid.uuid4()),
        "time": now,
        "ingestion": now,
        "specversion": "v1",
        "type": tipo,
        "datacontenttype": "AVRO",
        "service_name": service_name,
        "correlation_id": correlation_id,
        "data": data,
    }


def main() -> int:
    print("esperando health...")
    print(esperar_ok())

    avsc_regla = cargar_avsc(CONTRATOS, "evt.partners", "ReglaDePartnerActualizada")
    avsc_hab = cargar_avsc(CONTRATOS, "evt.proveedores", "EstadoDeHabilitacionCambiado")
    avsc_creado = cargar_avsc(CONTRATOS, "evt.trabajos", "TrabajoCreado")
    avsc_asignado = cargar_avsc(CONTRATOS, "evt.trabajos", "TrabajoAsignado")
    avsc_rechazado = cargar_avsc(CONTRATOS, "evt.trabajos", "TrabajoRechazado")
    avsc_rechazo = cargar_avsc(CONTRATOS, "evt.asignaciones", "AsignacionRechazadaPorHabilitacion")

    client = pulsar.Client(PULSAR_URL)
    sub_verif = f"sim-verif-{uuid.uuid4().hex[:8]}"
    verif = client.subscribe(
        TOPIC_TRABAJOS,
        sub_verif,
        consumer_type=ConsumerType.Shared,
        initial_position=InitialPosition.Earliest,
        schema=BytesSchema(),
    )

    corr = str(uuid.uuid4())
    trabajo_id = str(uuid.uuid4())
    partner_id = "partner-31"

    regla = cloudevent(
        "ReglaDePartnerActualizada",
        "motor-reglas-partner",
        {
            "partner_id": partner_id,
            "convenio_id": "conv-31",
            "nombre": "Partner 31",
            "tipo_partner": "ASEGURADORA",
            "activo": True,
            "vigencia_desde": _ahora_ms() - 86_400_000,
            "vigencia_hasta": 0,
            "version_regla": 1,
            "cobertura_contratada": ["PLOMERIA", "ELECTRICIDAD"],
            "sla_minutos": 120,
            "monto_maximo_sin_aprobacion": {"monto": 50000000, "moneda": "COP"},
            "pasos_de_aprobacion": [],
            "red_homologada": ["prov-b", "prov-a"],
            "porcentaje_comision": 0.0,
            "moneda_tarifa": "COP",
        },
        corr,
    )
    send_avro(client, TOPIC_PARTNERS, avsc_regla, regla, partner_id, True)

    for proveedor_id, estado, cats, ciudades in (
        ("prov-a", "HABILITADO", ["PLOMERIA"], ["Bogota"]),
        ("prov-b", "HABILITADO", ["PLOMERIA"], ["Bogota"]),
        ("prov-c", "SUSPENDIDO", ["PLOMERIA"], ["Bogota"]),
        ("prov-d", "HABILITADO", ["ELECTRICIDAD"], ["Bogota"]),
    ):
        hab = cloudevent(
            "EstadoDeHabilitacionCambiado",
            "acreditacion-habilitacion",
            {
                "proveedor_id": proveedor_id,
                "nombre": proveedor_id,
                "estado": estado,
                "categorias": cats,
                "ciudades": ciudades,
                "motivo": "" if estado == "HABILITADO" else "demo",
                "vigente_hasta": 0,
            },
            corr,
        )
        send_avro(client, TOPIC_PROVEEDORES, avsc_hab, hab, proveedor_id, True)

    print("esperando hidratación de proyecciones...")
    print(esperar_proyecciones())

    creado = cloudevent(
        "TrabajoCreado",
        "orquestacion-trabajos",
        {
            "trabajo_id": trabajo_id,
            "partner_id": partner_id,
            "mercado_id": "CO",
            "categoria": "PLOMERIA",
            "urgencia": "ALTA",
            "ciudad": "Bogota",
            "sla_minutos": 120,
            "requiere_aprobacion": False,
        },
        corr,
    )
    evento_creado_id = creado["id"]
    send_avro(client, TOPIC_TRABAJOS, avsc_creado, creado, trabajo_id, False)

    # TrabajoRechazado ajeno: Emparejamiento debe filtrar y no crear fila extra
    otro_trabajo = str(uuid.uuid4())
    rechazado = cloudevent(
        "TrabajoRechazado",
        "orquestacion-trabajos",
        {
            "trabajo_id": otro_trabajo,
            "partner_id": partner_id,
            "categoria": "CARPINTERIA",
            "motivo": "FUERA_DE_COBERTURA",
            "detalle": "sim",
        },
        corr,
    )
    send_avro(client, TOPIC_TRABAJOS, avsc_rechazado, rechazado, otro_trabajo, False)

    asignacion = None
    t0 = time.time()
    while time.time() - t0 < 45:
        r = httpx.get(f"{BASE}/asignaciones/{trabajo_id}", timeout=3.0)
        if r.status_code == 200:
            asignacion = r.json()
            break
        time.sleep(1)
    if not asignacion:
        raise SystemExit("no apareció Asignacion")

    print("GET /asignaciones =>", json.dumps(asignacion, indent=2))
    assert asignacion["proveedor_id"] == "prov-a", asignacion
    assert asignacion["estado"] == "ASIGNADO"
    assert asignacion["correlation_id"] == corr
    assert asignacion["partner_id"] == partner_id
    assert asignacion["origen_habilitacion"] == "PROYECCION_LOCAL"
    assert asignacion["sla_vence_en"] == asignacion["time"] + 120 * 60 * 1000 or (
        asignacion["sla_vence_en"] - asignacion["verificado_en"]
    ) >= 119 * 60 * 1000

    r_otro = httpx.get(f"{BASE}/asignaciones/{otro_trabajo}", timeout=3.0)
    assert r_otro.status_code == 404

    visto_asignado = None
    t0 = time.time()
    while time.time() - t0 < 20 and visto_asignado is None:
        try:
            msg = verif.receive(timeout_millis=2000)
        except Exception:
            continue
        try:
            rec = decode_avro(avsc_asignado, bytes(msg.data()))
        except Exception:
            verif.acknowledge(msg)
            continue
        if rec.get("type") == "TrabajoAsignado" and (rec.get("data") or {}).get("trabajo_id") == trabajo_id:
            visto_asignado = rec
        verif.acknowledge(msg)
    if not visto_asignado:
        raise SystemExit("no se leyó TrabajoAsignado Avro")
    print("TrabajoAsignado Avro =>", json.dumps(visto_asignado, default=str))
    data_asig = visto_asignado["data"]
    assert visto_asignado["service_name"] == "emparejamiento-asignacion"
    assert visto_asignado["type"] == "TrabajoAsignado"
    assert visto_asignado["correlation_id"] == corr
    assert data_asig["proveedor_id"] == "prov-a"
    assert data_asig["asignacion_id"] == asignacion["asignacion_id"]
    assert data_asig["partner_id"] == partner_id
    assert data_asig["origen_habilitacion"] == "PROYECCION_LOCAL"
    assert "verificado_en" not in data_asig

    send_avro(client, TOPIC_TRABAJOS, avsc_creado, creado, trabajo_id, False)
    time.sleep(3)
    otra = httpx.get(f"{BASE}/asignaciones/{trabajo_id}", timeout=3.0).json()
    assert otra["asignacion_id"] == asignacion["asignacion_id"]

    spoof = cloudevent(
        "TrabajoAsignado",
        "emparejamiento-asignacion",
        {
            "trabajo_id": trabajo_id,
            "asignacion_id": str(uuid.uuid4()),
            "proveedor_id": "prov-spoof",
            "partner_id": partner_id,
            "sla_vence_en": _ahora_ms() + 1000,
            "origen_habilitacion": "PROYECCION_LOCAL",
        },
        corr,
    )
    spoof_id = spoof["id"]
    send_avro(client, TOPIC_TRABAJOS, avsc_asignado, spoof, trabajo_id, False)
    time.sleep(3)
    sigue = httpx.get(f"{BASE}/asignaciones/{trabajo_id}", timeout=3.0).json()
    assert sigue["proveedor_id"] == "prov-a"
    assert sigue["asignacion_id"] == asignacion["asignacion_id"]

    rechazo = cloudevent(
        "AsignacionRechazadaPorHabilitacion",
        "acreditacion-habilitacion",
        {
            "trabajo_id": trabajo_id,
            "asignacion_id": asignacion["asignacion_id"],
            "proveedor_id": "prov-a",
            "estado_real": "SUSPENDIDO",
            "motivo": "demo rechazo",
            "verificado_en": _ahora_ms(),
        },
        corr,
    )
    send_avro(client, TOPIC_ASIGNACIONES, avsc_rechazo, rechazo, trabajo_id, True)
    t0 = time.time()
    rechazada = None
    while time.time() - t0 < 20:
        rec = httpx.get(f"{BASE}/asignaciones/{trabajo_id}", timeout=3.0).json()
        if rec["estado"] == "RECHAZADO":
            rechazada = rec
            break
        time.sleep(1)
    if not rechazada:
        raise SystemExit("no marcó RECHAZADO")
    assert rechazada["asignacion_id"] == asignacion["asignacion_id"]

    extras = 0
    t0 = time.time()
    while time.time() - t0 < 8:
        try:
            msg = verif.receive(timeout_millis=1500)
        except Exception:
            continue
        try:
            rec = decode_avro(avsc_asignado, bytes(msg.data()))
            if rec.get("type") == "TrabajoAsignado" and (rec.get("data") or {}).get("trabajo_id") == trabajo_id:
                eid = rec.get("id")
                if eid != visto_asignado.get("id") and eid != spoof_id:
                    extras += 1
        except Exception:
            pass
        verif.acknowledge(msg)
    assert extras == 0, f"se republicó TrabajoAsignado ({extras})"

    verif.close()
    client.close()
    print("DoD simulación OK")
    print("evento_creado_id", evento_creado_id)
    print("trabajo_id", trabajo_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
