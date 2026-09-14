"""Eventos de DOMINIO del módulo de partners.

Ojo con la distinción: estos NO salen al bus. Son el registro interno de lo que le
pasó a la agregación. La capa de infraestructura los traduce a eventos de
integración antes de publicarlos, y en esa traducción decide qué se expone y qué no.
"""

from dataclasses import dataclass, field
from datetime import datetime

from motor_reglas.seedwork.dominio.eventos import EventoDominio


@dataclass
class ReglaDePartnerActualizada(EventoDominio):
    partner_id: str = None
    convenio_id: str = None
    version_regla: int = 1
    fecha_actualizacion: datetime = field(default_factory=datetime.utcnow)


@dataclass
class PartnerDadoDeBaja(EventoDominio):
    partner_id: str = None
    motivo: str = None
