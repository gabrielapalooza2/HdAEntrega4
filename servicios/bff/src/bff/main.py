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
