"""Agregación Partner: entidades Convenio y ReglaDePartner.

FRONTERA TRANSACCIONAL. Partner es la raíz; Convenio y ReglaDePartner solo se
tocan a través de ella. La razón no es estética: una regla sin convenio vigente
que la respalde es un estado inválido del negocio, y los dos tienen que quedar
consistentes de inmediato. Eso es lo que define una agregación en Evans.

Mercado es una agregación SEPARADA aunque el mismo servicio la posea: sus
invariantes son independientes de los de Partner y no hay ninguna regla que exija
que las dos queden consistentes en la misma transacción.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from motor_reglas.seedwork.dominio.entidades import AgregacionRaiz, Entidad

from .eventos import PartnerDadoDeBaja, ReglaDePartnerActualizada
from .objetos_valor import (
    AcuerdoDeServicio,
    Categoria,
    CoberturaContratada,
    RedHomologada,
    Tarifa,
    TipoPartner,
    Vigencia,
)
from .reglas import (
    ConvenioDebeTenerVigenciaValida,
    PartnerDebeTenerAlMenosUnaCategoria,
    ReglaDebePertenecerAlConvenioDelPartner,
)


@dataclass
class Convenio(Entidad):
    """El acuerdo comercial firmado. Entidad, no objeto valor: dos convenios con
    los mismos términos siguen siendo convenios distintos."""

    numero: str = None
    vigencia: Vigencia = None
    tarifa: Tarifa = None

    def esta_vigente(self, momento: datetime | None = None) -> bool:
        momento = momento or datetime.utcnow()
        return self.vigencia is not None and self.vigencia.vigente_en(momento)


@dataclass
class ReglaDePartner(Entidad):
    """LA PIEZA CENTRAL DEL ESCENARIO 6.

    Todo lo que distingue a un partner de otro vive aquí, como DATO. Un partner
    nuevo es una instancia más de esta entidad; nunca una rama nueva de código en
    Orquestación de trabajos.
    """

    version: int = 1
    cobertura: CoberturaContratada = None
    acuerdo: AcuerdoDeServicio = None
    red_homologada: RedHomologada = field(default_factory=RedHomologada)

    def permite(self, categoria: Categoria) -> bool:
        return self.cobertura is not None and self.cobertura.cubre(categoria)

    def admite_proveedor(self, proveedor_id: str) -> bool:
        return self.red_homologada.admite(proveedor_id)


@dataclass
class Partner(AgregacionRaiz):
    """Raíz de la agregación. Único punto de entrada."""

    nombre: str = None
    tipo: TipoPartner = None
    activo: bool = True
    convenio: Convenio = None
    regla: ReglaDePartner = None

    # ---------- comportamiento de dominio ----------

    def firmar_convenio(self, convenio: Convenio):
        self.validar_regla(ConvenioDebeTenerVigenciaValida(convenio.vigencia))
        self.convenio = convenio
        self.tocar()

    def definir_regla(self, regla: ReglaDePartner, convenio_id: uuid.UUID | str | None = None):
        """Fija o reemplaza la regla de operación del partner.

        Sube la versión y registra el evento de dominio. Nadie llama a esto desde
        afuera de la agregación: la capa de aplicación habla con el Partner, no
        con la ReglaDePartner.
        """
        self.validar_regla(PartnerDebeTenerAlMenosUnaCategoria(regla.cobertura))
        self.validar_regla(
            ReglaDebePertenecerAlConvenioDelPartner(self, convenio_id or (self.convenio.id if self.convenio else None))
        )

        regla.version = (self.regla.version + 1) if self.regla else 1
        self.regla = regla
        self.tocar()

        self.agregar_evento(
            ReglaDePartnerActualizada(
                partner_id=str(self.id),
                convenio_id=str(self.convenio.id),
                version_regla=regla.version,
                fecha_actualizacion=self.fecha_actualizacion,
            )
        )

    def dar_de_baja(self, motivo: str):
        """No se borra: se publica con activo=False.

        Borrar el registro dejaría a los consumidores con una regla obsoleta para
        siempre, porque en un tópico compactado la ausencia de mensaje no borra
        nada. La baja tiene que viajar como un mensaje más.
        """
        self.activo = False
        self.tocar()
        self.agregar_evento(PartnerDadoDeBaja(partner_id=str(self.id), motivo=motivo))
        self.agregar_evento(
            ReglaDePartnerActualizada(
                partner_id=str(self.id),
                convenio_id=str(self.convenio.id) if self.convenio else "",
                version_regla=self.regla.version if self.regla else 0,
                fecha_actualizacion=self.fecha_actualizacion,
            )
        )

    # ---------- consultas de dominio ----------

    def puede_solicitar(self, categoria: Categoria, momento: datetime | None = None) -> bool:
        """La pregunta que Orquestación de trabajos responde leyendo su proyección.

        Si esta lógica no existiera aquí, viviría como un condicional por
        identificador de partner dentro del motor de gestión de trabajos. Ese
        traslado es, literalmente, el escenario 6.
        """
        if not self.activo or self.regla is None:
            return False
        if self.convenio is None or not self.convenio.esta_vigente(momento):
            return False
        return self.regla.permite(categoria)
