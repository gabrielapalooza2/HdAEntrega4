"""Implementación SQLAlchemy de los repositorios del dominio de partners.

Nótese la dirección de la dependencia: este archivo importa del dominio; el
dominio no importa nada de aquí. Esa es la inversión de dependencias de la
arquitectura cebolla, y es lo que permitiría cambiar PostgreSQL por otra cosa sin
tocar una línea de `dominio/`.
"""

from uuid import UUID

from motor_reglas.config.db import db

from ..dominio.entidades import Partner
from ..dominio.excepciones import PartnerNoExiste
from ..dominio.repositorios import RepositorioPartners
from .dto import Partner as PartnerDTO
from .mapeadores import MapeadorPartner


class RepositorioPartnersSQLAlchemy(RepositorioPartners):
    def __init__(self):
        self._mapeador = MapeadorPartner()

    def obtener_por_id(self, id: UUID) -> Partner:
        dto = db.session.query(PartnerDTO).filter_by(id=str(id)).one_or_none()
        if dto is None:
            raise PartnerNoExiste(id)
        return self._mapeador.dto_a_entidad(dto)

    def obtener_todos(self) -> list[Partner]:
        return [self._mapeador.dto_a_entidad(d) for d in db.session.query(PartnerDTO).all()]

    def agregar(self, partner: Partner):
        db.session.add(self._mapeador.entidad_a_dto(partner))

    def actualizar(self, partner: Partner):
        """`merge` y no `add`: la agregación se reconstruyó desde el DTO, así que
        la sesión puede no tenerla adjunta."""
        db.session.merge(self._mapeador.entidad_a_dto(partner))

    def eliminar(self, partner_id: UUID):
        raise NotImplementedError(
            "Un partner no se elimina: se da de baja con activo=False. "
            "Borrar la fila dejaría a los consumidores con una regla obsoleta, "
            "porque en un tópico compactado la ausencia de mensaje no borra nada."
        )
