"""Infraestructura de pruebas.

Las pruebas que tocan PostgreSQL se saltan solas si no hay base disponible, para
que `pytest tests` siga sirviendo en una maquina sin Docker. Las de la costura
(test_contratos.py) no necesitan nada.

  docker run -d --name orq-test-pg -e POSTGRES_DB=trabajos \
    -e POSTGRES_USER=trabajos -e POSTGRES_PASSWORD=trabajos \
    -p 55432:5432 postgres:16-alpine

  export DATABASE_DSN=postgresql://trabajos:trabajos@localhost:55432/trabajos
"""
import os

import pytest

os.environ.setdefault(
    "DATABASE_DSN", "postgresql://trabajos:trabajos@localhost:55432/trabajos"
)


@pytest.fixture(scope="session")
def base():
    """Aplica el esquema una vez por corrida."""
    psycopg = pytest.importorskip("psycopg")
    from orquestacion.infraestructura.persistencia import bd

    try:
        bd.aplicar_esquema()
    except Exception as exc:
        pytest.skip(f"sin PostgreSQL de pruebas: {exc}")
    yield bd
    bd.cerrar()


@pytest.fixture
def limpia(base):
    """Cada prueba arranca con las tablas vacias.

    TRUNCATE y no DROP: el esquema se aplica una sola vez y las pruebas no
    dependen del orden en que corran.
    """
    with base.pool().connection() as con:
        con.execute("TRUNCATE saga_paso, saga_asignacion, eventos_trabajo, outbox, "
                    "proyeccion_regla_partner, proyeccion_trabajo, mensajes_procesados")
    return base
