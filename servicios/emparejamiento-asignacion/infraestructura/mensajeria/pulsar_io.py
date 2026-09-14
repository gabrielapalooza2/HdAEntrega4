from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable

import pulsar
from pulsar import ConsumerType, InitialPosition
from pulsar.schema import BytesSchema

from infraestructura.mensajeria.avro_codec import (
    cargar_avsc,
    decode_avro,
    decode_evt_trabajos,
    encode_avro,
    record_to_plain,
    schema_pulsar,
)
from dominio.modelo import TrabajoAsignado
from infraestructura.schema.v1.eventos import (
    EventoAsignacionRechazadaPorHabilitacion,
    EventoEstadoDeHabilitacionCambiado,
    EventoReglaDePartnerActualizada,
)

log = logging.getLogger("emparejamiento.pulsar")

TOPIC_TRABAJOS = "persistent://hda/poc/evt.trabajos"
TOPIC_PARTNERS = "persistent://hda/poc/evt.partners"
TOPIC_PROVEEDORES = "persistent://hda/poc/evt.proveedores"
TOPIC_ASIGNACIONES = "persistent://hda/poc/evt.asignaciones"

SUB_PARTNERS = "emparejamiento-asignacion-partners"
SUB_PROVEEDORES = "emparejamiento-asignacion-proveedores"
SUB_TRABAJOS = "emparejamiento-asignacion-trabajos"
SUB_ASIGNACIONES = "emparejamiento-asignacion-asignaciones"


class PublicadorTrabajoAsignadoPulsar:
    """Único productor de TrabajoAsignado. Clave: data.trabajo_id."""

    def __init__(self, client: pulsar.Client, avsc: dict) -> None:
        self._avsc = avsc
        self._lock = threading.Lock()
        # evt.trabajos lleva TrabajoCreado, TrabajoRechazado y TrabajoAsignado.
        # Pulsar registra un esquema por tópico; BACKWARD no admite los tres.
        # Codificamos con el .avsc oficial (idéntico al Record copiado) y
        # publicamos bytes Avro. Compactados de un solo tipo sí usan AvroSchema.
        self._producer = client.create_producer(
            TOPIC_TRABAJOS,
            producer_name="emparejamiento-asignacion",
            schema=BytesSchema(),
        )

    def publicar(self, evento: TrabajoAsignado) -> None:
        payload = evento.a_dict()
        clave = evento.trabajo_id
        with self._lock:
            self._producer.send(encode_avro(self._avsc, payload), partition_key=clave)
            log.info(
                "publicado TrabajoAsignado trabajo_id=%s asignacion_id=%s proveedor_id=%s",
                evento.trabajo_id,
                evento.asignacion_id,
                evento.proveedor_id,
            )


class ConsumidoresPulsar:
    def __init__(
        self,
        client: pulsar.Client,
        contratos_dir: Path,
        on_regla: Callable,
        on_habilitacion: Callable,
        on_trabajos: Callable,
        on_rechazo: Callable,
    ) -> None:
        self._client = client
        self._on_regla = on_regla
        self._on_habilitacion = on_habilitacion
        self._on_trabajos = on_trabajos
        self._on_rechazo = on_rechazo
        self._stop = threading.Event()
        self._hilos: list[threading.Thread] = []
        self._consumers: list[pulsar.Consumer] = []

        self.avsc_regla = cargar_avsc(contratos_dir, "evt.partners", "ReglaDePartnerActualizada")
        self.avsc_hab = cargar_avsc(contratos_dir, "evt.proveedores", "EstadoDeHabilitacionCambiado")
        self.avsc_creado = cargar_avsc(contratos_dir, "evt.trabajos", "TrabajoCreado")
        self.avsc_asignado = cargar_avsc(contratos_dir, "evt.trabajos", "TrabajoAsignado")
        self.avsc_rechazado = cargar_avsc(contratos_dir, "evt.trabajos", "TrabajoRechazado")
        self.avsc_rechazo = cargar_avsc(
            contratos_dir, "evt.asignaciones", "AsignacionRechazadaPorHabilitacion"
        )
        self._avsc_trabajos = {
            "TrabajoCreado": self.avsc_creado,
            "TrabajoAsignado": self.avsc_asignado,
            "TrabajoRechazado": self.avsc_rechazado,
        }

    def arrancar(self) -> None:
        # Compacted read exige Exclusive/Failover; nunca Exclusive.
        # Shared + Earliest relee el tópico desde el inicio (carga de estado).
        specs = [
            (TOPIC_PARTNERS, SUB_PARTNERS, True, self.avsc_regla, self._manejar_regla),
            (TOPIC_PROVEEDORES, SUB_PROVEEDORES, True, self.avsc_hab, self._manejar_habilitacion),
            (TOPIC_TRABAJOS, SUB_TRABAJOS, False, None, self._manejar_trabajos),
            (TOPIC_ASIGNACIONES, SUB_ASIGNACIONES, False, self.avsc_rechazo, self._manejar_rechazo),
        ]
        for topic, sub, shared_ok, avsc, handler in specs:
            consumer = self._subscribe(topic, sub, prefer_key_shared=not shared_ok, avsc=avsc)
            self._consumers.append(consumer)
            hilo = threading.Thread(
                target=self._loop,
                args=(consumer, handler, topic),
                name=f"pulsar-{sub}",
                daemon=True,
            )
            hilo.start()
            self._hilos.append(hilo)

    def detener(self) -> None:
        self._stop.set()
        for c in self._consumers:
            try:
                c.close()
            except Exception:
                pass

    def _subscribe(self, topic, sub, prefer_key_shared: bool, avsc):
        tipos = (
            [ConsumerType.KeyShared, ConsumerType.Shared]
            if prefer_key_shared
            else [ConsumerType.Shared]
        )
        schemas = []
        if avsc is not None:
            schemas.append(schema_pulsar(avsc))
        schemas.append(BytesSchema())
        ultimo = None
        for ctype in tipos:
            for schema in schemas:
                try:
                    consumer = self._client.subscribe(
                        topic=topic,
                        subscription_name=sub,
                        consumer_type=ctype,
                        initial_position=InitialPosition.Earliest,
                        schema=schema,
                        consumer_name=sub,
                        negative_ack_redelivery_delay_ms=2000,
                    )
                    log.info("consumidor %s en %s (%s %s)", sub, topic, ctype, type(schema).__name__)
                    return consumer
                except Exception as exc:
                    ultimo = exc
                    log.warning("subscribe %s %s %s falló (%s)", topic, ctype, type(schema).__name__, exc)
        raise RuntimeError(f"no se pudo suscribir a {topic}: {ultimo}")

    def _loop(self, consumer: pulsar.Consumer, handler: Callable, topic: str) -> None:
        while not self._stop.is_set():
            try:
                msg = consumer.receive(timeout_millis=1000)
            except Exception:
                continue
            try:
                handler(msg)
                consumer.acknowledge(msg)
            except Exception:
                log.exception("error procesando %s", topic)
                consumer.negative_acknowledge(msg)

    def _payload(self, msg: pulsar.Message, avsc: dict) -> dict:
        valor = msg.value()
        if isinstance(valor, dict):
            return record_to_plain(valor)
        if valor is not None and not isinstance(valor, (bytes, bytearray)):
            return record_to_plain(valor)
        return decode_avro(avsc, bytes(msg.data()))

    def _manejar_regla(self, msg: pulsar.Message) -> None:
        self._on_regla(self._payload(msg, self.avsc_regla))

    def _manejar_habilitacion(self, msg: pulsar.Message) -> None:
        self._on_habilitacion(self._payload(msg, self.avsc_hab))

    def _manejar_trabajos(self, msg: pulsar.Message) -> None:
        payload = decode_evt_trabajos(bytes(msg.data()), self._avsc_trabajos)
        if payload is None:
            valor = msg.value()
            if isinstance(valor, dict):
                payload = record_to_plain(valor)
            elif valor is not None and not isinstance(valor, (bytes, bytearray)):
                payload = record_to_plain(valor)
        if payload is None:
            log.warning("evt.trabajos no decodificable; ack y skip")
            return
        self._on_trabajos(payload)

    def _manejar_rechazo(self, msg: pulsar.Message) -> None:
        self._on_rechazo(self._payload(msg, self.avsc_rechazo))


# Referencias para que el schema registry de tópicos de un solo tipo
# coincida con los Record copiados (mismo Avro que generar.py).
RECORD_REGLA = EventoReglaDePartnerActualizada
RECORD_HABILITACION = EventoEstadoDeHabilitacionCambiado
RECORD_RECHAZO = EventoAsignacionRechazadaPorHabilitacion
