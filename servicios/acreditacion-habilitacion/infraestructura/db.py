"""Motor de base de datos de este servicio.

psycopg v3 (driver 'postgresql+psycopg', NO psycopg2) -- asi lo fija el
DATABASE_DSN del docker-compose.yml del equipo. DATABASE_DSN se lee
completo desde el entorno; si no esta, se cae a SQLite solo para poder
correr pruebas unitarias sin Postgres levantado (nunca para el servicio
real desplegado).
"""
from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, scoped_session, sessionmaker

Base = declarative_base()

DATABASE_DSN = os.getenv("DATABASE_DSN", "sqlite:///acreditacion_test.db")

engine = create_engine(
    DATABASE_DSN,
    echo=False,
    future=True,
    connect_args={"check_same_thread": False} if DATABASE_DSN.startswith("sqlite") else {},
)

SessionFactory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
Session = scoped_session(SessionFactory)


def crear_tablas():
    from . import dto  # noqa: F401 -- registra los modelos en Base.metadata
    Base.metadata.create_all(engine)
