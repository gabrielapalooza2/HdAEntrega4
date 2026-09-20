"""Consumidor de evt.trabajos: el paso de Motor en la saga.

Key_Shared por trabajo_id para no procesar dos asignaciones del mismo trabajo
en paralelo. BytesSchema porque el topico es multi-tipo.
"""
from __future__ import annotations

import logging
import traceback

import _pulsar
import pulsar
from pulsar.schema import BytesSchema

from motor_reglas.seedwork.infraestructura import utils

from ..aplicacion.comandos.verificar_asignacion import VerificarAsignacion, ejecutar
from .saga_contratos import tipo_del_sobre

logger = logging.getLogger(__name__)

TOPICO_EVT_TRABAJOS = "persistent://hda/poc/evt.trabajos"
TIPO_TRABAJO_ASIGNADO = "TrabajoAsignado"


def suscribirse_a_trabajos(app=None, topico: str = TOPICO_EVT_TRABAJOS):
    cliente = None
    try:
        cliente = pulsar.Client(utils.broker_url())
        consumidor = cliente.subscribe(
            topico,
            consumer_type=_pulsar.ConsumerType.KeyShared,
            subscription_name="motor-reglas-partner-sub-asignaciones",
            schema=BytesSchema(),
        )
        logger.info("Escuchando TrabajoAsignado en %s (paso de saga)", topico)

        while True:
            mensaje = consumidor.receive()
            try:
                crudo = bytes(mensaje.data())
                tipo = (mensaje.properties() or {}).get("type") or tipo_del_sobre(crudo)
                if tipo != TIPO_TRABAJO_ASIGNADO:
                    consumidor.acknowledge(mensaje)
                    continue

                with app.app_context():
                    sobre = decodificar_trabajo_asignado(crudo)
                    data = sobre.get("data") or {}
                    resultado = ejecutar(VerificarAsignacion(
                        trabajo_id=data.get("trabajo_id") or "",
                        asignacion_id=data.get("asignacion_id") or "",
                        proveedor_id=data.get("proveedor_id") or "",
                        partner_id=data.get("partner_id") or "",
                        correlation_id=sobre.get("correlation_id") or "",
                        mensaje_id=sobre.get("id") or "",
                    ))
                    logger.info(
                        "saga regla partner trabajo=%s proveedor=%s resultado=%s",
                        data.get("trabajo_id"), data.get("proveedor_id"), resultado,
                    )
                consumidor.acknowledge(mensaje)
            except Exception:
                logger.exception("Error en el paso de saga; se devuelve al broker")
                consumidor.negative_acknowledge(mensaje)
    except Exception:
        logger.error("ERROR suscribiendose a evt.trabajos para la saga")
        traceback.print_exc()
    finally:
        if cliente:
            cliente.close()


def decodificar_trabajo_asignado(payload: bytes) -> dict:
    """Decodifica TrabajoAsignado con su .avsc oficial."""
    from pathlib import Path
    import json
    import io
    import fastavro
    from .saga_contratos import contratos_dir

    ruta = Path(contratos_dir()) / "esquemas" / "evt.trabajos" / "TrabajoAsignado.avsc"
    schema = fastavro.parse_schema(json.loads(ruta.read_text(encoding="utf-8")))
    return fastavro.schemaless_reader(io.BytesIO(payload), schema)
