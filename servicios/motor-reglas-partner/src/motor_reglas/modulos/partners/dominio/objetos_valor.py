"""Objetos valor de la agregación Partner.

Son los mismos que declaramos en la vista de información de la Entrega 2:
TipoPartner, Vigencia, CoberturaContratada, Tarifa y AcuerdoDeServicio.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from motor_reglas.seedwork.dominio.objetos_valor import Dinero, ObjetoValor


class TipoPartner(str, Enum):
    ASEGURADORA = "ASEGURADORA"
    BANCO = "BANCO"
    COMERCIO = "COMERCIO"


class Categoria(str, Enum):
    PLOMERIA = "PLOMERIA"
    ELECTRICIDAD = "ELECTRICIDAD"
    CARPINTERIA = "CARPINTERIA"
    PINTURA = "PINTURA"
    CERRAJERIA = "CERRAJERIA"
    OTRO = "OTRO"


@dataclass(frozen=True)
class Vigencia(ObjetoValor):
    desde: datetime
    hasta: datetime | None = None

    def __post_init__(self):
        if self.hasta and self.hasta <= self.desde:
            raise ValueError("La vigencia no puede terminar antes de empezar")

    def vigente_en(self, momento: datetime) -> bool:
        if momento < self.desde:
            return False
        return self.hasta is None or momento <= self.hasta


@dataclass(frozen=True)
class CoberturaContratada(ObjetoValor):
    """Categorías que este partner puede solicitar.

    Es la pieza que convierte 'este partner solo puede pedir plomería' de un
    condicional en el motor a un dato consultable.
    """

    categorias: tuple[Categoria, ...] = field(default_factory=tuple)

    def cubre(self, categoria: Categoria) -> bool:
        return categoria in self.categorias


@dataclass(frozen=True)
class Tarifa(ObjetoValor):
    porcentaje_comision: float
    moneda: str

    def __post_init__(self):
        if not 0 <= self.porcentaje_comision <= 100:
            raise ValueError("La comisión debe estar entre 0 y 100")


@dataclass(frozen=True)
class AcuerdoDeServicio(ObjetoValor):
    """El SLA pactado con el partner, más los límites operativos que lo acompañan."""

    sla_minutos: int
    monto_maximo_sin_aprobacion: Dinero
    pasos_de_aprobacion: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self):
        if self.sla_minutos <= 0:
            raise ValueError("El SLA debe ser mayor a cero minutos")

    def requiere_aprobacion(self, monto: Dinero) -> bool:
        return monto > self.monto_maximo_sin_aprobacion


@dataclass(frozen=True)
class RedHomologada(ObjetoValor):
    """Proveedores que este partner acepta. Vacía significa sin restricción."""

    proveedores: tuple[str, ...] = field(default_factory=tuple)

    def admite(self, proveedor_id: str) -> bool:
        return not self.proveedores or proveedor_id in self.proveedores
