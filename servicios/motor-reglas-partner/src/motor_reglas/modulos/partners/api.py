"""Adaptador de entrada HTTP.

ACLARACIÓN IMPORTANTE PARA LA SUSTENTACIÓN: esta API NO es comunicación entre
servicios. Ningún microservicio llama a estos endpoints; el enunciado lo prohíbe
expresamente. Existe para dos cosas: que un operador humano registre un partner
durante la demostración, y que el BFF de la entrega 5 tenga dónde conectarse.

Toda comunicación entre servicios pasa por los tópicos de Apache Pulsar.
"""

import uuid
from datetime import datetime

from flask import Blueprint, jsonify, request

from motor_reglas.seedwork.aplicacion.comandos import ejecutar_comando
from motor_reglas.seedwork.aplicacion.queries import ejecutar_query

from .aplicacion.comandos.actualizar_regla import ActualizarReglaDePartner
from .aplicacion.comandos.registrar_partner import RegistrarPartner
from .aplicacion.queries.obtener_partner import ObtenerPartner, ObtenerPartners
from .dominio.excepciones import PartnerIdInvalido, PartnerNoExiste

bp = Blueprint("partners", __name__, url_prefix="/partners")


def _fecha(valor, por_defecto=None):
    if not valor:
        return por_defecto
    return datetime.fromisoformat(valor.replace("Z", "+00:00")).replace(tzinfo=None)


@bp.route("", methods=["POST"])
def registrar_partner():
    """Registra un partner con su convenio y su regla. Devuelve 202: el efecto
    sobre los demás servicios es asíncrono y llega por el bus."""
    cuerpo = request.json
    regla = cuerpo.get("regla", {})
    monto = regla.get("monto_maximo_sin_aprobacion", {})

    comando = RegistrarPartner(
        partner_id=cuerpo.get("id"),
        nombre=cuerpo["nombre"],
        tipo_partner=cuerpo["tipo_partner"],
        convenio_numero=cuerpo["convenio_numero"],
        vigencia_desde=_fecha(cuerpo.get("vigencia_desde"), datetime.utcnow()),
        vigencia_hasta=_fecha(cuerpo.get("vigencia_hasta")),
        porcentaje_comision=cuerpo.get("porcentaje_comision", 0.0),
        moneda_tarifa=cuerpo.get("moneda_tarifa", "COP"),
        cobertura_contratada=regla["cobertura_contratada"],
        sla_minutos=regla["sla_minutos"],
        monto_maximo_monto=monto.get("monto", 0),
        monto_maximo_moneda=monto.get("moneda", "COP"),
        pasos_de_aprobacion=regla.get("pasos_de_aprobacion", []),
        red_homologada=regla.get("red_homologada", []),
        correlation_id=request.headers.get("X-Correlation-Id", str(uuid.uuid4())),
    )
    partner_id = ejecutar_comando(comando)
    return jsonify({"id": partner_id, "estado": "registrado"}), 202


@bp.route("/<partner_id>/regla", methods=["PUT"])
def actualizar_regla(partner_id):
    cuerpo = request.json
    monto = cuerpo.get("monto_maximo_sin_aprobacion", {})
    comando = ActualizarReglaDePartner(
        partner_id=partner_id,
        cobertura_contratada=cuerpo["cobertura_contratada"],
        sla_minutos=cuerpo["sla_minutos"],
        monto_maximo_monto=monto.get("monto", 0),
        monto_maximo_moneda=monto.get("moneda", "COP"),
        pasos_de_aprobacion=cuerpo.get("pasos_de_aprobacion", []),
        red_homologada=cuerpo.get("red_homologada", []),
        correlation_id=request.headers.get("X-Correlation-Id", str(uuid.uuid4())),
    )
    try:
        version = ejecutar_comando(comando)
    except PartnerIdInvalido as e:
        return jsonify({"error": str(e)}), 400
    except PartnerNoExiste as e:
        return jsonify({"error": str(e)}), 404
    return jsonify({"id": partner_id, "version_regla": version}), 202


@bp.route("/<partner_id>", methods=["GET"])
def obtener_partner(partner_id):
    resultado = ejecutar_query(ObtenerPartner(id=partner_id)).resultado
    if resultado is None:
        return jsonify({"error": "no existe"}), 404
    return jsonify(resultado), 200


@bp.route("", methods=["GET"])
def obtener_partners():
    solo_activos = request.args.get("activos", "false").lower() == "true"
    return jsonify(ejecutar_query(ObtenerPartners(solo_activos=solo_activos)).resultado), 200
