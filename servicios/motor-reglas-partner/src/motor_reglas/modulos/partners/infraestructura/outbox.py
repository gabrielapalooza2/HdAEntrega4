"""Outbox y su relay.

El outbox resuelve la atomicidad entre la base de datos y el broker. El relay es
el proceso que drena la tabla hacia Pulsar.

Garantía que da: AL MENOS UNA VEZ. Si el relay publica y se cae antes de marcar la
fila, el evento se republica al reiniciar. Por eso todo consumidor debe ser
idempotente — y por eso existe la tabla `mensajes_procesados`.
"""

import json
import logging
import time
import uuid
from datetime import datetime

from motor_reglas.config.db import db
from motor_reglas.seedwork.infraestructura.utils import time_millis

from .dto import Outbox

logger = logging.getLogger(__name__)

TOPICO_EVENTOS_PARTNER = "persistent://hda/poc/eventos-partner"


def registrar_en_outbox(tipo: str, clave: str, payload: dict, correlation_id: str,
                        topico: str = TOPICO_EVENTOS_PARTNER):
    """Se llama DENTRO de la transacción de dominio, antes del commit.

    No publica nada: solo deja la fila. El commit de la transacción es lo que hace
    que el evento exista, y por eso no puede haber un evento que describa un cambio
    que no ocurrió.
    """
    db.session.add(
        Outbox(
            id=str(uuid.uuid4()),
            tipo=tipo,
            topico=topico,
            clave=clave,
            payload=payload,
            correlation_id=correlation_id,
            publicado=False,
            fecha_creacion=datetime.utcnow(),
        )
    )


def drenar_outbox(despachador, limite: int = 100) -> int:
    """Publica lo pendiente y marca las filas. Devuelve cuántos eventos publicó."""
    pendientes = (
        db.session.query(Outbox)
        .filter_by(publicado=False)
        .order_by(Outbox.fecha_creacion)
        .limit(limite)
        .all()
    )

    publicados = 0
    for fila in pendientes:
        try:
            despachador.publicar_evento_regla(
                payload=fila.payload,
                clave=fila.clave,
                correlation_id=fila.correlation_id,
                topico=fila.topico,
            )
            fila.publicado = True
            fila.fecha_publicacion = datetime.utcnow()
            publicados += 1
        except Exception:
            logger.exception("No se pudo publicar el evento %s; se reintenta luego", fila.id)
            break  # preserva el orden: no salta al siguiente

    if publicados:
        db.session.commit()
    return publicados


def iniciar_relay(app, intervalo_segundos: float = 1.0):
    """Bucle del relay. Se lanza en un hilo aparte desde `create_app`.

    En producción esto sería un proceso independiente y no un hilo, para poder
    escalarlo y reiniciarlo sin tocar la API. Para la prueba de concepto un hilo
    alcanza y evita un contenedor más.
    """
    from .despachadores import Despachador

    despachador = Despachador()
    while True:
        try:
            with app.app_context():
                drenar_outbox(despachador)
        except Exception:
            logger.exception("Error en el relay del outbox")
        time.sleep(intervalo_segundos)
