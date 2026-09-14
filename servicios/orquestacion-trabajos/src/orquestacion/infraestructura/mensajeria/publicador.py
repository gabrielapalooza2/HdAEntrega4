"""El RELAY del outbox: el unico productor de Pulsar del servicio.

Drena `outbox WHERE publicado_en IS NULL` y publica. Corre en su propio hilo,
desacoplado del camino de escritura: un trabajo se crea y se confirma sin
esperar al broker, y si Pulsar esta caido las filas se acumulan y salen solas
cuando vuelve. Eso es tolerancia a fallos sin reintentos en el camino critico.
"""
import logging
import threading
import time

import pulsar

from orquestacion import config
from orquestacion.infraestructura.persistencia import bd, outbox

logger = logging.getLogger(__name__)


class Publicador:
    """Mantiene vivos un cliente y un productor por topico.

    Crear un cliente por mensaje cuesta una conexion TCP y una negociacion de
    esquema por evento; bajo carga eso se vuelve el cuello de botella y la
    medicion terminaria hablando del cliente y no de la arquitectura.
    """

    def __init__(self):
        self._cliente = None
        self._productores = {}

    def _productor(self, topico: str):
        if self._cliente is None:
            self._cliente = pulsar.Client(
                config.broker_url(),
                logger=pulsar.ConsoleLogger(pulsar.LoggerLevel.Warn),
                **config.opciones_cliente(),
            )
        if topico not in self._productores:
            self._productores[topico] = self._cliente.create_producer(
                topico,
                # BytesSchema: el payload ya viene codificado desde el outbox.
                # El relay no conoce los contratos, solo mueve bytes.
                schema=pulsar.schema.BytesSchema(),
                batching_enabled=True,
                batching_max_publish_delay_ms=10,
            )
        return self._productores[topico]

    def publicar(self, topico: str, clave: str, payload: bytes) -> None:
        self._productor(topico).send(payload, partition_key=clave)

    def cerrar(self) -> None:
        if self._cliente:
            self._cliente.close()
            self._cliente = None
            self._productores = {}


def drenar(publicador: Publicador, limite: int = 100) -> int:
    """Publica un lote y marca las filas. Devuelve cuantos mensajes salieron.

    Todo el lote va en UNA transaccion: se toman las filas con FOR UPDATE SKIP
    LOCKED, se publican y se marcan. Si algo falla, el rollback devuelve las
    filas al estado pendiente y se reintentan en la vuelta siguiente.

    Ante un fallo se hace `break` y no `continue`: saltar al siguiente mensaje
    romperia el orden de publicacion de un mismo agregado, que es justo lo que
    la clave de particion trata de preservar.
    """
    publicados = []
    with bd.pool().connection() as con, con.cursor() as cur:
        pendientes = outbox.tomar_pendientes(cur, limite)
        for fila_id, topico, clave, payload in pendientes:
            try:
                publicador.publicar(topico, clave, bytes(payload))
                publicados.append(fila_id)
            except Exception:
                logger.exception("No se pudo publicar la fila %s del outbox; "
                                 "se reintenta en la proxima vuelta", fila_id)
                break
        outbox.marcar_publicado(cur, publicados)

    if publicados:
        logger.info("Relay: %s mensajes publicados", len(publicados))
    return len(publicados)


def bucle(parar: threading.Event) -> None:
    publicador = Publicador()
    try:
        while not parar.is_set():
            try:
                drenar(publicador)
            except Exception:
                logger.exception("Error en el relay del outbox")
            parar.wait(config.RELAY_OUTBOX_SEGUNDOS)
    finally:
        publicador.cerrar()
        logger.info("Relay del outbox detenido")


def arrancar(parar: threading.Event) -> threading.Thread:
    hilo = threading.Thread(target=bucle, args=(parar,), name="relay-outbox",
                            daemon=True)
    hilo.start()
    return hilo
