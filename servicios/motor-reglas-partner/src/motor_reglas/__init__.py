"""Fábrica de la aplicación Flask del microservicio Motor reglas partner."""

import logging
import os
import threading

from flask import Flask, jsonify


def _registrar_handlers():
    """Importa los módulos que registran handlers en `singledispatch`.

    Sin este import los decoradores @ejecutar_comando.register nunca corren y el
    despacho falla en tiempo de ejecución con "no existe implementación".
    """
    import motor_reglas.modulos.partners.aplicacion.comandos.actualizar_regla  # noqa: F401
    import motor_reglas.modulos.partners.aplicacion.comandos.registrar_partner  # noqa: F401
    import motor_reglas.modulos.partners.aplicacion.queries.obtener_partner  # noqa: F401


def _importar_modelos():
    import motor_reglas.modulos.partners.infraestructura.dto  # noqa: F401


def create_app(configuracion=None):
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    app = Flask(__name__, instance_relative_config=True)

    from motor_reglas.config.db import database_connection, db, init_db

    configuracion = configuracion or {}
    app.config["SQLALCHEMY_DATABASE_URI"] = database_connection(configuracion)
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["TESTING"] = configuracion.get("TESTING", False)

    init_db(app)
    _importar_modelos()
    _registrar_handlers()

    with app.app_context():
        db.create_all()

    from motor_reglas.modulos.partners.api import bp
    app.register_blueprint(bp)

    @app.route("/health")
    def health():
        return jsonify({"servicio": "motor-reglas-partner", "estado": "ok"}), 200

    if not app.config["TESTING"] and os.getenv("INICIAR_WORKERS", "true").lower() == "true":
        _iniciar_workers(app)

    return app


def _iniciar_workers(app):
    """Lanza el relay del outbox y el consumidor de comandos en hilos demonio.

    En producción serían procesos aparte para poder escalarlos por separado; para
    la prueba de concepto van en hilos y así el servicio es un solo contenedor.
    """
    from motor_reglas.modulos.partners.infraestructura.consumidores import suscribirse_a_comandos
    from motor_reglas.modulos.partners.infraestructura.consumidores_saga import suscribirse_a_trabajos
    from motor_reglas.modulos.partners.infraestructura.outbox import iniciar_relay

    threading.Thread(target=iniciar_relay, args=(app,), daemon=True, name="outbox-relay").start()
    threading.Thread(target=suscribirse_a_comandos, args=(app,), daemon=True, name="consumidor-comandos").start()
    threading.Thread(target=suscribirse_a_trabajos, args=(app,), daemon=True, name="consumidor-saga").start()
