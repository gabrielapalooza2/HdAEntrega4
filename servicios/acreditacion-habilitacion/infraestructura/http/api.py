"""Entrypoint del servicio: Flask + arranque de consumidores en background.

Es el modulo que referencia el Dockerfile: gunicorn ... infraestructura.http.api:app
Al importarse (una sola vez, cuando gunicorn carga el modulo) se crean las
tablas, se arrancan los consumidores de Pulsar como threads daemon, y se
registran las rutas -- todo en el mismo proceso, un solo contenedor.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from flask import Flask, jsonify, request

from dominio.excepciones import ExcepcionDominio, ProveedorNoExiste
from infraestructura.db import Session, crear_tablas
from infraestructura.repositorios import RepositorioProveedoresSQLAlchemy
from infraestructura.verificacion_externa import VerificacionNoDisponible, toggle_falla_policia_nacional

from aplicacion.comandos import acreditar_proveedor, suspender_proveedor, verificar_antecedentes
from mensajeria import consumidores
from mensajeria.cliente import Publicador, crear_cliente

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# --- arranque: se ejecuta una sola vez al importar el modulo
crear_tablas()
_cliente_publicador = crear_cliente()
_publicador = Publicador(_cliente_publicador)
consumidores.iniciar_en_background()
logger.info("Acreditacion y Habilitacion: tablas listas, consumidores arrancados.")


def _epoch_millis_a_dt(valor):
    if valor is None:
        return None
    return datetime.fromtimestamp(valor / 1000, tz=timezone.utc)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "acreditacion-habilitacion"}), 200


@app.route("/proveedores", methods=["POST"])
def acreditar():
    """Uso administrativo/pruebas. El camino normal es cmd.proveedores."""
    datos = request.json or {}
    session = Session()
    try:
        comando = acreditar_proveedor.AcreditarProveedor(
            proveedor_id=datos.get("proveedor_id"), nombre=datos.get("nombre", ""),
            categorias=datos.get("categorias", []), ciudades=datos.get("ciudades", []),
            vigente_hasta=_epoch_millis_a_dt(datos.get("vigente_hasta")),
            tipo_proveedor=datos.get("tipo_proveedor", "PERSONA_NATURAL"),
        )
        repositorio = RepositorioProveedoresSQLAlchemy(session)
        correlation_id = request.headers.get("X-Correlation-Id", "http-admin")
        dto = acreditar_proveedor.ejecutar(comando, repositorio, session,
                                            lambda ev: _publicador.publicar(ev, correlation_id))
        return jsonify(dto.a_externo()), 201
    finally:
        session.close()


@app.route("/proveedores/<proveedor_id>/suspender", methods=["PATCH"])
def suspender(proveedor_id):
    datos = request.json or {}
    session = Session()
    try:
        comando = suspender_proveedor.SuspenderProveedor(proveedor_id=proveedor_id, motivo=datos.get("motivo", ""))
        repositorio = RepositorioProveedoresSQLAlchemy(session)
        correlation_id = request.headers.get("X-Correlation-Id", "http-admin")
        dto = suspender_proveedor.ejecutar(comando, repositorio, session,
                                            lambda ev: _publicador.publicar(ev, correlation_id))
        return jsonify(dto.a_externo()), 200
    finally:
        session.close()


@app.route("/proveedores/<proveedor_id>/habilitacion", methods=["GET"])
def obtener_habilitacion(proveedor_id):
    """Excepcion sincrona de back-office. Ningun otro microservicio la llama."""
    session = Session()
    try:
        repositorio = RepositorioProveedoresSQLAlchemy(session)
        proveedor = repositorio.obtener_por_id(proveedor_id)
        if proveedor is None:
            raise ProveedorNoExiste(proveedor_id)
        from aplicacion.dto import ProveedorDTO
        return jsonify(ProveedorDTO.desde_entidad(proveedor).a_externo()), 200
    finally:
        session.close()


@app.route("/proveedores/<proveedor_id>/verificar-antecedentes", methods=["POST"])
def verificar_antecedentes_endpoint(proveedor_id):
    """Demo en vivo del escenario 8: circuit breaker + cache."""
    datos = request.json or {}
    fuente = datos.get("fuente", "policia_nacional")
    session = Session()
    try:
        inicio = datetime.now(timezone.utc)
        comando = verificar_antecedentes.VerificarAntecedentes(proveedor_id=proveedor_id, fuente=fuente)
        resultado = verificar_antecedentes.ejecutar(comando, session)
        latencia_ms = (datetime.now(timezone.utc) - inicio).total_seconds() * 1000
        return jsonify({
            "proveedor_id": proveedor_id, "fuente": resultado.fuente, "aprobado": resultado.aprobado,
            "motivo": resultado.motivo, "desde_cache": resultado.desde_cache,
            "verificado_en": resultado.verificado_en.isoformat(), "latencia_ms": round(latencia_ms, 1),
        }), 200
    finally:
        session.close()


@app.route("/admin/simular-falla-policia", methods=["POST"])
def simular_falla_policia():
    datos = request.json or {}
    activa = bool(datos.get("activa", True))
    toggle_falla_policia_nacional(activa)
    return jsonify({"falla_policia_nacional_activa": activa}), 200


@app.errorhandler(ProveedorNoExiste)
def _no_existe(error):
    return jsonify({"error": str(error)}), 404


@app.errorhandler(VerificacionNoDisponible)
def _verificacion_no_disponible(error):
    return jsonify({"error": str(error)}), 503


@app.errorhandler(ExcepcionDominio)
def _dominio(error):
    return jsonify({"error": str(error)}), 409


@app.errorhandler(ValueError)
def _valor(error):
    return jsonify({"error": str(error)}), 400
