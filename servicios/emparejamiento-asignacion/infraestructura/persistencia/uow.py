from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from infraestructura.persistencia.repositorios import (
    RepositorioAsignacionesFallidasSql,
    RepositorioAsignacionesSql,
    RepositorioEventosProcesadosSql,
    RepositorioProyeccionHabilitacionSql,
    RepositorioProyeccionReglaSql,
)


class SqlAlchemyUoW:
    def __init__(self, session_factory: sessionmaker) -> None:
        self._session: Session = session_factory()
        self.asignaciones = RepositorioAsignacionesSql(self._session)
        self.reglas = RepositorioProyeccionReglaSql(self._session)
        self.habilitaciones = RepositorioProyeccionHabilitacionSql(self._session)
        self.eventos_procesados = RepositorioEventosProcesadosSql(self._session)
        self.fallidas = RepositorioAsignacionesFallidasSql(self._session)

    def commit(self) -> None:
        try:
            self._session.commit()
        finally:
            self._session.close()

    def rollback(self) -> None:
        try:
            self._session.rollback()
        finally:
            self._session.close()
