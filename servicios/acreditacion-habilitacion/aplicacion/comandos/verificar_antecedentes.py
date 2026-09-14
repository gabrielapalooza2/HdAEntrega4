"""Verificar antecedentes contra Policia Nacional/RUES via circuit breaker.
Escenario 8 -- comando invocado directamente desde la demo HTTP, no
dispara eventos de integracion (es una consulta a terceros, no un cambio
del dato autoritativo de Proveedor)."""
from __future__ import annotations

from dataclasses import dataclass

from infraestructura.verificacion_externa import crear_verificador


@dataclass(frozen=True)
class VerificarAntecedentes:
    proveedor_id: str
    fuente: str = "policia_nacional"


def ejecutar(comando: VerificarAntecedentes, session):
    verificador = crear_verificador(session)
    resultado = verificador.verificar(comando.proveedor_id, comando.fuente)
    session.commit()
    return resultado
