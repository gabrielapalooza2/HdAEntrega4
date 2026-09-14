"""Copias locales de los Record que este servicio produce o consume.

Fuente: entrega4/contratos/generar.py. No se importa ese archivo (acoplamiento
de código entre MS). No se mutan los .avsc.
"""

from infraestructura.schema.v1.eventos import (
    Dinero,
    EstadoDeHabilitacionCambiadoPayload,
    EventoAsignacionRechazadaPorHabilitacion,
    EventoEstadoDeHabilitacionCambiado,
    EventoReglaDePartnerActualizada,
    EventoTrabajoAsignado,
    EventoTrabajoCreado,
    EventoTrabajoRechazado,
    ReglaDePartnerActualizadaPayload,
    TrabajoAsignadoPayload,
    TrabajoCreadoPayload,
    TrabajoRechazadoPayload,
    AsignacionRechazadaPorHabilitacionPayload,
)

__all__ = [
    "Dinero",
    "EstadoDeHabilitacionCambiadoPayload",
    "EventoAsignacionRechazadaPorHabilitacion",
    "EventoEstadoDeHabilitacionCambiado",
    "EventoReglaDePartnerActualizada",
    "EventoTrabajoAsignado",
    "EventoTrabajoCreado",
    "EventoTrabajoRechazado",
    "ReglaDePartnerActualizadaPayload",
    "TrabajoAsignadoPayload",
    "TrabajoCreadoPayload",
    "TrabajoRechazadoPayload",
    "AsignacionRechazadaPorHabilitacionPayload",
]
