from __future__ import annotations

from typing import Optional, Sequence

from dominio.modelo import (
    DATACONTENTTYPE,
    ORIGEN_HABILITACION_PROYECCION_LOCAL,
    PRODUCTOR,
    SPECVERSION,
    TIPO_TRABAJO_ASIGNADO,
    Asignacion,
    AsignacionFallida,
    ProyeccionHabilitacion,
    ProyeccionReglaPartner,
    TrabajoAsignado,
    TrabajoParaAsignar,
    aplicar_red_homologada,
    candidatos_habilitados,
    elegir_proveedor_determinista,
    minutos_a_millis,
)


def emparejar(
    trabajo: TrabajoParaAsignar,
    regla: Optional[ProyeccionReglaPartner],
    habilitaciones: Sequence[ProyeccionHabilitacion],
    ahora_ms: int,
    asignacion_id: str,
    evento_salida_id: str,
) -> tuple[Optional[Asignacion], Optional[TrabajoAsignado], Optional[AsignacionFallida]]:
    """Asignación optimista solo con proyecciones locales. Cero llamadas a otros MS."""
    verificado_en = ahora_ms
    red: Sequence[str] = ()
    if regla is not None:
        red = regla.red_homologada

    ids = candidatos_habilitados(
        habilitaciones,
        categoria=trabajo.categoria,
        ciudad=trabajo.ciudad,
        ahora_ms=ahora_ms,
    )
    ids = aplicar_red_homologada(ids, red)
    proveedor_id = elegir_proveedor_determinista(ids)

    if proveedor_id is None:
        fallida = AsignacionFallida(
            trabajo_id=trabajo.trabajo_id,
            correlacion_id=trabajo.correlacion_id,
            motivo="SIN_CANDIDATOS",
            ocurrido_en=ahora_ms,
            evento_id=trabajo.evento_id,
        )
        return None, None, fallida

    base_ms = trabajo.ocurrido_en if trabajo.ocurrido_en else ahora_ms
    sla_vence_en = base_ms + minutos_a_millis(trabajo.sla_minutos)

    asignacion = Asignacion(
        asignacion_id=asignacion_id,
        trabajo_id=trabajo.trabajo_id,
        proveedor_id=proveedor_id,
        partner_id=trabajo.partner_id,
        correlacion_id=trabajo.correlacion_id,
        sla_vence_en=sla_vence_en,
        verificado_en=verificado_en,
        ocurrido_en=ahora_ms,
        origen_habilitacion=ORIGEN_HABILITACION_PROYECCION_LOCAL,
    )
    evento = TrabajoAsignado(
        id=evento_salida_id,
        time=ahora_ms,
        ingestion=ahora_ms,
        specversion=SPECVERSION,
        type=TIPO_TRABAJO_ASIGNADO,
        datacontenttype=DATACONTENTTYPE,
        service_name=PRODUCTOR,
        correlation_id=trabajo.correlacion_id,
        trabajo_id=trabajo.trabajo_id,
        asignacion_id=asignacion_id,
        proveedor_id=proveedor_id,
        partner_id=trabajo.partner_id,
        sla_vence_en=sla_vence_en,
        origen_habilitacion=ORIGEN_HABILITACION_PROYECCION_LOCAL,
    )
    return asignacion, evento, None
