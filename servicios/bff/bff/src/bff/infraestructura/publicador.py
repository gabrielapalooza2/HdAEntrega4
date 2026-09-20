"""Publicacion de comandos en Apache Pulsar.

El BFF solo PUBLICA COMANDOS. No publica eventos: un evento es la afirmacion de
algo que ya paso dentro de una agregacion, y el BFF no posee ninguna. Tampoco
llama a ningun servicio por HTTP ni por gRPC, que es lo que el enunciado prohibe.

Productores con `BytesSchema`, igual que Orquestacion, Acreditacion y
Emparejamiento: el payload se codifica aqui con los .avsc del equipo. Ver
`esquemas/avro.py` para por que no se usa `AvroSchema`.
"""

import logging
import threading
import time
import uuid

from .. import config
from ..esquemas import avro

log = logging.getLogger("bff.publicador")


def ahora_ms() -> int:
    return int(time.time() * 1000)


class Publicador:
    def __init__(self):
        self._cliente = None
        self._productores: dict[str, object] = {}
        self._candado = threading.Lock()

    # ── ciclo de vida ────────────────────────────────────────────────────────

    def conectar(self):
        import pulsar

        limite = time.time() + config.ESPERA_BROKER_SEGUNDOS
        ultimo_error = None
        while time.time() < limite:
            try:
                self._cliente = pulsar.Client(config.PULSAR_URL)
                log.info("conectado a %s", config.PULSAR_URL)
                return
            except Exception as e:                         # noqa: BLE001
                ultimo_error = e
                time.sleep(3)
        raise RuntimeError(
            f"no se pudo conectar a {config.PULSAR_URL} en "
            f"{config.ESPERA_BROKER_SEGUNDOS}s: {ultimo_error}"
        )

    def cerrar(self):
        for p in self._productores.values():
            try:
                p.close()
            except Exception:                              # noqa: BLE001
                pass
        if self._cliente is not None:
            try:
                self._cliente.close()
            except Exception:                              # noqa: BLE001
                pass

    # ── publicacion ──────────────────────────────────────────────────────────

    def _productor(self, topico: str):
        import pulsar

        with self._candado:
            if topico not in self._productores:
                self._productores[topico] = self._cliente.create_producer(
                    topico, schema=pulsar.schema.BytesSchema()
                )
            return self._productores[topico]

    def publicar(self, topico: str, tipo: str, payload: dict,
                 correlation_id: str, clave_particion: str | None = None):
        """Arma el sobre CloudEvents, lo codifica en Avro y lo envia."""
        sobre = {
            "id": str(uuid.uuid4()),
            "time": ahora_ms(),
            "ingestion": ahora_ms(),
            "specversion": "v1",
            "type": tipo,
            "datacontenttype": "AVRO",
            "service_name": config.SERVICE_NAME,
            "correlation_id": correlation_id,
            "data": avro.completar(tipo, payload),
        }
        crudo = avro.codificar(sobre)
        productor = self._productor(topico)
        # La clave de particion decide el orden: dos comandos sobre el MISMO
        # partner o el MISMO trabajo deben caer en la misma particion para que
        # lleguen en orden. Sin esto, "actualizar regla" podria adelantar a
        # "registrar partner".
        if clave_particion:
            productor.send(crudo, partition_key=str(clave_particion))
        else:
            productor.send(crudo)
        log.info("publicado %s corr=%s en %s (%d bytes)",
                 tipo, correlation_id, topico, len(crudo))


publicador = Publicador()
