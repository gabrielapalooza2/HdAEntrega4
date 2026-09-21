"""Consulta del saga log. Solo lectura, para un operador o un tutor.

Orquestacion de trabajos es el COORDINADOR DE SAGAS: dueño de saga_asignacion,
saga_paso y trabajo_id. No es BFF ni CSaaS. No dispara la saga ni manda
comandos a los otros tres participantes. El estado se mira tambien con SQL;
estas rutas evitan copiar PGPASSWORD.
"""
from flask import Blueprint, jsonify, request

from orquestacion.infraestructura.persistencia import bd, saga_log

bp = Blueprint("sagas", __name__)


@bp.get("/sagas")
def listar():
    estado = request.args.get("estado")
    with bd.pool().connection() as con, con.cursor() as cur:
        filas = saga_log.listar(cur, estado=estado)
    return jsonify({
        "coordinador": saga_log.SERVICIO_COORDINADOR,
        "sagas": filas,
    })


@bp.get("/sagas/<saga_id>")
def detalle(saga_id: str):
    with bd.pool().connection() as con, con.cursor() as cur:
        vista = saga_log.obtener(cur, saga_id)
    if vista is None:
        return jsonify({"error": "saga desconocida", "saga_id": saga_id}), 404
    return jsonify(vista)
