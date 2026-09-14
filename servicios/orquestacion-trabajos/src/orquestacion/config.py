"""Lectura del entorno. Un solo lugar, para que ningun modulo llame a os.getenv.

Los nombres de variable NO son inventados: son los que el docker-compose de la
raiz ya le pasa a este contenedor. El servicio se adapta a la infraestructura
que el grupo ya tiene montada, no al reves.
"""
import os
from pathlib import Path

SERVICE_NAME = os.getenv("SERVICE_NAME", "orquestacion-trabajos")

# ─────────────────────────────────────────────────────────────── contratos ──
# En el contenedor, el compose monta ./contratos como /app/contratos:ro y fija
# CONTRATOS_DIR. Corriendo en local no hay variable y hay que encontrarla sola.
#
# Se BUSCA HACIA ARRIBA en vez de contar niveles con parents[N]: el paquete
# cuelga de una profundidad distinta en cada sitio -en el repo esta bajo
# servicios/orquestacion-trabajos/src/, en la imagen bajo /app/src/- y un indice
# fijo revienta con IndexError en uno de los dos. Buscar la carpeta funciona en
# los dos sin saber cual es cual.
def _contratos_por_defecto() -> Path:
    for padre in Path(__file__).resolve().parents:
        candidato = padre / "contratos"
        if (candidato / "esquemas").is_dir():
            return candidato
    return Path("/app/contratos")


# Nota: `os.getenv(clave, default)` evalua el default SIEMPRE, aunque la
# variable exista. Por eso se consulta primero y se calcula despues.
_contratos_env = os.getenv("CONTRATOS_DIR")
CONTRATOS_DIR = Path(_contratos_env) if _contratos_env else _contratos_por_defecto()

# ────────────────────────────────────────────────────────────────── Pulsar ──
# El compose fija PULSAR_URL; PULSAR_ADDRESS es la forma que usan los otros
# servicios del grupo. Se aceptan las dos para no depender de cual llegue.
def broker_url() -> str:
    url = os.getenv("PULSAR_URL")
    if url:
        return url
    return f"pulsar://{os.getenv('PULSAR_ADDRESS', 'localhost')}:6650"


# ─────────────────────────────────────────────── listener de Pulsar ─────────
# El broker puede anunciar VARIAS direcciones para el mismo topico, una por
# "listener". Hace falta porque la direccion util depende de donde este el
# cliente:
#
#   internal -> broker:6650      los microservicios, dentro de la red de Docker
#   external -> 127.0.0.1:6650   los scripts, corriendo en el host
#
# Un cliente que no pide listener recibe el interno, que es lo correcto para los
# servicios. Los scripts del host exportan PULSAR_LISTENER=external.
#
# Sin esto, un servicio en un contenedor recibe "conectate a 127.0.0.1" y muere
# con Connection refused, porque en SU contenedor esa direccion no es el broker.
def listener() -> str | None:
    return os.getenv("PULSAR_LISTENER") or None


def opciones_cliente() -> dict:
    """kwargs extra para pulsar.Client. Vacio si no hay listener configurado."""
    nombre = listener()
    return {"listener_name": nombre} if nombre else {}


# ────────────────────────────────────────────────────────────── PostgreSQL ──
def dsn() -> str:
    """DSN en formato libpq, que es lo que entiende psycopg3.

    OJO: el compose expone DATABASE_DSN como `postgresql+psycopg://...`. Ese
    `+psycopg` es sintaxis de SQLAlchemy y libpq no la entiende, asi que hay
    que quitarlo. Es exactamente el tipo de detalle que aparece al no usar ORM
    en un compose escrito pensando en uno.
    """
    crudo = os.getenv("DATABASE_DSN")
    if crudo:
        return crudo.replace("postgresql+psycopg://", "postgresql://", 1)
    usuario = os.getenv("DB_USERNAME", "trabajos")
    clave = os.getenv("DB_PASSWORD", "trabajos")
    host = os.getenv("DB_HOSTNAME", "localhost")
    puerto = os.getenv("DB_PORT", "5432")
    nombre = os.getenv("DB_NAME", "trabajos")
    return f"postgresql://{usuario}:{clave}@{host}:{puerto}/{nombre}"


# ───────────────────────────────────────────────────────────────── ajustes ──
MAX_INTENTOS_ASIGNACION = int(os.getenv("MAX_INTENTOS_ASIGNACION", "3"))
BARRIDO_SLA_SEGUNDOS = float(os.getenv("BARRIDO_SLA_SEGUNDOS", "30"))
RELAY_OUTBOX_SEGUNDOS = float(os.getenv("RELAY_OUTBOX_SEGUNDOS", "1"))

# El contenedor siempre expone 5000 y el compose lo mapea a 5001 afuera. En
# macOS el 5000 lo suele tener AirPlay, asi que corriendo en local hace falta
# poder moverlo.
PUERTO_API = int(os.getenv("PUERTO_API", "5000"))
