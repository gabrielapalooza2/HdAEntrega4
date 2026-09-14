"""Mapeadores: la traducción entre las tres representaciones de un Partner.

Hay tres y son distintas a propósito:
  1. la ENTIDAD de dominio, rica en comportamiento,
  2. el DTO, plano, que toca PostgreSQL,
  3. el PAYLOAD Avro, que es el contrato público.

Que las tres sean la misma clase es la forma más rápida de convertir un cambio de
base de datos en un cambio de contrato público. Estos mapeadores son la frontera.
"""

import uuid
from datetime import datetime

from motor_reglas.seedwork.dominio.objetos_valor import Dinero
from motor_reglas.seedwork.dominio.repositorios import Mapeador
from motor_reglas.seedwork.infraestructura.utils import datetime_a_millis, millis_a_datetime

from ..dominio.entidades import Convenio, Partner, ReglaDePartner
from ..dominio.objetos_valor import (
    AcuerdoDeServicio,
    Categoria,
    CoberturaContratada,
    RedHomologada,
    Tarifa,
    TipoPartner,
    Vigencia,
)
from .dto import Partner as PartnerDTO


class MapeadorPartner(Mapeador):
    """Dominio <-> DTO de persistencia."""

    _FORMATO_FECHA = "%Y-%m-%dT%H:%M:%SZ"

    def obtener_tipo(self) -> type:
        return Partner.__class__

    def entidad_a_dto(self, partner: Partner) -> PartnerDTO:
        convenio = partner.convenio
        regla = partner.regla
        return PartnerDTO(
            id=str(partner.id),
            nombre=partner.nombre,
            tipo=partner.tipo.value if partner.tipo else None,
            activo=partner.activo,
            convenio_id=str(convenio.id),
            convenio_numero=convenio.numero,
            vigencia_desde=convenio.vigencia.desde,
            vigencia_hasta=convenio.vigencia.hasta,
            tarifa_comision=convenio.tarifa.porcentaje_comision if convenio.tarifa else None,
            tarifa_moneda=convenio.tarifa.moneda if convenio.tarifa else None,
            regla_id=str(regla.id) if regla else None,
            regla_version=regla.version if regla else 0,
            sla_minutos=regla.acuerdo.sla_minutos if regla else None,
            monto_maximo_monto=regla.acuerdo.monto_maximo_sin_aprobacion.monto if regla else None,
            monto_maximo_moneda=regla.acuerdo.monto_maximo_sin_aprobacion.moneda if regla else None,
            cobertura=[c.value for c in regla.cobertura.categorias] if regla else [],
            pasos_aprobacion=list(regla.acuerdo.pasos_de_aprobacion) if regla else [],
            red_homologada=list(regla.red_homologada.proveedores) if regla else [],
            fecha_creacion=partner.fecha_creacion,
            fecha_actualizacion=partner.fecha_actualizacion,
        )

    def dto_a_entidad(self, dto: PartnerDTO) -> Partner:
        convenio = Convenio(
            id=uuid.UUID(dto.convenio_id),
            numero=dto.convenio_numero,
            vigencia=Vigencia(desde=dto.vigencia_desde, hasta=dto.vigencia_hasta),
            tarifa=Tarifa(dto.tarifa_comision, dto.tarifa_moneda) if dto.tarifa_moneda else None,
        )

        regla = None
        if dto.regla_id:
            regla = ReglaDePartner(
                id=uuid.UUID(dto.regla_id),
                version=dto.regla_version,
                cobertura=CoberturaContratada(tuple(Categoria(c) for c in (dto.cobertura or []))),
                acuerdo=AcuerdoDeServicio(
                    sla_minutos=dto.sla_minutos,
                    monto_maximo_sin_aprobacion=Dinero(dto.monto_maximo_monto, dto.monto_maximo_moneda),
                    pasos_de_aprobacion=tuple(dto.pasos_aprobacion or []),
                ),
                red_homologada=RedHomologada(tuple(dto.red_homologada or [])),
            )

        return Partner(
            id=uuid.UUID(dto.id),
            nombre=dto.nombre,
            tipo=TipoPartner(dto.tipo),
            activo=dto.activo,
            convenio=convenio,
            regla=regla,
            fecha_creacion=dto.fecha_creacion,
            fecha_actualizacion=dto.fecha_actualizacion,
        )


class MapeadorEventosPartner:
    """Dominio -> payload del evento de integración.

    Aquí se decide qué se expone al mundo. Todo lo que este método NO copia es
    modelo interno que los consumidores nunca verán, y por tanto nunca podrán
    acoplarse a él.
    """

    def partner_a_payload_dict(self, partner: Partner) -> dict:
        regla = partner.regla
        convenio = partner.convenio
        return {
            "partner_id": str(partner.id),
            "convenio_id": str(convenio.id),
            "nombre": partner.nombre,
            "tipo_partner": partner.tipo.value,
            "activo": partner.activo,
            "vigencia_desde": datetime_a_millis(convenio.vigencia.desde),
            "vigencia_hasta": datetime_a_millis(convenio.vigencia.hasta) if convenio.vigencia.hasta else 0,
            "version_regla": regla.version if regla else 0,
            "cobertura_contratada": [c.value for c in regla.cobertura.categorias] if regla else [],
            "sla_minutos": regla.acuerdo.sla_minutos if regla else 0,
            "monto_maximo_sin_aprobacion": {
                "monto": regla.acuerdo.monto_maximo_sin_aprobacion.monto if regla else 0,
                "moneda": regla.acuerdo.monto_maximo_sin_aprobacion.moneda if regla else "COP",
            },
            "pasos_de_aprobacion": list(regla.acuerdo.pasos_de_aprobacion) if regla else [],
            "red_homologada": list(regla.red_homologada.proveedores) if regla else [],
            "porcentaje_comision": convenio.tarifa.porcentaje_comision if convenio.tarifa else 0.0,
            "moneda_tarifa": convenio.tarifa.moneda if convenio.tarifa else "",
        }
