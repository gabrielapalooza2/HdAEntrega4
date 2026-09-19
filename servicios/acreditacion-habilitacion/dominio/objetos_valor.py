"""Objetos valor del dominio de Acreditacion y Habilitacion."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class EstadoHabilitacion(Enum):
    HABILITADO = "HABILITADO"
    SUSPENDIDO = "SUSPENDIDO"
    INHABILITADO = "INHABILITADO"

    def habilita_para_trabajar(self) -> bool:
        return self is EstadoHabilitacion.HABILITADO


class CategoriaServicio(Enum):
    PLOMERIA = "PLOMERIA"
    ELECTRICIDAD = "ELECTRICIDAD"
    CARPINTERIA = "CARPINTERIA"
    PINTURA = "PINTURA"
    CERRAJERIA = "CERRAJERIA"
    OTRO = "OTRO"

    @classmethod
    def desde_codigo(cls, codigo: str) -> "CategoriaServicio":
        try:
            return cls(codigo)
        except ValueError:
            raise ValueError(f"Categoria de servicio desconocida: {codigo}")


class TipoProveedor(Enum):
    PERSONA_NATURAL = "PERSONA_NATURAL"
    EMPRESA = "EMPRESA"


@dataclass(frozen=True)
class VigenciaExpediente:
    vigente_hasta: datetime | None

    def esta_vencido(self, momento: datetime) -> bool:
        if self.vigente_hasta is None:
            return False
        return momento > self.vigente_hasta


@dataclass(frozen=True)
class ResultadoVerificacion:
    aprobado: bool
    fuente: str
    motivo: str | None
    verificado_en: datetime
    desde_cache: bool = False
