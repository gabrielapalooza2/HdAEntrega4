"""Caso de uso: acreditar (habilitar) un proveedor.

Sin UnidadTrabajo compartida: el patron aqui es explicito y simple --
el handler recibe la sesion y una funcion publicar_evento ya resueltas
por quien lo invoca (la API o el consumidor de Pulsar), hace su trabajo,
y al final hace commit + publica los eventos de integracion acumulados.
Esto es intencional para no reinventar el seedwork compartido que ya no
existe en este repo: cada servicio resuelve su propio "commit + publicar"
con la complejidad minima que necesita.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from dominio.eventos import EventoIntegracion
from dominio.fabricas import ConstructorProveedor
from dominio.objetos_valor import CategoriaServicio
from dominio.repositorios import RepositorioProveedores

from aplicacion.dto import ProveedorDTO


@dataclass(frozen=True)
class AcreditarProveedor:
    proveedor_id: str
    nombre: str
    categorias: list[str] = field(default_factory=list)
    ciudades: list[str] = field(default_factory=list)
    vigente_hasta: datetime | None = None
    tipo_proveedor: str = "PERSONA_NATURAL"


def ejecutar(
    comando: AcreditarProveedor,
    repositorio: RepositorioProveedores,
    session,
    publicar_evento: Callable[[EventoIntegracion], None],
) -> ProveedorDTO:
    proveedor = repositorio.obtener_por_id(comando.proveedor_id)

    if proveedor is None:
        proveedor = ConstructorProveedor.construir(
            nombre=comando.nombre, categorias=comando.categorias, ciudades=comando.ciudades,
            proveedor_id=comando.proveedor_id, tipo_proveedor=comando.tipo_proveedor,
        )
        proveedor.acreditar(nombre=proveedor.nombre, categorias=proveedor.categorias,
                             ciudades=proveedor.ciudades, vigente_hasta=comando.vigente_hasta)
        repositorio.agregar(proveedor)
    else:
        categorias_nuevas = (
            [CategoriaServicio.desde_codigo(c) for c in comando.categorias]
            if comando.categorias else proveedor.categorias
        )
        proveedor.acreditar(nombre=comando.nombre or proveedor.nombre, categorias=categorias_nuevas,
                             ciudades=comando.ciudades or proveedor.ciudades, vigente_hasta=comando.vigente_hasta)
        repositorio.actualizar(proveedor)

    session.commit()
    eventos = proveedor.obtener_eventos()
    proveedor.limpiar_eventos()
    for evento in eventos:
        if isinstance(evento, EventoIntegracion):
            publicar_evento(evento)

    return ProveedorDTO.desde_entidad(proveedor)
