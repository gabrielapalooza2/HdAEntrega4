"""Reglas de negocio explicitas del modulo Acreditacion."""
from __future__ import annotations

from ._base import ReglaNegocio
from .objetos_valor import CategoriaServicio, EstadoHabilitacion


class ProveedorDebeEstarHabilitado(ReglaNegocio):
    def __init__(self, estado: EstadoHabilitacion):
        self.estado = estado
        super().__init__(f"El proveedor no esta habilitado (estado actual: {estado.value})")

    def es_valido(self) -> bool:
        return self.estado.habilita_para_trabajar()


class ProveedorDebeEstarVigente(ReglaNegocio):
    def __init__(self, vencido: bool):
        self.vencido = vencido
        super().__init__("El expediente de acreditacion del proveedor vencio")

    def es_valido(self) -> bool:
        return not self.vencido


class ProveedorDebeCubrirCategoria(ReglaNegocio):
    def __init__(self, categoria: CategoriaServicio, categorias_habilitadas: list[CategoriaServicio]):
        self.categoria = categoria
        self.categorias_habilitadas = categorias_habilitadas
        super().__init__(f"El proveedor no esta habilitado para la categoria {categoria.value}")

    def es_valido(self) -> bool:
        return self.categoria in self.categorias_habilitadas


class MotivoDeSuspensionEsObligatorio(ReglaNegocio):
    def __init__(self, motivo: str | None):
        self.motivo = motivo
        super().__init__("Suspender o inhabilitar un proveedor requiere motivo")

    def es_valido(self) -> bool:
        return bool(self.motivo and self.motivo.strip())
