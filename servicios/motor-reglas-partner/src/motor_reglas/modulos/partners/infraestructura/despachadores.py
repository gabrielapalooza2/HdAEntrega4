"""Despachador: el único punto del servicio que habla con Apache Pulsar.

Encapsular el cliente aquí significa que ninguna otra capa importa `pulsar`. Si
mañana el broker cambiara, el cambio se agota en este archivo.
"""

import logging
import uuid

import pulsar
from pulsar.schema import AvroSchema

from motor_reglas.seedwork.infraestructura import utils

from .schema.v1.eventos import EventoReglaDePartnerActualizada, ReglaDePartnerActualizadaPayload

logger = logging.getLogger(__name__)


class Despachador:
    """Mantiene un cliente y un productor vivos.

    Crear un cliente por mensaje —como hace el tutorial— cuesta una conexión TCP y
    una negociación de esquema por evento. Bajo la carga del escenario de
    escalabilidad eso se convierte en el cuello de botella, y la medición terminaría
    hablando del cliente y no de la arquitectura.
    """

    def __init__(self):
        self._cliente = None
        self._productores = {}

    def _obtener_cliente(self):
        if self._cliente is None:
            self._cliente = pulsar.Client(utils.broker_url())
        return self._cliente

    def _obtener_productor(self, topico: str):
        if topico not in self._productores:
            self._productores[topico] = self._obtener_cliente().create_producer(
                topico,
                schema=AvroSchema(EventoReglaDePartnerActualizada),
                # batching para que el pico de 4x no se traduzca en 4x llamadas de red
                batching_enabled=True,
                batching_max_publish_delay_ms=10,
            )
        return self._productores[topico]

    def publicar_evento_regla(self, payload: dict, clave: str, correlation_id: str, topico: str):
        """Publica con CLAVE.

        La clave hace dos cosas a la vez: fija la partición, lo que garantiza el
        orden de los eventos de un mismo partner; y es la clave de compactación,
        lo que hace que el tópico conserve la última regla de cada partner y que un
        consumidor nuevo pueda reconstruir su proyección leyéndolo desde el inicio.
        """
        evento = EventoReglaDePartnerActualizada(
            id=str(uuid.uuid4()),
            time=utils.time_millis(),
            ingestion=utils.time_millis(),
            specversion="v1",
            type="ReglaDePartnerActualizada",
            datacontenttype="AVRO",
            service_name=utils.service_name(),
            correlation_id=correlation_id,
            data=ReglaDePartnerActualizadaPayload(**payload),
        )
        self._obtener_productor(topico).send(evento, partition_key=clave)
        logger.info("Publicado ReglaDePartnerActualizada partner=%s v=%s",
                    payload.get("partner_id"), payload.get("version_regla"))

    def cerrar(self):
        if self._cliente:
            self._cliente.close()
            self._cliente = None
            self._productores = {}
