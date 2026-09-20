"""Copias locales de los Record que este servicio produce o consume.

Fuente: entrega4/contratos/generar.py. No se importa ese archivo (acoplamiento
de código entre MS). No se mutan los .avsc.
"""

from infraestructura.schema.v1.eventos import (
    Dinero,
    EstadoDeHabilitacionCambiadoPayload,
    EventoAsignacionConfirmadaPorHabilitacion,
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
    AsignacionConfirmadaPorHabilitacionPayload,
)

__all__ = [
    "Dinero",
    "EstadoDeHabilitacionCambiadoPayload",
    "EventoAsignacionRechazadaPorHabilitacion",
    "EventoAsignacionConfirmadaPorHabilitacion",
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
    "AsignacionConfirmadaPorHabilitacionPayload",
]
