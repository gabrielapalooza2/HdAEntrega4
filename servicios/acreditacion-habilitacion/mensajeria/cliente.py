"""Cliente Pulsar: fabrica, topicos/suscripciones, y el publicador.

Separado de contratos.py a proposito: este archivo es plomeria de
mensajeria (conexion, productores, topicos), contratos.py es SOLO
traduccion Avro/CloudEvents. Mismo criterio de separacion de
responsabilidades que el resto del dominio.
"""
from __future__ import annotations

import logging
import os

import pulsar

from . import contratos

logger = logging.getLogger(__name__)

PULSAR_URL = os.getenv("PULSAR_URL", "pulsar://localhost:6650")

TOPICO_CMD_PROVEEDORES = "persistent://hda/poc/cmd.proveedores"
TOPICO_EVT_TRABAJOS = "persistent://hda/poc/evt.trabajos"
TOPICO_EVT_PROVEEDORES = "persistent://hda/poc/evt.proveedores"
TOPICO_EVT_ASIGNACIONES = "persistent://hda/poc/evt.asignaciones"

SUSCRIPCION_CMD_PROVEEDORES = "acreditacion-cmd-proveedores"
SUSCRIPCION_EVT_TRABAJOS = "acreditacion-evt-trabajos"


def crear_cliente() -> pulsar.Client:
    return pulsar.Client(PULSAR_URL)


class Publicador:
    """Envuelve los productores de los dos topicos que este servicio
    publica (single writer principle: nadie mas escribe en estos)."""

    def __init__(self, cliente: pulsar.Client):
        self._cliente = cliente
        self._productores: dict[str, pulsar.Producer] = {}

    def _productor(self, topico: str) -> pulsar.Producer:
        if topico not in self._productores:
            self._productores[topico] = self._cliente.create_producer(topico)
        return self._productores[topico]

    def publicar(self, evento, correlation_id: str):
        from dominio.eventos import (
            AsignacionConfirmadaPorHabilitacion,
            AsignacionRechazadaPorHabilitacion,
            EstadoDeHabilitacionCambiado,
        )

        if isinstance(evento, EstadoDeHabilitacionCambiado):
            topico, clave = TOPICO_EVT_PROVEEDORES, evento.proveedor_id
        elif isinstance(evento, (AsignacionRechazadaPorHabilitacion,
                                 AsignacionConfirmadaPorHabilitacion)):
            topico, clave = TOPICO_EVT_ASIGNACIONES, evento.trabajo_id
        else:
            raise NotImplementedError(f"No se sabe a que topico publicar {type(evento).__name__}")

        payload, propiedades = contratos.codificar_evento(evento, correlation_id)
        self._productor(topico).send(payload, partition_key=clave, properties=propiedades)
        logger.info("[PULSAR publicado] topico=%s clave=%s type=%s correlation_id=%s",
                    topico, clave, propiedades["type"], correlation_id)

    def cerrar(self):
        for p in self._productores.values():
            p.close()
