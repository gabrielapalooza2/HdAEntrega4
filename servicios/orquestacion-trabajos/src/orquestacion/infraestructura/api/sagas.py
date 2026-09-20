"""Consulta del saga log. Solo lectura, para un operador o un tutor.

No es BFF ni CSaaS. No dispara la saga. El estado se mira tambien con SQL
sobre saga_asignacion y saga_paso; estas rutas evitan copiar PGPASSWORD.
"""
from flask import Blueprint, jsonify, request

from orquestacion.infraestructura.persistencia import bd, saga_log

bp = Blueprint("sagas", __name__)


@bp.get("/sagas")
def listar():
    estado = request.args.get("estado")
    with bd.pool().connection() as con, con.cursor() as cur:
        filas = saga_log.listar(cur, estado=estado)
    return jsonify({"sagas": filas})


@bp.get("/sagas/<saga_id>")
def detalle(saga_id: str):
    with bd.pool().connection() as con, con.cursor() as cur:
        vista = saga_log.obtener(cur, saga_id)
    if vista is None:
        return jsonify({"error": "saga desconocida", "saga_id": saga_id}), 404
    return jsonify(vista)
