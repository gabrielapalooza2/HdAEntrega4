from __future__ import annotations

import logging
import time

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from infraestructura.persistencia.modelos import Base

log = logging.getLogger("emparejamiento.db")


def crear_engine(dsn: str):
    return create_engine(
        dsn,
        pool_pre_ping=True,
        future=True,
        connect_args={"connect_timeout": 5},
    )


def crear_session_factory(engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def esperar_db(engine, intentos: int = 30, pausa: float = 2.0) -> None:
    ultimo = None
    for i in range(intentos):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            log.info("base de datos lista")
            return
        except Exception as exc:
            ultimo = exc
            log.warning("esperando DB (%s/%s): %s", i + 1, intentos, exc)
            time.sleep(pausa)
    raise RuntimeError(f"DB no disponible: {ultimo}")


def crear_tablas(engine) -> None:
    Base.metadata.create_all(engine)
