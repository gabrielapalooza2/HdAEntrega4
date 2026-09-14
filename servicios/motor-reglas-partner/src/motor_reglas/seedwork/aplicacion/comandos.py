"""Lado de ESCRITURA de CQRS.

Un comando expresa una intención que puede ser rechazada. Se despacha con
`singledispatch`, así que registrar un comando nuevo no obliga a modificar
ningún `if` existente: es el principio abierto/cerrado aplicado al bus interno.
"""

from abc import ABC, abstractmethod
from functools import singledispatch


class Comando:
    ...


class ComandoHandler(ABC):
    @abstractmethod
    def handle(self, comando: Comando):
        raise NotImplementedError()


@singledispatch
def ejecutar_comando(comando):
    raise NotImplementedError(
        f"No existe implementación para el comando de tipo {type(comando).__name__}"
    )
