"""Lado de LECTURA.

Va directo al DTO y no reconstruye la agregación. Reconstruirla costaría armar
objetos valor y validar invariantes para después solo serializar el resultado: el
agregado existe para proteger ESCRITURAS.
"""

from dataclasses import dataclass

from motor_reglas.config.db import db
from motor_reglas.seedwork.aplicacion.queries import Query, QueryHandler, QueryResultado, ejecutar_query

from ...infraestructura.dto import Partner as PartnerDTO


def _a_dict(dto: PartnerDTO) -> dict:
    return {
        "id": dto.id,
        "nombre": dto.nombre,
        "tipo_partner": dto.tipo,
        "activo": dto.activo,
        "convenio": {
            "id": dto.convenio_id,
            "numero": dto.convenio_numero,
            "vigencia_desde": dto.vigencia_desde.isoformat() if dto.vigencia_desde else None,
            "vigencia_hasta": dto.vigencia_hasta.isoformat() if dto.vigencia_hasta else None,
        },
        "regla": None if not dto.regla_id else {
            "version": dto.regla_version,
            "cobertura_contratada": dto.cobertura,
            "sla_minutos": dto.sla_minutos,
            "monto_maximo_sin_aprobacion": {
                "monto": dto.monto_maximo_monto,
                "moneda": dto.monto_maximo_moneda,
            },
            "pasos_de_aprobacion": dto.pasos_aprobacion,
            "red_homologada": dto.red_homologada,
        },
    }


@dataclass
class ObtenerPartner(Query):
    id: str


class ObtenerPartnerHandler(QueryHandler):
    def handle(self, query: ObtenerPartner) -> QueryResultado:
        dto = db.session.query(PartnerDTO).filter_by(id=query.id).one_or_none()
        return QueryResultado(resultado=_a_dict(dto) if dto else None)


@ejecutar_query.register(ObtenerPartner)
def ejecutar_obtener_partner(query: ObtenerPartner):
    return ObtenerPartnerHandler().handle(query)


@dataclass
class ObtenerPartners(Query):
    solo_activos: bool = False


class ObtenerPartnersHandler(QueryHandler):
    def handle(self, query: ObtenerPartners) -> QueryResultado:
        q = db.session.query(PartnerDTO)
        if query.solo_activos:
            q = q.filter_by(activo=True)
        return QueryResultado(resultado=[_a_dict(d) for d in q.all()])


@ejecutar_query.register(ObtenerPartners)
def ejecutar_obtener_partners(query: ObtenerPartners):
    return ObtenerPartnersHandler().handle(query)
