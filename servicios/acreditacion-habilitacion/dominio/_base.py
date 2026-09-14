"""Piezas base del dominio, propias de ESTE servicio.

No es un paquete compartido entre microservicios (eso ya no existe en el
repo nuevo) -- es simplemente la porcion minima de tactica DDD que
Acreditacion necesita, vive dentro de su propio dominio/ y no importa
Flask, psycopg ni pulsar (misma regla que sigue Orquestacion).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid


def ahora() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Entidad:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    fecha_creacion: datetime = field(default_factory=ahora)
    fecha_actualizacion: datetime = field(default_factory=ahora)

    def __eq__(self, other) -> bool:
        if not isinstance(other, Entidad):
            return NotImplemented
        return self.id == other.id

    def __hash__(self):
        return hash(self.id)

    def tocar(self):
        self.fecha_actualizacion = ahora()


@dataclass
class AgregacionRaiz(Entidad):
    eventos: list = field(default_factory=list)

    def agregar_evento(self, evento):
        self.eventos.append(evento)

    def limpiar_eventos(self):
        self.eventos = []

    def obtener_eventos(self) -> list:
        return list(self.eventos)


class ReglaNegocio(ABC):
    def __init__(self, mensaje: str):
        self._mensaje = mensaje

    def mensaje(self) -> str:
        return self._mensaje

    @abstractmethod
    def es_valido(self) -> bool:
        ...


class ExcepcionDominio(Exception):
    ...


class ExcepcionReglaDeNegocio(ExcepcionDominio):
    def __init__(self, regla: ReglaNegocio):
        self.regla = regla
        super().__init__(regla.mensaje())


def validar_regla(regla: ReglaNegocio):
    if not regla.es_valido():
        raise ExcepcionReglaDeNegocio(regla)


@dataclass
class EventoDominio:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    fecha_evento: datetime = field(default_factory=ahora)


@dataclass
class EventoIntegracion(EventoDominio):
    """Cruza la frontera del microservicio -- published language."""
    ...
