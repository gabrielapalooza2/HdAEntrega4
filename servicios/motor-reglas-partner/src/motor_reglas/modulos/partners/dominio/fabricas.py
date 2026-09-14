"""Fábrica del dominio de partners.

Despacha al mapeador correcto según el tipo. Gracias a esto, ni la capa de
aplicación ni los repositorios saben cómo se arma un Partner por dentro.
"""

from dataclasses import dataclass

from motor_reglas.seedwork.dominio.entidades import Entidad
from motor_reglas.seedwork.dominio.fabricas import Fabrica
from motor_reglas.seedwork.dominio.repositorios import Mapeador

from .entidades import Partner
from .excepciones import TipoObjetoNoExisteEnDominioPartnersExcepcion


@dataclass
class FabricaPartners(Fabrica):
    def crear_objeto(self, obj, mapeador: Mapeador) -> any:
        if isinstance(obj, Entidad):
            return mapeador.entidad_a_dto(obj)

        partner = mapeador.dto_a_entidad(obj)
        if not isinstance(partner, Partner):
            raise TipoObjetoNoExisteEnDominioPartnersExcepcion()
        return partner
