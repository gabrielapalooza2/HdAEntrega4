"""Reaccion coreografiada a TrabajoAsignado (evt.trabajos, filtrado por type).

TrabajoAsignadoPayload no trae categoria -- la verificacion aqui es solo
habilitacion + vigencia contra el dato autoritativo (Proveedor.esta_disponible).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from dominio.eventos import AsignacionRechazadaPorHabilitacion, EventoIntegracion
from dominio.excepciones import ProveedorNoExiste
from dominio.repositorios import RepositorioProveedores


@dataclass(frozen=True)
class VerificarAsignacion:
    trabajo_id: str
    asignacion_id: str
    proveedor_id: str


def ejecutar(
    comando: VerificarAsignacion,
    repositorio: RepositorioProveedores,
    session,
    publicar_evento: Callable[[EventoIntegracion], None],
) -> bool:
    proveedor = repositorio.obtener_por_id(comando.proveedor_id)
    if proveedor is None:
        raise ProveedorNoExiste(comando.proveedor_id)

    disponible = proveedor.esta_disponible()

    if not disponible:
        publicar_evento(AsignacionRechazadaPorHabilitacion(
            trabajo_id=comando.trabajo_id, asignacion_id=comando.asignacion_id,
            proveedor_id=comando.proveedor_id, estado_real=proveedor.estado.value,
            motivo=proveedor.motivo or f"Proveedor no habilitado (estado {proveedor.estado.value})",
        ))

    session.commit()
    return disponible
