"""Adaptador de persistencia del agregado Proveedor."""
from __future__ import annotations

import uuid
from datetime import timezone

from dominio.entidades import Proveedor
from dominio.objetos_valor import CategoriaServicio, EstadoHabilitacion, TipoProveedor, VigenciaExpediente
from dominio.repositorios import RepositorioProveedores

from .dto import ProveedorDBO


def _dto_a_entidad(dbo: ProveedorDBO) -> Proveedor:
    proveedor = Proveedor(
        id=uuid.UUID(dbo.id), nombre=dbo.nombre, tipo_proveedor=TipoProveedor(dbo.tipo_proveedor),
        estado=EstadoHabilitacion(dbo.estado),
        categorias=[CategoriaServicio.desde_codigo(c) for c in (dbo.categorias or [])],
        ciudades=list(dbo.ciudades or []), motivo=dbo.motivo,
        vigencia=VigenciaExpediente(vigente_hasta=dbo.vigente_hasta),
        fecha_creacion=dbo.fecha_creacion, fecha_actualizacion=dbo.fecha_actualizacion,
    )
    proveedor.limpiar_eventos()
    return proveedor


def _entidad_a_dto(entidad: Proveedor) -> ProveedorDBO:
    return ProveedorDBO(
        id=str(entidad.id), nombre=entidad.nombre, tipo_proveedor=entidad.tipo_proveedor.value,
        estado=entidad.estado.value, categorias=[c.value for c in entidad.categorias],
        ciudades=list(entidad.ciudades), motivo=entidad.motivo,
        vigente_hasta=entidad.vigencia.vigente_hasta,
        fecha_creacion=entidad.fecha_creacion, fecha_actualizacion=entidad.fecha_actualizacion,
    )


class RepositorioProveedoresSQLAlchemy(RepositorioProveedores):
    def __init__(self, session):
        self.session = session

    def obtener_por_id(self, id) -> Proveedor | None:
        dbo = self.session.query(ProveedorDBO).filter_by(id=str(id)).one_or_none()
        return _dto_a_entidad(dbo) if dbo else None

    def obtener_todos(self) -> list[Proveedor]:
        return [_dto_a_entidad(d) for d in self.session.query(ProveedorDBO).all()]

    def obtener_por_estado(self, estado: str) -> list[Proveedor]:
        return [_dto_a_entidad(d) for d in self.session.query(ProveedorDBO).filter_by(estado=estado).all()]

    def agregar(self, proveedor: Proveedor):
        self.session.add(_entidad_a_dto(proveedor))

    def actualizar(self, proveedor: Proveedor):
        dbo = self.session.query(ProveedorDBO).filter_by(id=str(proveedor.id)).one_or_none()
        if not dbo:
            self.agregar(proveedor)
            return
        dbo.nombre = proveedor.nombre
        dbo.tipo_proveedor = proveedor.tipo_proveedor.value
        dbo.estado = proveedor.estado.value
        dbo.categorias = [c.value for c in proveedor.categorias]
        dbo.ciudades = list(proveedor.ciudades)
        dbo.motivo = proveedor.motivo
        dbo.vigente_hasta = proveedor.vigencia.vigente_hasta
        dbo.fecha_actualizacion = proveedor.fecha_actualizacion

    def eliminar(self, id):
        dbo = self.session.query(ProveedorDBO).filter_by(id=str(id)).one_or_none()
        if dbo:
            self.session.delete(dbo)
