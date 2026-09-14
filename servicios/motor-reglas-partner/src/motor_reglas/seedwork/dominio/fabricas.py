"""Fábricas.

Encapsulan el ensamblado de una agregación compleja para que ni la capa de
aplicación ni la de infraestructura conozcan cómo se arma por dentro.
"""

from abc import ABC, abstractmethod

from .repositorios import Mapeador


class Fabrica(ABC):
    @abstractmethod
    def crear_objeto(self, obj, mapeador: Mapeador):
        ...
