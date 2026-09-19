"""Adaptador de verificacion externa + circuit breaker. Escenario 8.

AdaptadorPoliciaNacionalStub NO llama a ningun sistema real -- simula
latencia y, con el interruptor de demo activo, un timeout. El patron que
se prueba es el circuit breaker + cache, no la integracion en si (permitido
explicitamente por el enunciado del curso).
"""
from __future__ import annotations

import logging
import random
import time
from datetime import datetime, timezone

import pybreaker

from dominio.objetos_valor import ResultadoVerificacion
from dominio.puertos_verificacion import VerificadorAntecedentes

from .dto import ValidacionPreviaDBO

logger = logging.getLogger(__name__)

_FALLA_FORZADA = {"activa": False}


def toggle_falla_policia_nacional(activa: bool):
    _FALLA_FORZADA["activa"] = activa
    logger.warning("[DEMO] falla forzada de Policia Nacional: %s", activa)


class AdaptadorPoliciaNacionalStub(VerificadorAntecedentes):
    def verificar(self, proveedor_id: str, fuente: str) -> ResultadoVerificacion:
        if _FALLA_FORZADA["activa"]:
            raise TimeoutError(f"Timeout simulado consultando {fuente} para {proveedor_id}")
        time.sleep(random.uniform(0.05, 0.15))
        return ResultadoVerificacion(aprobado=True, fuente=fuente, motivo=None,
                                      verificado_en=datetime.now(timezone.utc), desde_cache=False)


class RepositorioCacheValidaciones:
    def __init__(self, session):
        self.session = session

    def obtener(self, proveedor_id: str, fuente: str) -> ResultadoVerificacion | None:
        fila = self.session.query(ValidacionPreviaDBO).filter_by(proveedor_id=proveedor_id, fuente=fuente).one_or_none()
        if fila is None:
            return None
        return ResultadoVerificacion(aprobado=fila.aprobado, fuente=fila.fuente, motivo=fila.motivo,
                                      verificado_en=fila.verificado_en, desde_cache=True)

    def guardar(self, proveedor_id: str, resultado: ResultadoVerificacion):
        fila = self.session.query(ValidacionPreviaDBO).filter_by(proveedor_id=proveedor_id, fuente=resultado.fuente).one_or_none()
        if fila is None:
            fila = ValidacionPreviaDBO(proveedor_id=proveedor_id, fuente=resultado.fuente)
            self.session.add(fila)
        fila.aprobado = resultado.aprobado
        fila.motivo = resultado.motivo
        fila.verificado_en = resultado.verificado_en


class VerificacionNoDisponible(Exception):
    ...


class VerificadorConCircuitBreaker(VerificadorAntecedentes):
    def __init__(self, adaptador: VerificadorAntecedentes, cache: RepositorioCacheValidaciones,
                 fail_max: int = 3, reset_timeout: int = 30):
        self._adaptador = adaptador
        self._cache = cache
        self._breaker = pybreaker.CircuitBreaker(fail_max=fail_max, reset_timeout=reset_timeout)

    def verificar(self, proveedor_id: str, fuente: str) -> ResultadoVerificacion:
        try:
            resultado = self._breaker.call(self._adaptador.verificar, proveedor_id, fuente)
            self._cache.guardar(proveedor_id, resultado)
            return resultado
        except pybreaker.CircuitBreakerError:
            logger.warning("Circuito ABIERTO para %s, sirviendo desde cache (proveedor=%s)", fuente, proveedor_id)
            return self._desde_cache_o_falla(proveedor_id, fuente)
        except Exception as e:
            logger.warning("Fallo llamando a %s (proveedor=%s): %s. Sirviendo desde cache.", fuente, proveedor_id, e)
            return self._desde_cache_o_falla(proveedor_id, fuente)

    def _desde_cache_o_falla(self, proveedor_id: str, fuente: str) -> ResultadoVerificacion:
        cacheado = self._cache.obtener(proveedor_id, fuente)
        if cacheado is None:
            raise VerificacionNoDisponible(
                f"{fuente} no disponible y no hay validacion previa cacheada para el proveedor {proveedor_id}"
            )
        return cacheado


def crear_verificador(session) -> VerificadorConCircuitBreaker:
    return VerificadorConCircuitBreaker(AdaptadorPoliciaNacionalStub(), RepositorioCacheValidaciones(session))
