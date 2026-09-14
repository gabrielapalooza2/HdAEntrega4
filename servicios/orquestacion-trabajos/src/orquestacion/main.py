"""Punto de entrada. Arranca la API y los hilos de fondo.

  gunicorn orquestacion.main:app     (contenedor)
  python -m orquestacion.main        (local)

Los consumidores, el relay del outbox y el barrido de SLA son HILOS de este
mismo proceso, no contenedores aparte. En produccion irian separados para poder
reiniciar el consumo sin tumbar la API; para una prueba de concepto un hilo
alcanza y evita tres contenedores mas. Por eso el Dockerfile fija un solo worker
de gunicorn: con varios habria un relay por worker peleandose las mismas filas
del outbox.
"""
import atexit
import logging
import threading

from flask import Flask

from orquestacion import config
from orquestacion.infraestructura import barrido
from orquestacion.infraestructura.api import trabajos as api_trabajos
from orquestacion.infraestructura.mensajeria import consumidores, publicador
from orquestacion.infraestructura.persistencia import bd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s [%(threadName)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_parar = threading.Event()


def create_app() -> Flask:
    app = Flask(__name__)

    bd.aplicar_esquema()

    # Tres clases de hilo, tres razones distintas:
    #   consumidores  reaccionan a mensajes
    #   relay         saca lo encolado hacia el broker
    #   barrido       reacciona al PASO DEL TIEMPO, que ningun mensaje reporta
    consumidores.arrancar(_parar)
    publicador.arrancar(_parar)
    barrido.arrancar(_parar)

    app.register_blueprint(api_trabajos.bp)

    @app.get("/health")
    def health():
        return {"estado": "vivo", "servicio": "orquestacion-trabajos"}

    atexit.register(_apagar)
    return app


def _apagar() -> None:
    _parar.set()
    bd.cerrar()


app = create_app()

if __name__ == "__main__":
    # use_reloader=False: con el recargador, Flask arranca DOS procesos y
    # tendriamos dos juegos de consumidores compitiendo por la misma suscripcion.
    app.run(host="0.0.0.0", port=config.PUERTO_API, use_reloader=False)
