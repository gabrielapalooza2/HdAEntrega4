"""Proyeccion local de las reglas de partner.

Es la pieza que sostiene DOS escenarios de calidad a la vez:

  MODIFICABILIDAD  toda la variabilidad entre aseguradoras vive aqui COMO DATO.
                   Agregar un partner nuevo, o cambiarle la cobertura, no toca
                   una sola linea de codigo. Por eso la regla dura del proyecto
                   es "cero condicionales por partner": no hay ningun
                   `if partner_id == ...` porque no hace falta.

  DISPONIBILIDAD   validar un trabajo lee ESTA TABLA, no llama al Motor de
                   Reglas por red. Si ese servicio esta caido, aqui sigue
                   estando la ultima regla conocida y Orquestacion sigue
                   operando.
Este modulo es SOLO el repositorio: el SQL que lee y escribe la proyeccion. La
regla en si -con su comportamiento de negocio- vive en dominio/regla_partner.py,
porque decidir si una categoria esta cubierta no es un detalle de persistencia.
"""
import logging

import psycopg

from orquestacion.dominio.regla_partner import ReglaDePartner

logger = logging.getLogger(__name__)


def guardar(cur: psycopg.Cursor, regla: ReglaDePartner) -> bool:
    """Upsert con GUARDA DE VERSION. Devuelve True si la fila cambio.

    El `WHERE ... < EXCLUDED.regla_version` del DO UPDATE es el segundo
    mecanismo de idempotencia, y resuelve un problema DISTINTO al de
    mensajes_procesados:

      mensajes_procesados  ->  REPETICION: el mismo mensaje dos veces
      guarda de version    ->  DESORDEN:   un mensaje viejo llegando tarde

    Hace falta el segundo porque la suscripcion a evt.partners es Shared: con
    varias replicas consumiendo, dos versiones del mismo partner pueden
    procesarse en paralelo y terminar en orden invertido. Sin esta guarda, la
    v3 reentregada tarde pisaria la v4 y el estado RETROCEDERIA.

    Con la guarda, aplicar las versiones en cualquier orden converge al mismo
    resultado: la mayor gana.
    """
    cur.execute(
        """
        INSERT INTO proyeccion_regla_partner
              (partner_id, regla_version, activo, sla_minutos,
               categorias_cubiertas, monto_max, moneda, actualizado_en)
        VALUES (%s, %s, %s, %s, %s, %s, %s, now())
        ON CONFLICT (partner_id) DO UPDATE SET
              regla_version        = EXCLUDED.regla_version,
              activo               = EXCLUDED.activo,
              sla_minutos          = EXCLUDED.sla_minutos,
              categorias_cubiertas = EXCLUDED.categorias_cubiertas,
              monto_max            = EXCLUDED.monto_max,
              moneda               = EXCLUDED.moneda,
              actualizado_en       = now()
        WHERE proyeccion_regla_partner.regla_version < EXCLUDED.regla_version
        """,
        (regla.partner_id, regla.regla_version, regla.activo, regla.sla_minutos,
         list(regla.categorias_cubiertas), regla.monto_max, regla.moneda),
    )
    return cur.rowcount == 1


def buscar(cur: psycopg.Cursor, partner_id: str) -> ReglaDePartner | None:
    """Devuelve la regla de un partner, o None si nunca llego ninguna.

    None NO es un error tecnico: significa que este servicio todavia no ha visto
    a ese partner. Es una causa legitima de rechazo, y el dominio la trata como
    tal.
    """
    cur.execute(
        "SELECT partner_id, regla_version, activo, sla_minutos, "
        "       categorias_cubiertas, monto_max, moneda "
        "FROM proyeccion_regla_partner WHERE partner_id = %s",
        (partner_id,),
    )
    fila = cur.fetchone()
    if fila is None:
        return None
    return ReglaDePartner(
        partner_id=fila[0], regla_version=fila[1], activo=fila[2],
        sla_minutos=fila[3], categorias_cubiertas=tuple(fila[4]),
        monto_max=fila[5], moneda=fila[6],
    )
