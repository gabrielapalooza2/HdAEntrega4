"""API HTTP. La UNICA excepcion sincrona permitida en todo el sistema.

Es sincrona hacia AFUERA -un operador o un BFF preguntan por un trabajo- pero
nunca hacia adentro: ningun endpoint de aqui llama a otro microservicio.
"""
import logging

from flask import Blueprint, jsonify

from orquestacion.infraestructura.persistencia import bd, trabajos

logger = logging.getLogger(__name__)

bp = Blueprint("trabajos", __name__)


@bp.get("/trabajos/<trabajo_id>/estado")
def estado(trabajo_id: str):
    """Lee SOLO la proyeccion. Es el lado Q de CQRS.

    No abre transaccion sobre el agregado ni toca el event store: una consulta a
    una tabla con PK, sin reproducir eventos. Ese es el punto de tener una
    proyeccion.
    """
    with bd.pool().connection() as con, con.cursor() as cur:
        vista = trabajos.buscar(cur, trabajo_id)

    if vista is None:
        return jsonify({"error": "trabajo desconocido", "trabajo_id": trabajo_id}), 404

    cuerpo = {
        "trabajo_id": vista.trabajo_id,
        "estado": vista.estado,
        "partner_id": vista.partner_id,
        "proveedor_id": vista.proveedor_id,
        "categoria": vista.categoria,
        "zona": vista.zona,
        "sla_minutos": vista.sla_minutos,
        "vence_en": vista.vence_en.isoformat() if vista.vence_en else None,
        "intentos": vista.intentos,
        "proveedores_excluidos": list(vista.proveedores_excluidos),
        "actualizado_en": vista.actualizado_en.isoformat(),
    }

    respuesta = jsonify(cuerpo)
    # ─── EL REZAGO, VISIBLE ───────────────────────────────────────────────
    # En CQRS la proyeccion va SIEMPRE por detras del event store, aunque sea
    # por milisegundos. Exponer hasta que evento refleja esta respuesta hace que
    # ese rezago sea observable en vez de estar escondido: quien consulta puede
    # saber si esta viendo un estado viejo.
    # ───────────────────────────────────────────────────────────────────────
    respuesta.headers["X-Proyeccion-Secuencia"] = str(vista.secuencia)
    return respuesta
