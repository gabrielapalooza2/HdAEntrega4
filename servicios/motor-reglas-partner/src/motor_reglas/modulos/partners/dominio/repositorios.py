"""Interfaces de repositorio del módulo de partners.

Las declara el DOMINIO. La implementación con SQLAlchemy vive en infraestructura
y depende de esta interfaz, no al revés.
"""

from abc import ABC
from uuid import UUID

from motor_reglas.seedwork.dominio.repositorios import Repositorio


class RepositorioPartners(Repositorio, ABC):
    def obtener_por_id(self, id: UUID):
        ...


class RepositorioMercados(Repositorio, ABC):
    ...
