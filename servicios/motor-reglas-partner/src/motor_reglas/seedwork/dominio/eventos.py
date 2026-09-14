"""Eventos de dominio.

Un evento de DOMINIO vive dentro del bounded context y nunca sale al bus tal cual.
Lo que sale al bus es un evento de INTEGRACIÓN, que se construye a partir de él en
la capa de infraestructura. Mantener los dos separados es lo que evita que el modelo
interno se convierta en contrato público.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class EventoDominio:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    fecha_evento: datetime = field(default_factory=datetime.utcnow)
