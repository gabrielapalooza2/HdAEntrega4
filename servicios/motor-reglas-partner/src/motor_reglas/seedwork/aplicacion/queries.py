"""Lado de LECTURA de CQRS.

Las consultas no pasan por el modelo de dominio: van directo al DTO. Un agregado
existe para proteger invariantes al escribir; al leer, esa protección es puro costo.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import singledispatch
from typing import Any


class Query(ABC):
    ...


@dataclass
class QueryResultado:
    resultado: Any


class QueryHandler(ABC):
    @abstractmethod
    def handle(self, query: Query) -> QueryResultado:
        raise NotImplementedError()


@singledispatch
def ejecutar_query(query):
    raise NotImplementedError(
        f"No existe implementación para el query de tipo {type(query).__name__}"
    )
