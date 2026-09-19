"""Fabrica del agregado Proveedor."""
from __future__ import annotations

import uuid

from .entidades import Proveedor
from .objetos_valor import CategoriaServicio, TipoProveedor


class ConstructorProveedor:
    @staticmethod
    def construir(nombre: str, categorias: list[str], ciudades: list[str],
                  proveedor_id: str | None = None, tipo_proveedor: str = "PERSONA_NATURAL") -> Proveedor:
        kwargs = {}
        if proveedor_id is not None:
            try:
                kwargs["id"] = uuid.UUID(str(proveedor_id))
            except (ValueError, AttributeError, TypeError):
                raise ValueError(f"proveedor_id '{proveedor_id}' no es un UUID valido")
        return Proveedor(
            nombre=nombre,
            tipo_proveedor=TipoProveedor(tipo_proveedor),
            categorias=[CategoriaServicio.desde_codigo(c) for c in categorias],
            ciudades=list(ciudades),
            **kwargs,
        )
