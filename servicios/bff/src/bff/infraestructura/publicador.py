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
            except Exception as e:                       
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
            except Exception:                           
                pass
        if self._cliente is not None:
            try:
                self._cliente.close()
            except Exception:                             
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

        if clave_particion:
            productor.send(crudo, partition_key=str(clave_particion))
        else:
            productor.send(crudo)
        log.info("publicado %s corr=%s en %s (%d bytes)",
                 tipo, correlation_id, topico, len(crudo))


publicador = Publicador()
