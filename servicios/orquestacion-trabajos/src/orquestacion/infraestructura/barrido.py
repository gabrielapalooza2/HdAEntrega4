"""Hilo del barrido de SLA.

Corre cada 30 segundos. Es la unica fuente de estimulo del sistema que no viene
de un mensaje: el paso del tiempo.
"""
import logging
import threading

from orquestacion import config
from orquestacion.aplicacion import trabajos

logger = logging.getLogger(__name__)


def bucle(parar: threading.Event) -> None:
    while not parar.is_set():
        # Espera PRIMERO: al arrancar, la proyeccion puede estar reconstruyendose
        # desde el tópico compactado y barrer en ese momento daria falsos
        # vencimientos sobre datos a medio cargar.
        parar.wait(config.BARRIDO_SLA_SEGUNDOS)
        if parar.is_set():
            break
        try:
            trabajos.barrer_sla()
        except Exception:
            logger.exception("Error en el barrido de SLA")
    logger.info("Barrido de SLA detenido")


def arrancar(parar: threading.Event) -> threading.Thread:
    hilo = threading.Thread(target=bucle, args=(parar,), name="barrido-sla",
                            daemon=True)
    hilo.start()
    return hilo
