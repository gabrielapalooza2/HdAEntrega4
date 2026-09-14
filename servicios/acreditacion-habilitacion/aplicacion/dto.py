"""DTO de la capa de aplicacion."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class ProveedorDTO:
    id: str
    nombre: str
    tipo_proveedor: str
    estado: str
    categorias: list[str] = field(default_factory=list)
    ciudades: list[str] = field(default_factory=list)
    motivo: str | None = None
    vigente_hasta: datetime | None = None
    fecha_actualizacion: datetime | None = None

    @staticmethod
    def desde_entidad(entidad) -> "ProveedorDTO":
        return ProveedorDTO(
            id=str(entidad.id), nombre=entidad.nombre, tipo_proveedor=entidad.tipo_proveedor.value,
            estado=entidad.estado.value, categorias=[c.value for c in entidad.categorias],
            ciudades=list(entidad.ciudades), motivo=entidad.motivo,
            vigente_hasta=entidad.vigencia.vigente_hasta, fecha_actualizacion=entidad.fecha_actualizacion,
        )

    def a_externo(self) -> dict:
        return {
            "id": self.id, "nombre": self.nombre, "tipo_proveedor": self.tipo_proveedor,
            "estado": self.estado, "categorias": self.categorias, "ciudades": self.ciudades,
            "motivo": self.motivo,
            "vigente_hasta": self.vigente_hasta.isoformat() if self.vigente_hasta else None,
            "actualizado": self.fecha_actualizacion.isoformat() if self.fecha_actualizacion else None,
        }
