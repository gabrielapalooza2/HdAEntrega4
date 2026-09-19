"""Comando: cambiar la regla de operación de un partner que ya existe.

Es el mecanismo de propagación del escenario de disponibilidad: se ejecuta este
comando y los consumidores reflejan la regla nueva sin que nadie los llame.
"""

import uuid
from dataclasses import dataclass, field

from motor_reglas.config.db import db
from motor_reglas.seedwork.aplicacion.comandos import Comando, ejecutar_comando
from motor_reglas.seedwork.dominio.objetos_valor import Dinero

from ...dominio.entidades import ReglaDePartner
from ...dominio.excepciones import PartnerIdInvalido
from ...dominio.objetos_valor import (
    AcuerdoDeServicio,
    Categoria,
    CoberturaContratada,
    RedHomologada,
)
from ...infraestructura.mapeadores import MapeadorEventosPartner
from ...infraestructura.outbox import registrar_en_outbox
from .base import RegistrarPartnerBaseHandler


@dataclass
class ActualizarReglaDePartner(Comando):
    partner_id: str
    cobertura_contratada: list[str]
    sla_minutos: int
    monto_maximo_monto: int
    monto_maximo_moneda: str
    pasos_de_aprobacion: list[str] = field(default_factory=list)
    red_homologada: list[str] = field(default_factory=list)
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))


def _uuid_de_partner(partner_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(partner_id)
    except ValueError as exc:
        raise PartnerIdInvalido(partner_id) from exc


class ActualizarReglaDePartnerHandler(RegistrarPartnerBaseHandler):
    def handle(self, comando: ActualizarReglaDePartner) -> int:
        partner = self.repositorio.obtener_por_id(_uuid_de_partner(comando.partner_id))

        regla = ReglaDePartner(
            cobertura=CoberturaContratada(tuple(Categoria(c) for c in comando.cobertura_contratada)),
            acuerdo=AcuerdoDeServicio(
                sla_minutos=comando.sla_minutos,
                monto_maximo_sin_aprobacion=Dinero(comando.monto_maximo_monto, comando.monto_maximo_moneda),
                pasos_de_aprobacion=tuple(comando.pasos_de_aprobacion),
            ),
            red_homologada=RedHomologada(tuple(comando.red_homologada)),
        )
        # La versión la sube la agregación, no el cliente: el número de versión es
        # un invariante del dominio, no un parámetro de entrada.
        partner.definir_regla(regla, partner.convenio.id)

        self.repositorio.actualizar(partner)
        registrar_en_outbox(
            tipo="ReglaDePartnerActualizada",
            clave=str(partner.id),
            payload=MapeadorEventosPartner().partner_a_payload_dict(partner),
            correlation_id=comando.correlation_id,
        )
        db.session.commit()
        version = partner.regla.version
        partner.limpiar_eventos()
        return version


@ejecutar_comando.register(ActualizarReglaDePartner)
def ejecutar_actualizar_regla(comando: ActualizarReglaDePartner):
    return ActualizarReglaDePartnerHandler().handle(comando)
