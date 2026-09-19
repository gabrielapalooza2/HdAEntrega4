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
    numero: str = None
    vigencia: Vigencia = None
    tarifa: Tarifa = None

    def esta_vigente(self, momento: datetime | None = None) -> bool:
        momento = momento or datetime.utcnow()
        return self.vigencia is not None and self.vigencia.vigente_en(momento)


@dataclass
class ReglaDePartner(Entidad):
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
    nombre: str = None
    tipo: TipoPartner = None
    activo: bool = True
    convenio: Convenio = None
    regla: ReglaDePartner = None


    def firmar_convenio(self, convenio: Convenio):
        self.validar_regla(ConvenioDebeTenerVigenciaValida(convenio.vigencia))
        self.convenio = convenio
        self.tocar()

    def definir_regla(self, regla: ReglaDePartner, convenio_id: uuid.UUID | str | None = None):

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

 
    def puede_solicitar(self, categoria: Categoria, momento: datetime | None = None) -> bool:

        if not self.activo or self.regla is None:
            return False
        if self.convenio is None or not self.convenio.esta_vigente(momento):
            return False
        return self.regla.permite(categoria)
