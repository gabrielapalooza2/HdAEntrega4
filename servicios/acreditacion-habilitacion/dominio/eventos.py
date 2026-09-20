"""Eventos de dominio e integracion de Acreditacion y Habilitacion."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ._base import EventoDominio, EventoIntegracion, ahora


@dataclass
class ProveedorAcreditado(EventoDominio):
    proveedor_id: str = None
    tipo_proveedor: str = None


@dataclass
class ProveedorSuspendido(EventoDominio):
    proveedor_id: str = None
    motivo: str = None


@dataclass
class EstadoDeHabilitacionCambiado(EventoIntegracion):
    """ECST. Topico evt.proveedores, compactado, clave proveedor_id."""
    proveedor_id: str = None
    nombre: str = None
    estado: str = None
    categorias: list[str] = field(default_factory=list)
    ciudades: list[str] = field(default_factory=list)
    motivo: str | None = None
    vigente_hasta: datetime | None = None


@dataclass
class AsignacionRechazadaPorHabilitacion(EventoIntegracion):
    """Compensacion de la saga. Topico evt.asignaciones."""
    trabajo_id: str = None
    asignacion_id: str = None
    proveedor_id: str = None
    estado_real: str = None
    motivo: str = None
    verificado_en: datetime = field(default_factory=ahora)


@dataclass
class AsignacionConfirmadaPorHabilitacion(EventoIntegracion):
    """Cierre feliz de la saga. Topico evt.asignaciones."""
    trabajo_id: str = None
    asignacion_id: str = None
    proveedor_id: str = None
    estado_real: str = None
    verificado_en: datetime = field(default_factory=ahora)
