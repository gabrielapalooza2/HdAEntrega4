"""OUTBOX: atomicidad entre PostgreSQL y Pulsar.

El problema que resuelve: guardar el evento y publicarlo son dos sistemas
distintos sin transaccion comun. Si se publicara primero y la base fallara,
habria un evento que describe algo que no paso. Si se guardara primero y el
proceso muriera antes de publicar, habria un trabajo del que nadie se entera.

La solucion es no publicar nunca desde el camino de escritura: se ENCOLA una
fila en la misma transaccion, y un hilo aparte la drena hacia el broker.

GARANTIA: al menos una vez. Si el relay publica y muere antes de marcar la fila,
republica al reiniciar. Por eso todo consumidor del sistema es idempotente.
"""
import logging

import psycopg

logger = logging.getLogger(__name__)


def encolar(cur: psycopg.Cursor, *, topico: str, clave: str, payload: bytes) -> None:
    """Se llama DENTRO de la transaccion de dominio, antes del commit.

    No publica nada: solo deja la fila. El COMMIT es lo que hace que el mensaje
    exista, y por eso no puede haber un mensaje que anuncie un cambio que no
    ocurrio.

    `payload` son los bytes Avro YA CODIFICADOS. El relay no vuelve a codificar
    ni conoce los contratos: solo mueve bytes a un topico.
    """
    cur.execute(
        "INSERT INTO outbox (topico, clave, payload) VALUES (%s, %s, %s)",
        (topico, clave, payload),
    )


def tomar_pendientes(cur: psycopg.Cursor, limite: int = 100) -> list[tuple]:
    """Reserva un lote de mensajes sin publicar.

    FOR UPDATE SKIP LOCKED: si hubiera varias replicas del servicio, cada relay
    toma un lote distinto en vez de que todos publiquen las mismas filas.

    SALVEDAD que hay que saber: con varios relays en paralelo se preserva el
    orden DENTRO de un lote, pero no entre lotes de replicas distintas. Para
    esta prueba de concepto corre un solo relay -el Dockerfile fija un worker de
    gunicorn justamente por esto-. Con varias replicas habria que particionar el
    outbox por agregado para conservar el orden por trabajo.
    """
    cur.execute(
        "SELECT id, topico, clave, payload FROM outbox "
        "WHERE publicado_en IS NULL ORDER BY id LIMIT %s "
        "FOR UPDATE SKIP LOCKED",
        (limite,),
    )
    return cur.fetchall()


def marcar_publicado(cur: psycopg.Cursor, ids: list[int]) -> None:
    if ids:
        cur.execute("UPDATE outbox SET publicado_en = now() WHERE id = ANY(%s)", (ids,))


def pendientes(cur: psycopg.Cursor) -> int:
    cur.execute("SELECT count(*) FROM outbox WHERE publicado_en IS NULL")
    return cur.fetchone()[0]
