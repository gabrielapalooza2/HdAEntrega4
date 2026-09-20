"""Reaccion coreografiada a TrabajoAsignado (evt.trabajos, filtrado por type).

Emparejamiento asigna contra su proyeccion local. Este servicio es el unico
dueno del dato autoritativo: confirma o dispara la compensacion. Nadie le
ordena el siguiente paso.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from dominio.eventos import (
    AsignacionConfirmadaPorHabilitacion,
    AsignacionRechazadaPorHabilitacion,
    EventoIntegracion,
)
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
        publicar_evento(AsignacionRechazadaPorHabilitacion(
            trabajo_id=comando.trabajo_id,
            asignacion_id=comando.asignacion_id,
            proveedor_id=comando.proveedor_id,
            estado_real="DESCONOCIDO",
            motivo="PROVEEDOR_NO_EXISTE",
        ))
        session.commit()
        return False

    disponible = proveedor.esta_disponible()
    if disponible:
        publicar_evento(AsignacionConfirmadaPorHabilitacion(
            trabajo_id=comando.trabajo_id,
            asignacion_id=comando.asignacion_id,
            proveedor_id=comando.proveedor_id,
            estado_real=proveedor.estado.value,
        ))
    else:
        publicar_evento(AsignacionRechazadaPorHabilitacion(
            trabajo_id=comando.trabajo_id,
            asignacion_id=comando.asignacion_id,
            proveedor_id=comando.proveedor_id,
            estado_real=proveedor.estado.value,
            motivo=proveedor.motivo or f"Proveedor no habilitado (estado {proveedor.estado.value})",
        ))

    session.commit()
    return disponible
