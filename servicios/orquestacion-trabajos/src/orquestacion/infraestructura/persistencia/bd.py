"""Conexion a PostgreSQL con psycopg3 y SQL crudo. Sin ORM.

Por que sin ORM: el control de concurrencia optimista de este servicio consiste
en ATRAPAR la violacion de la PK compuesta (trabajo_id, secuencia). Un ORM mete
en medio una sesion con cache de identidad y unit-of-work propia, que oscurece
exactamente el momento en que la escritura choca. Aqui el SQL es el diseno.
"""
import logging
from pathlib import Path

import psycopg
from psycopg_pool import ConnectionPool

from orquestacion import config

logger = logging.getLogger(__name__)

# El esquema vive junto al codigo y se aplica al arrancar. Es todo IF NOT
# EXISTS, asi que arrancar N replicas a la vez no rompe nada.
#
# Se busca hacia arriba, no con un parents[N] fijo: el paquete esta a distinta
# profundidad en el repo y en la imagen, y un indice fijo revienta en uno de los
# dos. Mismo criterio que en config.CONTRATOS_DIR.
def _ruta_esquema() -> Path:
    for padre in Path(__file__).resolve().parents:
        candidato = padre / "db" / "esquema.sql"
        if candidato.is_file():
            return candidato
    raise FileNotFoundError("No se encontro db/esquema.sql")


RUTA_ESQUEMA = _ruta_esquema()

_pool: ConnectionPool | None = None


def pool() -> ConnectionPool:
    """Pool perezoso y compartido.

    Un pool y no una conexion por operacion: el relay del outbox, los tres
    consumidores y el barrido de SLA son hilos distintos del mismo proceso, y
    una conexion de psycopg no se comparte entre hilos.
    """
    global _pool
    if _pool is None:
        _pool = ConnectionPool(config.dsn(), min_size=1, max_size=10,
                               kwargs={"autocommit": False}, open=True)
    return _pool


def aplicar_esquema() -> None:
    with pool().connection() as con:
        con.execute(RUTA_ESQUEMA.read_text(encoding="utf-8"))
    logger.info("Esquema aplicado desde %s", RUTA_ESQUEMA)


def cerrar() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


# ═══════════════════════════════════════════════════════════ idempotencia ══

def reclamar_mensaje(cur: psycopg.Cursor, message_id: str) -> bool:
    """Marca el mensaje como procesado. Devuelve False si YA lo estaba.

    Un solo INSERT y no un SELECT seguido de un INSERT: entre "verificar" y
    "marcar" habria una ventana en la que dos hilos -o dos replicas- podrian
    colarse los dos. `ON CONFLICT DO NOTHING` deja que la restriccion de unicidad
    resuelva la carrera dentro del motor, que es donde se puede resolver bien.

    ESTA LLAMADA VA EN LA MISMA TRANSACCION QUE EL EFECTO DEL MENSAJE. Si el
    efecto falla y se hace rollback, la marca desaparece con el, y el mensaje se
    vuelve a procesar cuando Pulsar lo reentregue. O se aplican los dos, o
    ninguno.

    Protege contra la REPETICION. El DESORDEN lo cubre el numero de version.
    """
    cur.execute(
        "INSERT INTO mensajes_procesados (message_id) VALUES (%s) "
        "ON CONFLICT (message_id) DO NOTHING",
        (_como_uuid(message_id),),
    )
    return cur.rowcount == 1


def _como_uuid(valor: str) -> str:
    """El contrato declara `id` como string, no como UUID, asi que nada obliga
    al emisor a mandar un UUID valido.

    Si llegara algo que no lo es, insertarlo en una columna UUID reventaria, el
    consumidor haria negative_acknowledge y Pulsar lo reentregaria para siempre:
    un mensaje venenoso en bucle. Se deriva un UUID determinista del texto, que
    conserva la idempotencia -el mismo id da siempre el mismo UUID- sin dejar
    caer el mensaje.
    """
    import uuid
    try:
        return str(uuid.UUID(valor))
    except (ValueError, AttributeError, TypeError):
        return str(uuid.uuid5(uuid.NAMESPACE_OID, str(valor)))
