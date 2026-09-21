"""BFF de Hogar de los Alpes.

Backend For Frontend: una unica puerta de entrada al sistema, que le ofrece al
cliente un modelo comodo y sincrono mientras por dentro todo sigue siendo
asincrono y por eventos.

LO QUE EL BFF NO ES
-------------------
No es un API Gateway: no enruta peticiones hacia servicios. No es un
orquestador: no decide el orden de los pasos de negocio. No es un servicio de
dominio: no posee ninguna agregacion ni aplica reglas de negocio.

LO QUE SI HACE
--------------
  1. Traduce peticiones HTTP en comandos publicados en Apache Pulsar.
  2. Mantiene una proyeccion de lectura alimentada por los eventos del bus.
  3. Compone en una sola respuesta datos que viven en servicios distintos.
  4. Expone el estado de cada operacion asincrona como un recurso consultable.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import config
from .infraestructura import proyeccion as mod_proyeccion
from .infraestructura.publicador import publicador
from .rutas import comandos, consultas

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("bff")

_estado: dict = {}


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    """Conecta a Pulsar al arrancar y suelta los recursos al terminar."""
    if config.CONECTAR_A_PULSAR:
        publicador.conectar()
        hilos, parar = mod_proyeccion.iniciar_consumidores(publicador._cliente)
        _estado["hilos"], _estado["parar"] = hilos, parar
        log.info("BFF listo: %d consumidores de proyeccion", len(hilos))
    else:
        log.warning("CONECTAR_A_PULSAR=false: sin productores ni consumidores")
    yield
    if _estado.get("parar"):
        _estado["parar"].set()
        for h in _estado.get("hilos", []):
            h.join(timeout=5)
    publicador.cerrar()


app = FastAPI(
    title="Hogar de los Alpes — BFF",
    version="1.0.0",
    lifespan=ciclo_de_vida,
    description=(
        "Puerta de entrada unica al sistema.\n\n"
        "**Las escrituras devuelven 202**, no 200: el BFF publica un comando en "
        "Apache Pulsar y responde con un `correlation_id`. El desenlace se "
        "consulta en `GET /operaciones/{correlation_id}`.\n\n"
        "**Las lecturas salen de una proyeccion local** construida con los "
        "eventos del bus, no de llamadas a los microservicios. Por eso siguen "
        "respondiendo aunque un servicio este caido."
    ),
)

app.include_router(comandos.router)
app.include_router(consultas.router)


@app.get("/health", tags=["Operacion"], summary="Sonda de vida")
def health():
    return {
        "servicio": config.SERVICE_NAME,
        "estado": "ok",
        "pulsar": config.PULSAR_URL if config.CONECTAR_A_PULSAR else "desconectado",
        "proyeccion": mod_proyeccion.proyeccion.estadisticas(),
    }
