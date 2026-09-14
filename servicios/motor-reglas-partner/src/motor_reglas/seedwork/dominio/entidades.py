import uuid
from dataclasses import dataclass, field
from datetime import datetime

from .eventos import EventoDominio
from .mixins import ValidarReglasMixin


@dataclass
class Entidad:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    fecha_creacion: datetime = field(default_factory=datetime.utcnow)
    fecha_actualizacion: datetime = field(default_factory=datetime.utcnow)

    @classmethod
    def siguiente_id(cls) -> uuid.UUID:
        return uuid.uuid4()

    def tocar(self):
        self.fecha_actualizacion = datetime.utcnow()


@dataclass
class AgregacionRaiz(Entidad, ValidarReglasMixin):

    eventos: list[EventoDominio] = field(default_factory=list)

    def agregar_evento(self, evento: EventoDominio):
        self.eventos.append(evento)

    def limpiar_eventos(self):
        self.eventos = list()
