"""Agregacion Proveedor. Frontera transaccional del microservicio."""
from __future__ import annotations
from ._base import ahora

from dataclasses import dataclass, field
from datetime import datetime

from ._base import AgregacionRaiz, validar_regla
from .eventos import EstadoDeHabilitacionCambiado, ProveedorAcreditado, ProveedorSuspendido
from .objetos_valor import CategoriaServicio, EstadoHabilitacion, TipoProveedor, VigenciaExpediente
from .reglas import MotivoDeSuspensionEsObligatorio, ProveedorDebeCubrirCategoria, ProveedorDebeEstarHabilitado, ProveedorDebeEstarVigente


@dataclass
class Proveedor(AgregacionRaiz):
    nombre: str = ""
    tipo_proveedor: TipoProveedor = TipoProveedor.PERSONA_NATURAL
    estado: EstadoHabilitacion = EstadoHabilitacion.SUSPENDIDO
    categorias: list[CategoriaServicio] = field(default_factory=list)
    ciudades: list[str] = field(default_factory=list)
    motivo: str | None = None
    vigencia: VigenciaExpediente = field(default_factory=lambda: VigenciaExpediente(vigente_hasta=None))

    def acreditar(self, nombre: str, categorias: list[CategoriaServicio], ciudades: list[str],
                  vigente_hasta: datetime | None = None):
        self.nombre = nombre
        self.categorias = categorias
        self.ciudades = ciudades
        self.vigencia = VigenciaExpediente(vigente_hasta=vigente_hasta)
        self.estado = EstadoHabilitacion.HABILITADO
        self.motivo = None
        self.tocar()
        self.agregar_evento(ProveedorAcreditado(proveedor_id=str(self.id), tipo_proveedor=self.tipo_proveedor.value))
        self._publicar_estado_cambiado()

    def suspender(self, motivo: str):
        validar_regla(MotivoDeSuspensionEsObligatorio(motivo))
        self.estado = EstadoHabilitacion.SUSPENDIDO
        self.motivo = motivo
        self.tocar()
        self.agregar_evento(ProveedorSuspendido(proveedor_id=str(self.id), motivo=motivo))
        self._publicar_estado_cambiado()

    def inhabilitar(self, motivo: str):
        validar_regla(MotivoDeSuspensionEsObligatorio(motivo))
        self.estado = EstadoHabilitacion.INHABILITADO
        self.motivo = motivo
        self.tocar()
        self.agregar_evento(ProveedorSuspendido(proveedor_id=str(self.id), motivo=motivo))
        self._publicar_estado_cambiado()

    def esta_disponible(self, momento: datetime | None = None) -> bool:
        momento = momento or ahora()
        habilitado = ProveedorDebeEstarHabilitado(self.estado).es_valido()
        vigente = ProveedorDebeEstarVigente(self.vigencia.esta_vencido(momento)).es_valido()
        return habilitado and vigente

    def verificar_para_categoria(self, categoria: CategoriaServicio, momento: datetime | None = None) -> bool:
        cubre = ProveedorDebeCubrirCategoria(categoria, self.categorias).es_valido()
        return self.esta_disponible(momento) and cubre

    def _publicar_estado_cambiado(self):
        self.agregar_evento(EstadoDeHabilitacionCambiado(
            proveedor_id=str(self.id), nombre=self.nombre, estado=self.estado.value,
            categorias=[c.value for c in self.categorias], ciudades=list(self.ciudades),
            motivo=self.motivo, vigente_hasta=self.vigencia.vigente_hasta,
        ))
