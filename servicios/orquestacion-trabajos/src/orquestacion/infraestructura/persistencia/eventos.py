"""El EVENT STORE. Fuente de verdad del agregado Trabajo.

Append-only: este modulo solo sabe hacer INSERT y SELECT. No hay una sola
sentencia UPDATE ni DELETE sobre eventos_trabajo, y esa ausencia es lo que hace
que el congelamiento del SLA sea una GARANTIA y no una promesa.
"""
import json
import logging

import psycopg

from orquestacion.dominio import eventos as ev

logger = logging.getLogger(__name__)


class ConflictoDeConcurrencia(Exception):
    """Otro escritor gano la carrera sobre el mismo agregado.

    No es un error a reportar: es la senal de que hay que releer el agregado y
    volver a decidir sobre el estado nuevo.
    """


def leer(cur: psycopg.Cursor, trabajo_id: str) -> list[tuple[int, ev.EventoDeDominio]]:
    """La historia completa del agregado, en orden.

    ORDER BY secuencia y no por ocurrido_en: dos eventos pueden compartir marca
    de tiempo -now() es igual dentro de una transaccion- pero nunca comparten
    secuencia. El orden del agregado es la secuencia, no el reloj.
    """
    cur.execute(
        "SELECT secuencia, tipo, payload FROM eventos_trabajo "
        "WHERE trabajo_id = %s ORDER BY secuencia",
        (trabajo_id,),
    )
    return [(fila[0], ev.rehidratar(fila[1], fila[2])) for fila in cur.fetchall()]


def anexar(cur: psycopg.Cursor, trabajo_id: str,
           eventos: list[ev.EventoDeDominio], *, correlation_id: str,
           secuencia_actual: int) -> int:
    """Agrega eventos al final de la historia. Devuelve la secuencia final.

    ─── CONTROL DE CONCURRENCIA OPTIMISTA ────────────────────────────────
    La secuencia de cada evento se calcula a partir de `secuencia_actual`, que
    es la que se leyo al reconstruir el agregado. Si entre esa lectura y este
    INSERT otro proceso escribio, las dos escrituras piden la MISMA clave
    (trabajo_id, secuencia) y la PK compuesta rechaza a la segunda.

    No hay locks ni SELECT FOR UPDATE: el conflicto se DETECTA al escribir en
    vez de PREVENIRSE bloqueando. Eso es lo que significa "optimista", y es lo
    que permite que la lectura del agregado no bloquee a nadie.

    La UniqueViolation se traduce a ConflictoDeConcurrencia para que la capa de
    aplicacion no tenga que saber de psycopg.
    ───────────────────────────────────────────────────────────────────────
    """
    if not eventos:
        return secuencia_actual

    filas = [
        (trabajo_id, secuencia_actual + i, evento.TIPO,
         json.dumps(evento.a_payload()), correlation_id)
        for i, evento in enumerate(eventos, start=1)
    ]

    try:
        cur.executemany(
            "INSERT INTO eventos_trabajo "
            "  (trabajo_id, secuencia, tipo, payload, correlation_id) "
            "VALUES (%s, %s, %s, %s, %s)",
            filas,
        )
    except psycopg.errors.UniqueViolation as exc:
        raise ConflictoDeConcurrencia(
            f"Trabajo {trabajo_id}: otro escritor tomo la secuencia "
            f"{secuencia_actual + 1}"
        ) from exc

    return secuencia_actual + len(eventos)
