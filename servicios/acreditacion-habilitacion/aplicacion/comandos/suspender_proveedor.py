"""Caso de uso: suspender un proveedor. Gatillo del escenario de saga/compensacion."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from dominio.eventos import EventoIntegracion
from dominio.excepciones import ProveedorNoExiste
from dominio.repositorios import RepositorioProveedores

from aplicacion.dto import ProveedorDTO


@dataclass(frozen=True)
class SuspenderProveedor:
    proveedor_id: str
    motivo: str


def ejecutar(
    comando: SuspenderProveedor,
    repositorio: RepositorioProveedores,
    session,
    publicar_evento: Callable[[EventoIntegracion], None],
) -> ProveedorDTO:
    proveedor = repositorio.obtener_por_id(comando.proveedor_id)
    if proveedor is None:
        raise ProveedorNoExiste(comando.proveedor_id)

    proveedor.suspender(comando.motivo)
    repositorio.actualizar(proveedor)

    session.commit()
    eventos = proveedor.obtener_eventos()
    proveedor.limpiar_eventos()
    for evento in eventos:
        if isinstance(evento, EventoIntegracion):
            publicar_evento(evento)

    return ProveedorDTO.desde_entidad(proveedor)
