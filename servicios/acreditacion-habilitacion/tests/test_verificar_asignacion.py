"""Pruebas del paso autoritativo de la saga: confirmar o compensar."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from aplicacion.comandos.verificar_asignacion import VerificarAsignacion, ejecutar
from dominio.eventos import AsignacionConfirmadaPorHabilitacion, AsignacionRechazadaPorHabilitacion
from dominio.objetos_valor import EstadoHabilitacion


@dataclass
class ProveedorFalso:
    estado: EstadoHabilitacion
    motivo: str | None = None

    def esta_disponible(self, momento: datetime | None = None) -> bool:
        return self.estado is EstadoHabilitacion.HABILITADO


class RepoFalso:
    def __init__(self, proveedores: dict):
        self._proveedores = proveedores

    def obtener_por_id(self, proveedor_id: str):
        return self._proveedores.get(proveedor_id)


class SesionFalsa:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1


def _comando():
    return VerificarAsignacion(
        trabajo_id="t-1", asignacion_id="a-1", proveedor_id="prov-1",
    )


def test_proveedor_habilitado_publica_confirmacion():
    publicados = []
    repo = RepoFalso({"prov-1": ProveedorFalso(EstadoHabilitacion.HABILITADO)})
    ok = ejecutar(_comando(), repo, SesionFalsa(), publicados.append)
    assert ok is True
    assert len(publicados) == 1
    assert isinstance(publicados[0], AsignacionConfirmadaPorHabilitacion)
    assert publicados[0].estado_real == "HABILITADO"


def test_proveedor_suspendido_publica_compensacion():
    publicados = []
    repo = RepoFalso({
        "prov-1": ProveedorFalso(EstadoHabilitacion.SUSPENDIDO, motivo="LICENCIA_VENCIDA"),
    })
    ok = ejecutar(_comando(), repo, SesionFalsa(), publicados.append)
    assert ok is False
    assert isinstance(publicados[0], AsignacionRechazadaPorHabilitacion)
    assert publicados[0].motivo == "LICENCIA_VENCIDA"


def test_proveedor_desconocido_tambien_compensa():
    publicados = []
    ok = ejecutar(_comando(), RepoFalso({}), SesionFalsa(), publicados.append)
    assert ok is False
    assert publicados[0].estado_real == "DESCONOCIDO"
    assert publicados[0].motivo == "PROVEEDOR_NO_EXISTE"
