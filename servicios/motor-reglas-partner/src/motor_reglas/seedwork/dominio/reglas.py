from abc import ABC, abstractmethod


class ReglaNegocio(ABC):
    __mensaje: str = "La regla de negocio no se cumple"

    def __init__(self, mensaje: str | None = None):
        if mensaje:
            self.__mensaje = mensaje

    def mensaje_error(self) -> str:
        return self.__mensaje

    @abstractmethod
    def es_valido(self) -> bool:
        ...

    def __str__(self) -> str:
        return f"{self.__class__.__name__} - {self.__mensaje}"


class IdEntidadEsInmutable(ReglaNegocio):
    def __init__(self, entidad, mensaje="El identificador de la entidad debe ser inmutable"):
        super().__init__(mensaje)
        self.entidad = entidad

    def es_valido(self) -> bool:
        return not hasattr(self.entidad, "_id") or self.entidad._id is None
