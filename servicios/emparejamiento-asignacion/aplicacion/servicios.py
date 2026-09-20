from __future__ import annotations

import logging
import uuid
from typing import Callable, Optional

from dominio.emparejador import emparejar
from dominio.modelo import (
    Asignacion,
    ProyeccionHabilitacion,
    ProyeccionReglaPartner,
    ResultadoEmparejamiento,
    TrabajoParaAsignar,
    vigencia_abierta,
)
from dominio.puertos import PublicadorTrabajoAsignado, Reloj, UnidadDeTrabajo

log = logging.getLogger("emparejamiento.application")

TIPO_TRABAJO_CREADO = "TrabajoCreado"
TIPO_TRABAJO_ASIGNADO = "TrabajoAsignado"
TIPO_TRABAJO_RECHAZADO = "TrabajoRechazado"
TIPO_REGLA = "ReglaDePartnerActualizada"
TIPO_HABILITACION = "EstadoDeHabilitacionCambiado"
TIPO_RECHAZO = "AsignacionRechazadaPorHabilitacion"
TIPO_RECHAZO_REGLA = "AsignacionRechazadaPorReglaPartner"
TIPO_CONFIRMACION = "AsignacionConfirmadaPorHabilitacion"
TIPOS_TRABAJOS_IGNORAR = {TIPO_TRABAJO_ASIGNADO, TIPO_TRABAJO_RECHAZADO}
TIPOS_RECHAZO = {TIPO_RECHAZO, TIPO_RECHAZO_REGLA}

FabricaUoW = Callable[[], UnidadDeTrabajo]


def _str(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, bytes):
        return valor.decode("utf-8")
    return str(valor)


def _long(valor) -> Optional[int]:
    if valor is None:
        return None
    if hasattr(valor, "timestamp"):
        return int(valor.timestamp() * 1000)
    return int(valor)


def _lista(valor) -> tuple:
    if not valor:
        return ()
    return tuple(_str(x) for x in valor)


def _bool(valor, default: bool = False) -> bool:
    if valor is None:
        return default
    return bool(valor)


def descomponer(payload: dict) -> tuple[dict, dict]:
    """Sobre CloudEvents + data. data vacío si el mensaje no trae payload anidado."""
    if not payload:
        return {}, {}
    data = payload.get("data")
    if data is None:
        return payload, {}
    if not isinstance(data, dict):
        return payload, {}
    return payload, data


def tipo_de(payload: dict) -> str:
    sobre, _ = descomponer(payload)
    return _str(sobre.get("type"))


def id_de(payload: dict) -> str:
    sobre, _ = descomponer(payload)
    return _str(sobre.get("id"))


class ServicioProyecciones:
    def __init__(self, fabrica_uow: FabricaUoW) -> None:
        self._fabrica = fabrica_uow

    def aplicar_regla_partner(self, payload: dict) -> None:
        if tipo_de(payload) != TIPO_REGLA:
            return
        _, data = descomponer(payload)
        evento_id = id_de(payload)
        vigencia_hasta = _long(data.get("vigencia_hasta"))
        if vigencia_abierta(vigencia_hasta):
            vigencia_hasta = None
        regla = ProyeccionReglaPartner(
            partner_id=_str(data.get("partner_id")),
            red_homologada=_lista(data.get("red_homologada")),
            activo=_bool(data.get("activo"), True),
            vigente_hasta=vigencia_hasta,
        )
        uow = self._fabrica()
        try:
            if uow.eventos_procesados.ya_procesado(evento_id):
                uow.commit()
                return
            uow.reglas.upsert(regla)
            uow.eventos_procesados.marcar(evento_id)
            uow.commit()
        except Exception:
            uow.rollback()
            raise

    def aplicar_habilitacion(self, payload: dict) -> None:
        if tipo_de(payload) != TIPO_HABILITACION:
            return
        _, data = descomponer(payload)
        evento_id = id_de(payload)
        vigencia_hasta = _long(data.get("vigente_hasta"))
        if vigencia_abierta(vigencia_hasta):
            vigencia_hasta = None
        hab = ProyeccionHabilitacion(
            proveedor_id=_str(data.get("proveedor_id")),
            estado=_str(data.get("estado")),
            categorias=_lista(data.get("categorias")),
            ciudades=_lista(data.get("ciudades")),
            vigente_hasta=vigencia_hasta,
        )
        uow = self._fabrica()
        try:
            if uow.eventos_procesados.ya_procesado(evento_id):
                uow.commit()
                return
            uow.habilitaciones.upsert(hab)
            uow.eventos_procesados.marcar(evento_id)
            uow.commit()
        except Exception:
            uow.rollback()
            raise


class ServicioAsignacion:
    def __init__(
        self,
        fabrica_uow: FabricaUoW,
        publicador: PublicadorTrabajoAsignado,
        reloj: Reloj,
    ) -> None:
        self._fabrica = fabrica_uow
        self._publicador = publicador
        self._reloj = reloj

    def consultar(self, trabajo_id: str) -> Optional[Asignacion]:
        uow = self._fabrica()
        try:
            return uow.asignaciones.obtener_por_trabajo(trabajo_id)
        finally:
            uow.rollback()

    def on_evento_trabajos(self, payload: dict) -> ResultadoEmparejamiento:
        tipo = tipo_de(payload)
        if tipo in TIPOS_TRABAJOS_IGNORAR:
            return ResultadoEmparejamiento(
                ignorado=True, motivo_ignorado=f"tipo {tipo} propio/ajeno"
            )
        if tipo != TIPO_TRABAJO_CREADO:
            return ResultadoEmparejamiento(
                ignorado=True, motivo_ignorado=f"tipo filtrado: {tipo or '(vacio)'}"
            )
        return self._asignar_trabajo_creado(payload)

    def _asignar_trabajo_creado(self, payload: dict) -> ResultadoEmparejamiento:
        sobre, data = descomponer(payload)
        evento_id = id_de(payload)
        trabajo = TrabajoParaAsignar(
            trabajo_id=_str(data.get("trabajo_id")),
            partner_id=_str(data.get("partner_id")),
            mercado_id=_str(data.get("mercado_id")),
            categoria=_str(data.get("categoria")),
            urgencia=_str(data.get("urgencia")),
            ciudad=_str(data.get("ciudad")),
            sla_minutos=int(data.get("sla_minutos") or 0),
            ocurrido_en=_long(sobre.get("time")) or 0,
            correlacion_id=_str(sobre.get("correlation_id")),
            evento_id=evento_id,
            requiere_aprobacion=_bool(data.get("requiere_aprobacion"), False),
        )
        uow = self._fabrica()
        try:
            if uow.eventos_procesados.ya_procesado(evento_id):
                existente = uow.asignaciones.obtener_por_trabajo(trabajo.trabajo_id)
                uow.commit()
                return ResultadoEmparejamiento(asignacion=existente, ya_procesado=True)

            ahora = self._reloj.ahora_ms()
            regla = uow.reglas.obtener(trabajo.partner_id)
            habilitaciones = list(uow.habilitaciones.listar())
            asignacion, evento, fallida = emparejar(
                trabajo,
                regla,
                habilitaciones,
                ahora_ms=ahora,
                asignacion_id=str(uuid.uuid4()),
                evento_salida_id=str(uuid.uuid4()),
            )
            uow.eventos_procesados.marcar(evento_id)
            if fallida is not None:
                uow.fallidas.guardar(fallida)
                uow.commit()
                log.warning(
                    "sin_candidatos trabajo_id=%s correlation_id=%s",
                    trabajo.trabajo_id,
                    trabajo.correlacion_id,
                )
                return ResultadoEmparejamiento(fallida=fallida)

            assert asignacion is not None and evento is not None
            uow.asignaciones.guardar(asignacion)
            uow.commit()
        except Exception:
            uow.rollback()
            raise

        self._publicador.publicar(evento)
        return ResultadoEmparejamiento(asignacion=asignacion, evento=evento)

    def on_rechazo_habilitacion(self, payload: dict) -> ResultadoEmparejamiento:
        if tipo_de(payload) not in TIPOS_RECHAZO:
            return ResultadoEmparejamiento(
                ignorado=True, motivo_ignorado=f"tipo filtrado: {tipo_de(payload)}"
            )
        _, data = descomponer(payload)
        evento_id = id_de(payload)
        asignacion_id = _str(data.get("asignacion_id"))
        trabajo_id = _str(data.get("trabajo_id"))
        uow = self._fabrica()
        try:
            if uow.eventos_procesados.ya_procesado(evento_id):
                existente = uow.asignaciones.obtener_por_trabajo(trabajo_id)
                uow.commit()
                return ResultadoEmparejamiento(asignacion=existente, ya_procesado=True)

            asignacion = uow.asignaciones.obtener_por_id(asignacion_id)
            if asignacion is None:
                asignacion = uow.asignaciones.obtener_por_trabajo(trabajo_id)
            if asignacion is not None:
                asignacion.marcar_rechazado()
                uow.asignaciones.guardar(asignacion)
            uow.eventos_procesados.marcar(evento_id)
            uow.commit()
            log.info(
                "asignacion_rechazada asignacion_id=%s trabajo_id=%s (sin reasignar)",
                asignacion_id,
                trabajo_id,
            )
            return ResultadoEmparejamiento(asignacion=asignacion)
        except Exception:
            uow.rollback()
            raise

    def on_confirmacion_habilitacion(self, payload: dict) -> ResultadoEmparejamiento:
        if tipo_de(payload) != TIPO_CONFIRMACION:
            return ResultadoEmparejamiento(
                ignorado=True, motivo_ignorado=f"tipo filtrado: {tipo_de(payload)}"
            )
        _, data = descomponer(payload)
        evento_id = id_de(payload)
        asignacion_id = _str(data.get("asignacion_id"))
        trabajo_id = _str(data.get("trabajo_id"))
        uow = self._fabrica()
        try:
            if uow.eventos_procesados.ya_procesado(evento_id):
                existente = uow.asignaciones.obtener_por_trabajo(trabajo_id)
                uow.commit()
                return ResultadoEmparejamiento(asignacion=existente, ya_procesado=True)

            asignacion = uow.asignaciones.obtener_por_id(asignacion_id)
            if asignacion is None:
                asignacion = uow.asignaciones.obtener_por_trabajo(trabajo_id)
            if asignacion is not None:
                asignacion.marcar_confirmado(_long(data.get("verificado_en")))
                uow.asignaciones.guardar(asignacion)
            uow.eventos_procesados.marcar(evento_id)
            uow.commit()
            log.info(
                "asignacion_confirmada asignacion_id=%s trabajo_id=%s",
                asignacion_id,
                trabajo_id,
            )
            return ResultadoEmparejamiento(asignacion=asignacion)
        except Exception:
            uow.rollback()
            raise
