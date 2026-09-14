"""Comando: registrar un partner nuevo con su convenio y su regla de operación.

ESTE ES EL ESCENARIO 6 EN UNA FUNCIÓN. Incorporar el partner 31 ejecuta este
comando una vez. No hay despliegue de dominio, no hay rama de código nueva: hay
una fila más y un evento.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from motor_reglas.config.db import db
from motor_reglas.seedwork.aplicacion.comandos import Comando, ejecutar_comando
from motor_reglas.seedwork.dominio.objetos_valor import Dinero

from ...dominio.entidades import Convenio, Partner, ReglaDePartner
from ...dominio.objetos_valor import (
    AcuerdoDeServicio,
    Categoria,
    CoberturaContratada,
    RedHomologada,
    Tarifa,
    TipoPartner,
    Vigencia,
)
from ...infraestructura.mapeadores import MapeadorEventosPartner
from ...infraestructura.outbox import registrar_en_outbox
from .base import RegistrarPartnerBaseHandler


@dataclass
class RegistrarPartner(Comando):
    nombre: str
    tipo_partner: str
    convenio_numero: str
    vigencia_desde: datetime
    cobertura_contratada: list[str]
    sla_minutos: int
    monto_maximo_monto: int
    monto_maximo_moneda: str
    partner_id: str | None = None
    vigencia_hasta: datetime | None = None
    porcentaje_comision: float = 0.0
    moneda_tarifa: str = "COP"
    pasos_de_aprobacion: list[str] = field(default_factory=list)
    red_homologada: list[str] = field(default_factory=list)
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))


class RegistrarPartnerHandler(RegistrarPartnerBaseHandler):
    def handle(self, comando: RegistrarPartner) -> str:
        partner = Partner(
            id=uuid.UUID(comando.partner_id) if comando.partner_id else uuid.uuid4(),
            nombre=comando.nombre,
            tipo=TipoPartner(comando.tipo_partner),
            activo=True,
        )

        convenio = Convenio(
            numero=comando.convenio_numero,
            vigencia=Vigencia(desde=comando.vigencia_desde, hasta=comando.vigencia_hasta),
            tarifa=Tarifa(comando.porcentaje_comision, comando.moneda_tarifa),
        )
        partner.firmar_convenio(convenio)

        regla = ReglaDePartner(
            cobertura=CoberturaContratada(tuple(Categoria(c) for c in comando.cobertura_contratada)),
            acuerdo=AcuerdoDeServicio(
                sla_minutos=comando.sla_minutos,
                monto_maximo_sin_aprobacion=Dinero(comando.monto_maximo_monto, comando.monto_maximo_moneda),
                pasos_de_aprobacion=tuple(comando.pasos_de_aprobacion),
            ),
            red_homologada=RedHomologada(tuple(comando.red_homologada)),
        )
        partner.definir_regla(regla, convenio.id)

        self.repositorio.agregar(partner)

        # El evento se registra en el outbox DENTRO de esta transacción: o existen
        # los dos, o no existe ninguno.
        registrar_en_outbox(
            tipo="ReglaDePartnerActualizada",
            clave=str(partner.id),
            payload=MapeadorEventosPartner().partner_a_payload_dict(partner),
            correlation_id=comando.correlation_id,
        )
        db.session.commit()
        partner.limpiar_eventos()
        return str(partner.id)


@ejecutar_comando.register(RegistrarPartner)
def ejecutar_registrar_partner(comando: RegistrarPartner):
    return RegistrarPartnerHandler().handle(comando)
