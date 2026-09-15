"""Arnés HTTP para Postman. NO es comunicación entre microservicios.

Orquestación y Acreditación no están en este repo. Estos POST publican los
mismos eventos Avro que esos servicios publicarían en Pulsar, para poder
recorrer emparejamiento → asignación → rechazo desde Collection Runner.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

import pulsar
from fastapi import APIRouter, HTTPException
from pulsar.schema import AvroSchema, BytesSchema
from pydantic import BaseModel

from infraestructura.mensajeria.avro_codec import cargar_avsc, encode_avro
from infraestructura.mensajeria.pulsar_io import (
    TOPIC_ASIGNACIONES,
    TOPIC_PARTNERS,
    TOPIC_PROVEEDORES,
    TOPIC_TRABAJOS,
)

log = logging.getLogger("emparejamiento.demo")

PARTNER_ID = "partner-31"


def ahora_ms() -> int:
    return int(time.time() * 1000)


def cloudevent(tipo: str, service_name: str, data: dict, correlation_id: str) -> dict:
    now = ahora_ms()
    return {
        "id": str(uuid.uuid4()),
        "time": now,
        "ingestion": now,
        "specversion": "v1",
        "type": tipo,
        "datacontenttype": "AVRO",
        "service_name": service_name,
        "correlation_id": correlation_id,
        "data": data,
    }


def payload_regla(correlation_id: str, partner_id: str = PARTNER_ID) -> dict:
    return cloudevent(
        "ReglaDePartnerActualizada",
        "motor-reglas-partner",
        {
            "partner_id": partner_id,
            "convenio_id": "conv-31",
            "nombre": "Partner 31",
            "tipo_partner": "ASEGURADORA",
            "activo": True,
            "vigencia_desde": ahora_ms() - 86_400_000,
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
        correlation_id,
    )


def payloads_habilitacion(correlation_id: str) -> list[tuple[str, dict]]:
    filas = (
        ("prov-a", "HABILITADO", ["PLOMERIA"], ["Bogota"]),
        ("prov-b", "HABILITADO", ["PLOMERIA"], ["Bogota"]),
        ("prov-c", "SUSPENDIDO", ["PLOMERIA"], ["Bogota"]),
        ("prov-d", "HABILITADO", ["ELECTRICIDAD"], ["Bogota"]),
    )
    out = []
    for proveedor_id, estado, cats, ciudades in filas:
        rec = cloudevent(
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
            correlation_id,
        )
        out.append((proveedor_id, rec))
    return out


def payload_trabajo_creado(
    trabajo_id: str, partner_id: str, correlation_id: str
) -> dict:
    return cloudevent(
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
        correlation_id,
    )


def payload_rechazo(
    trabajo_id: str,
    asignacion_id: str,
    proveedor_id: str,
    correlation_id: str,
    motivo: str,
) -> dict:
    return cloudevent(
        "AsignacionRechazadaPorHabilitacion",
        "acreditacion-habilitacion",
        {
            "trabajo_id": trabajo_id,
            "asignacion_id": asignacion_id,
            "proveedor_id": proveedor_id,
            "estado_real": "SUSPENDIDO",
            "motivo": motivo,
            "verificado_en": ahora_ms(),
        },
        correlation_id,
    )


class DemoBus:
    """Publica Avro en los tópicos oficiales (mismo cable que el simulador CLI)."""

    def __init__(self, client: pulsar.Client, contratos: Path) -> None:
        self._client = client
        self._lock = threading.Lock()
        self._prods: dict[tuple[str, bool], object] = {}
        self.avsc_regla = cargar_avsc(contratos, "evt.partners", "ReglaDePartnerActualizada")
        self.avsc_hab = cargar_avsc(contratos, "evt.proveedores", "EstadoDeHabilitacionCambiado")
        self.avsc_creado = cargar_avsc(contratos, "evt.trabajos", "TrabajoCreado")
        self.avsc_rechazo = cargar_avsc(
            contratos, "evt.asignaciones", "AsignacionRechazadaPorHabilitacion"
        )

    def _producer(self, topic: str, avsc: dict, usar_schema: bool):
        clave = (topic, usar_schema)
        with self._lock:
            prod = self._prods.get(clave)
            if prod is None:
                if usar_schema:
                    prod = self._client.create_producer(
                        topic, schema=AvroSchema(None, schema_definition=avsc)
                    )
                else:
                    prod = self._client.create_producer(topic, schema=BytesSchema())
                self._prods[clave] = prod
            return prod

    def send(self, topic: str, avsc: dict, record: dict, key: str, usar_schema: bool) -> None:
        prod = self._producer(topic, avsc, usar_schema)
        with self._lock:
            if usar_schema:
                prod.send(record, partition_key=key)
            else:
                prod.send(encode_avro(avsc, record), partition_key=key)
        log.info("demo publicó %s key=%s type=%s", topic, key, record.get("type"))


def serializar_asignacion(asignacion) -> dict:
    return {
        "asignacion_id": asignacion.asignacion_id,
        "trabajo_id": asignacion.trabajo_id,
        "proveedor_id": asignacion.proveedor_id,
        "partner_id": asignacion.partner_id,
        "estado": asignacion.estado.value,
        "sla_vence_en": asignacion.sla_vence_en,
        "origen_habilitacion": asignacion.origen_habilitacion,
        "verificado_en": asignacion.verificado_en,
        "correlation_id": asignacion.correlacion_id,
        "time": asignacion.ocurrido_en,
    }


def esperar_proyecciones(fabrica_uow, min_reglas=1, min_habs=2, timeout=45.0) -> dict:
    t0 = time.time()
    ultimo = {"reglas": 0, "habilitaciones": 0}
    while time.time() - t0 < timeout:
        uow = fabrica_uow()
        try:
            ultimo = {
                "reglas": uow.reglas.contar(),
                "habilitaciones": uow.habilitaciones.contar(),
            }
        finally:
            uow.rollback()
        if ultimo["reglas"] >= min_reglas and ultimo["habilitaciones"] >= min_habs:
            return ultimo
        time.sleep(0.4)
    raise HTTPException(status_code=504, detail=f"proyecciones no hidratadas: {ultimo}")


def esperar_asignacion(
    consultar: Callable, trabajo_id: str, estado: str | None = None, timeout=45.0
):
    t0 = time.time()
    ultimo = None
    while time.time() - t0 < timeout:
        ultimo = consultar(trabajo_id)
        if ultimo is not None and (estado is None or ultimo.estado.value == estado):
            return ultimo
        time.sleep(0.4)
    raise HTTPException(
        status_code=504,
        detail={
            "mensaje": f"no llegó asignación estado={estado}",
            "trabajo_id": trabajo_id,
            "visto": serializar_asignacion(ultimo) if ultimo is not None else None,
        },
    )


class RechazoIn(BaseModel):
    trabajo_id: str
    asignacion_id: str | None = None
    proveedor_id: str | None = None
    correlation_id: str | None = None
    motivo: str = "demo rechazo"


def montar_demo(estado: dict) -> APIRouter:
    router = APIRouter(
        prefix="/demo/flujo",
        tags=["demo — simulador de MS ausentes (no es API de negocio)"],
    )

    def bus() -> DemoBus:
        demo = estado.get("demo_bus")
        if demo is None or not estado.get("listo"):
            raise HTTPException(status_code=503, detail="servicio no listo")
        return demo

    @router.post("/preparar")
    def preparar():
        """Publica regla + habilitaciones (carga de estado) y espera proyecciones locales."""
        demo = bus()
        corr = str(uuid.uuid4())
        regla = payload_regla(corr)
        demo.send(TOPIC_PARTNERS, demo.avsc_regla, regla, PARTNER_ID, True)
        for proveedor_id, hab in payloads_habilitacion(corr):
            demo.send(TOPIC_PROVEEDORES, demo.avsc_hab, hab, proveedor_id, True)
        proyecciones = esperar_proyecciones(estado["fabrica_uow"])
        return {
            "ok": True,
            "simulando": ["motor-reglas-partner", "acreditacion-habilitacion"],
            "partner_id": PARTNER_ID,
            "correlation_id": corr,
            "proyecciones": proyecciones,
            "nota": "Emparejamiento no llamó a nadie por HTTP: hidrató evt.partners y evt.proveedores.",
        }

    @router.post("/trabajo-creado")
    def trabajo_creado(partner_id: str = PARTNER_ID):
        """Publica TrabajoCreado (como Orquestación) y espera ASIGNADO."""
        demo = bus()
        corr = str(uuid.uuid4())
        trabajo_id = str(uuid.uuid4())
        rec = payload_trabajo_creado(trabajo_id, partner_id, corr)
        demo.send(TOPIC_TRABAJOS, demo.avsc_creado, rec, trabajo_id, False)
        asignacion = esperar_asignacion(
            estado["asignacion"].consultar, trabajo_id, estado="ASIGNADO"
        )
        return {
            "ok": True,
            "simulando": "orquestacion-trabajos",
            "evento": "TrabajoCreado",
            "trabajo_id": trabajo_id,
            "correlation_id": corr,
            "partner_id": partner_id,
            "asignacion": serializar_asignacion(asignacion),
            "nota": "Matching local. origen_habilitacion=PROYECCION_LOCAL.",
        }

    @router.post("/rechazo")
    def rechazo(cuerpo: RechazoIn):
        """Publica AsignacionRechazadaPorHabilitacion y espera RECHAZADO (sin reasignar)."""
        demo = bus()
        servicio = estado["asignacion"]
        actual = servicio.consultar(cuerpo.trabajo_id)
        if actual is None:
            raise HTTPException(status_code=404, detail="asignacion no encontrada")
        asignacion_id = cuerpo.asignacion_id or actual.asignacion_id
        proveedor_id = cuerpo.proveedor_id or actual.proveedor_id
        corr = cuerpo.correlation_id or actual.correlacion_id
        rec = payload_rechazo(
            cuerpo.trabajo_id, asignacion_id, proveedor_id, corr, cuerpo.motivo
        )
        demo.send(TOPIC_ASIGNACIONES, demo.avsc_rechazo, rec, cuerpo.trabajo_id, True)
        asignacion = esperar_asignacion(
            servicio.consultar, cuerpo.trabajo_id, estado="RECHAZADO"
        )
        return {
            "ok": True,
            "simulando": "acreditacion-habilitacion",
            "evento": "AsignacionRechazadaPorHabilitacion",
            "trabajo_id": cuerpo.trabajo_id,
            "asignacion": serializar_asignacion(asignacion),
            "nota": "Compensación E4: marca RECHAZADO y no publica otro TrabajoAsignado.",
        }

    return router
