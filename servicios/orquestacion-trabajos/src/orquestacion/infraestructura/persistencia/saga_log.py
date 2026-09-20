"""Saga log de la asignacion de un trabajo. SQL crudo, psycopg3, sin ORM.

COORDINADOR DE SAGAS
--------------------
Orquestacion de trabajos ES el coordinador de sagas. No es un orquestador
que mande comandos a los demas: es el dueno de `trabajo_id`, del event store
del agregado Trabajo y de las tablas `saga_asignacion` / `saga_paso`. La
rubrica pide un coordinador + saga log; no pide un quinto microservicio.

El campo `coordinador` queda en `orquestacion-trabajos` para que el tutor
lo vea en SQL y en GET /sagas, sin desplegar un proceso aparte.

Por que vive AQUI y no en un microservicio dedicado
---------------------------------------------------
La saga es el ciclo de respuesta de UN trabajo. Su identidad es trabajo_id,
que ya es la PK del event store. Este servicio produce o consume los hitos
de los cuatro participantes (TrabajoCreado lo produce; TrabajoAsignado, el
veredicto de Motor y la confirmacion/rechazo de habilitacion los consume).

El log NO dirige: no publica comandos. Es una proyeccion para operar y para
que un tutor inspeccione el workflow con SQL. La coreografia sigue siendo
eventos entre Orquestacion, Motor, Emparejamiento y Acreditacion.

Por que SQL expresivo y no un ORM
---------------------------------
El material de la entrega es almacenamiento y transacciones. El tutor tiene
que poder copiar las consultas de docs/entrega5 y ver pasos y compensaciones.
Un INSERT ... SELECT con CTE y un UPSERT con CASE deja esa logica en el
motor, no escondida en una sesion.
"""
from __future__ import annotations

import json
from typing import Any

import psycopg

from orquestacion.infraestructura.persistencia.bd import _como_uuid

# Nombre del coordinador de sagas (este servicio). No es un quinto contenedor.
SERVICIO_COORDINADOR = "orquestacion-trabajos"
SERVICIO_ORQUESTACION = SERVICIO_COORDINADOR
SERVICIO_EMPAREJAMIENTO = "emparejamiento-asignacion"
SERVICIO_ACREDITACION = "acreditacion-habilitacion"
SERVICIO_MOTOR = "motor-reglas-partner"


def _json(valor: dict[str, Any] | None) -> str:
    return json.dumps(valor or {}, ensure_ascii=False, default=str)


def anexar_paso(cur: psycopg.Cursor, *, saga_id: str, servicio: str,
                tipo_mensaje: str, rol: str, resultado: str,
                payload: dict[str, Any] | None = None) -> int:
    """Append-only. La secuencia la calcula PostgreSQL, no Python."""
    cur.execute(
        """
        WITH actual AS (
            SELECT COALESCE(MAX(secuencia), 0) AS ultima
              FROM saga_paso
             WHERE saga_id = %s::uuid
        )
        INSERT INTO saga_paso (
            saga_id, secuencia, servicio, tipo_mensaje, rol, resultado, payload
        )
        SELECT %s::uuid, actual.ultima + 1, %s, %s, %s, %s, %s::jsonb
          FROM actual
        RETURNING secuencia
        """,
        (_como_uuid(saga_id), _como_uuid(saga_id), servicio, tipo_mensaje,
         rol, resultado, _json(payload)),
    )
    return int(cur.fetchone()[0])


def _upsert_cabecera(cur: psycopg.Cursor, *, saga_id: str, correlation_id: str,
                     estado: str, paso_actual: str, partner_id: str | None = None,
                     proveedor_id: str | None = None, asignacion_id: str | None = None,
                     motivo: str | None = None, cerrar: bool = False) -> None:
    """Una fila por saga. No reabre COMPLETADA/FALLIDA con un paso viejo."""
    cur.execute(
        """
        INSERT INTO saga_asignacion (
            saga_id, correlation_id, estado, partner_id, proveedor_id,
            asignacion_id, paso_actual, motivo, coordinador, iniciada_en,
            actualizada_en, cerrada_en
        )
        VALUES (
            %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, now(), now(),
            CASE WHEN %s THEN now() ELSE NULL END
        )
        ON CONFLICT (saga_id) DO UPDATE SET
            correlation_id = COALESCE(EXCLUDED.correlation_id, saga_asignacion.correlation_id),
            partner_id     = COALESCE(EXCLUDED.partner_id, saga_asignacion.partner_id),
            proveedor_id   = COALESCE(EXCLUDED.proveedor_id, saga_asignacion.proveedor_id),
            asignacion_id  = COALESCE(EXCLUDED.asignacion_id, saga_asignacion.asignacion_id),
            motivo         = COALESCE(EXCLUDED.motivo, saga_asignacion.motivo),
            paso_actual    = EXCLUDED.paso_actual,
            estado         = CASE
                WHEN saga_asignacion.estado IN ('COMPLETADA', 'FALLIDA')
                THEN saga_asignacion.estado
                ELSE EXCLUDED.estado
            END,
            actualizada_en = now(),
            cerrada_en     = CASE
                WHEN saga_asignacion.estado IN ('COMPLETADA', 'FALLIDA')
                THEN saga_asignacion.cerrada_en
                WHEN EXCLUDED.cerrada_en IS NOT NULL
                THEN EXCLUDED.cerrada_en
                ELSE saga_asignacion.cerrada_en
            END
        """,
        (_como_uuid(saga_id), correlation_id, estado, partner_id, proveedor_id,
         asignacion_id, paso_actual, motivo, SERVICIO_COORDINADOR, cerrar),
    )


def iniciar(cur: psycopg.Cursor, *, trabajo_id: str, correlation_id: str,
            partner_id: str) -> None:
    _upsert_cabecera(
        cur, saga_id=trabajo_id, correlation_id=correlation_id,
        estado="INICIADA", paso_actual="TrabajoCreado", partner_id=partner_id,
    )
    anexar_paso(
        cur, saga_id=trabajo_id, servicio=SERVICIO_ORQUESTACION,
        tipo_mensaje="TrabajoCreado", rol="PASO", resultado="OK",
        payload={"partner_id": partner_id},
    )


def marcar_asignacion_optimista(cur: psycopg.Cursor, *, trabajo_id: str,
                                correlation_id: str, proveedor_id: str,
                                asignacion_id: str) -> None:
    _upsert_cabecera(
        cur, saga_id=trabajo_id, correlation_id=correlation_id,
        estado="EN_CURSO", paso_actual="TrabajoAsignado",
        proveedor_id=proveedor_id, asignacion_id=asignacion_id,
    )
    anexar_paso(
        cur, saga_id=trabajo_id, servicio=SERVICIO_EMPAREJAMIENTO,
        tipo_mensaje="TrabajoAsignado", rol="PASO", resultado="OK",
        payload={"proveedor_id": proveedor_id, "asignacion_id": asignacion_id},
    )


def marcar_regla_aceptada(cur: psycopg.Cursor, *, trabajo_id: str,
                          correlation_id: str, proveedor_id: str,
                          asignacion_id: str, partner_id: str = "",
                          regla_version: int = 0) -> None:
    """Paso del Motor: la red homologada autoritativa admite al proveedor."""
    _upsert_cabecera(
        cur, saga_id=trabajo_id, correlation_id=correlation_id,
        estado="EN_CURSO", paso_actual="AsignacionAceptadaPorReglaPartner",
        partner_id=partner_id or None, proveedor_id=proveedor_id,
        asignacion_id=asignacion_id,
    )
    anexar_paso(
        cur, saga_id=trabajo_id, servicio=SERVICIO_MOTOR,
        tipo_mensaje="AsignacionAceptadaPorReglaPartner",
        rol="PASO", resultado="OK",
        payload={"proveedor_id": proveedor_id, "asignacion_id": asignacion_id,
                 "partner_id": partner_id, "regla_version": regla_version},
    )


def marcar_confirmada(cur: psycopg.Cursor, *, trabajo_id: str,
                      correlation_id: str, proveedor_id: str,
                      asignacion_id: str, estado_real: str) -> None:
    _upsert_cabecera(
        cur, saga_id=trabajo_id, correlation_id=correlation_id,
        estado="COMPLETADA", paso_actual="AsignacionConfirmadaPorHabilitacion",
        proveedor_id=proveedor_id, asignacion_id=asignacion_id, cerrar=True,
    )
    anexar_paso(
        cur, saga_id=trabajo_id, servicio=SERVICIO_ACREDITACION,
        tipo_mensaje="AsignacionConfirmadaPorHabilitacion",
        rol="CIERRE", resultado="CONFIRMADO",
        payload={"proveedor_id": proveedor_id, "asignacion_id": asignacion_id,
                 "estado_real": estado_real},
    )


def marcar_compensacion(cur: psycopg.Cursor, *, trabajo_id: str,
                        correlation_id: str, proveedor_id: str,
                        asignacion_id: str, motivo: str,
                        estado_trabajo: str,
                        tipo_mensaje: str = "AsignacionRechazadaPorHabilitacion",
                        servicio: str = SERVICIO_ACREDITACION) -> None:
    estado_saga = "FALLIDA" if estado_trabajo == "ESCALADO_MANUAL" else "COMPENSADA"
    _upsert_cabecera(
        cur, saga_id=trabajo_id, correlation_id=correlation_id,
        estado=estado_saga, paso_actual=tipo_mensaje,
        proveedor_id=proveedor_id, asignacion_id=asignacion_id, motivo=motivo,
        cerrar=True,
    )
    anexar_paso(
        cur, saga_id=trabajo_id, servicio=servicio,
        tipo_mensaje=tipo_mensaje,
        rol="COMPENSACION", resultado="RECHAZO",
        payload={"proveedor_id": proveedor_id, "asignacion_id": asignacion_id,
                 "motivo": motivo},
    )
    anexar_paso(
        cur, saga_id=trabajo_id, servicio=SERVICIO_ORQUESTACION,
        tipo_mensaje="ProveedorDescartado",
        rol="COMPENSACION", resultado="COMPENSADO",
        payload={"proveedor_id": proveedor_id, "estado_trabajo": estado_trabajo},
    )


def obtener(cur: psycopg.Cursor, saga_id: str) -> dict | None:
    cur.execute(
        """
        SELECT saga_id, correlation_id, estado, partner_id, proveedor_id,
               asignacion_id, paso_actual, motivo, coordinador, iniciada_en,
               actualizada_en, cerrada_en,
               EXTRACT(EPOCH FROM (COALESCE(cerrada_en, now()) - iniciada_en))
                 AS duracion_segundos
          FROM saga_asignacion
         WHERE saga_id = %s::uuid
        """,
        (_como_uuid(saga_id),),
    )
    cab = cur.fetchone()
    if cab is None:
        return None
    cur.execute(
        """
        SELECT secuencia, servicio, tipo_mensaje, rol, resultado, payload, ocurrido_en
          FROM saga_paso
         WHERE saga_id = %s::uuid
         ORDER BY secuencia
        """,
        (_como_uuid(saga_id),),
    )
    pasos = [
        {
            "secuencia": fila[0],
            "servicio": fila[1],
            "tipo_mensaje": fila[2],
            "rol": fila[3],
            "resultado": fila[4],
            "payload": fila[5],
            "ocurrido_en": fila[6].isoformat() if fila[6] else None,
        }
        for fila in cur.fetchall()
    ]
    return {
        "saga_id": str(cab[0]),
        "correlation_id": cab[1],
        "estado": cab[2],
        "partner_id": cab[3],
        "proveedor_id": cab[4],
        "asignacion_id": cab[5],
        "paso_actual": cab[6],
        "motivo": cab[7],
        "coordinador": cab[8] or SERVICIO_COORDINADOR,
        "iniciada_en": cab[9].isoformat() if cab[9] else None,
        "actualizada_en": cab[10].isoformat() if cab[10] else None,
        "cerrada_en": cab[11].isoformat() if cab[11] else None,
        "duracion_segundos": float(cab[12]) if cab[12] is not None else None,
        "pasos": pasos,
    }


def listar(cur: psycopg.Cursor, estado: str | None = None, limite: int = 50) -> list[dict]:
    if estado:
        cur.execute(
            """
            SELECT saga_id, estado, partner_id, proveedor_id, paso_actual,
                   coordinador, iniciada_en, cerrada_en
              FROM saga_asignacion
             WHERE estado = %s
             ORDER BY iniciada_en DESC
             LIMIT %s
            """,
            (estado, limite),
        )
    else:
        cur.execute(
            """
            SELECT saga_id, estado, partner_id, proveedor_id, paso_actual,
                   coordinador, iniciada_en, cerrada_en
              FROM saga_asignacion
             ORDER BY iniciada_en DESC
             LIMIT %s
            """,
            (limite,),
        )
    return [
        {
            "saga_id": str(fila[0]),
            "estado": fila[1],
            "partner_id": fila[2],
            "proveedor_id": fila[3],
            "paso_actual": fila[4],
            "coordinador": fila[5] or SERVICIO_COORDINADOR,
            "iniciada_en": fila[6].isoformat() if fila[6] else None,
            "cerrada_en": fila[7].isoformat() if fila[7] else None,
        }
        for fila in cur.fetchall()
    ]
