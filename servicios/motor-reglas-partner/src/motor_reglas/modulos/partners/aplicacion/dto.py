"""DTOs de la capa de aplicación: lo que entra y sale por la frontera del servicio."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DineroDTO:
    monto: int
    moneda: str


@dataclass(frozen=True)
class ReglaDTO:
    cobertura_contratada: list[str]
    sla_minutos: int
    monto_maximo_sin_aprobacion: DineroDTO
    pasos_de_aprobacion: list[str] = field(default_factory=list)
    red_homologada: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PartnerDTO:
    id: str
    nombre: str
    tipo_partner: str
    activo: bool
    convenio_numero: str
    vigencia_desde: str
    vigencia_hasta: str | None
    regla: ReglaDTO | None
