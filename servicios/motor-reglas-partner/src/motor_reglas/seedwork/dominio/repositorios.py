"""Interfaces de repositorio.

INVERSIÓN DE DEPENDENCIAS: el dominio declara la interfaz que necesita y la
infraestructura la implementa. El dominio no importa SQLAlchemy ni Pulsar; es la
infraestructura la que depende del dominio, nunca al revés. Esa flecha es la
arquitectura cebolla.
"""

from abc import ABC, abstractmethod
from uuid import UUID

from .entidades import Entidad


class Repositorio(ABC):
    @abstractmethod
    def obtener_por_id(self, id: UUID) -> Entidad:
        ...

    @abstractmethod
    def obtener_todos(self) -> list[Entidad]:
        ...

    @abstractmethod
    def agregar(self, entidad: Entidad):
        ...

    @abstractmethod
    def actualizar(self, entidad: Entidad):
        ...


class Mapeador(ABC):
    """Traduce entre el modelo de dominio y una representación externa (DTO, evento)."""

    @abstractmethod
    def obtener_tipo(self) -> type:
        ...

    @abstractmethod
    def entidad_a_dto(self, entidad: Entidad):
        ...

    @abstractmethod
    def dto_a_entidad(self, dto):
        ...
