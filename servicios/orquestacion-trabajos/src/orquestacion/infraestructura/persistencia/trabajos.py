"""Proyeccion de trabajos: el lado de LECTURA de CQRS.

Es estado DERIVADO. Si se borrara entera, se podria reconstruir releyendo
eventos_trabajo. La fuente de verdad es el event store; esto es una cache
consultable.

Existe porque responder "en que estado va el trabajo X" reproduciendo N eventos
es caro, y la API tiene que contestar en una sola consulta sin abrir una
transaccion sobre el agregado.
"""
import logging
from dataclasses import dataclass
from datetime import datetime

import psycopg

from orquestacion.dominio import eventos as ev
from orquestacion.dominio.objetos_valor import EstadoTrabajo
from orquestacion.dominio.trabajo import Trabajo

logger = logging.getLogger(__name__)

ESTADOS_TERMINALES = ("ASIGNADO", "RECHAZADO", "ESCALADO_MANUAL")


@dataclass(frozen=True)
class VistaTrabajo:
    """Lo que la API devuelve. Plano y sin comportamiento a proposito: el lado
    de lectura no toma decisiones."""
    trabajo_id: str
    estado: str
    partner_id: str
    proveedor_id: str | None
    categoria: str
    zona: str
    sla_minutos: int | None
    vence_en: datetime | None
    intentos: int
    proveedores_excluidos: tuple[str, ...]
    secuencia: int
    actualizado_en: datetime


def sincronizar(cur: psycopg.Cursor, trabajo: Trabajo) -> None:
    """Escribe el estado derivado del agregado.

    Se le pasa el agregado YA reconstruido en vez de aplicar evento por evento:
    el agregado ya sabe reproducir su historia, y duplicar esa logica aqui daria
    dos implementaciones del mismo calculo que se desincronizan.

    ─── GUARDA DE VERSION ────────────────────────────────────────────────
    El `WHERE ... < EXCLUDED.secuencia` es el mismo mecanismo que en la
    proyeccion de reglas, contra el mismo problema: el DESORDEN. Si dos
    escrituras del mismo trabajo se aplicaran fuera de orden, la vieja pisaria a
    la nueva y el estado RETROCEDERIA. Con la guarda, la mayor gana y el orden
    de llegada deja de importar.
    ───────────────────────────────────────────────────────────────────────
    """
    cur.execute(
        """
        INSERT INTO proyeccion_trabajo
              (trabajo_id, estado, partner_id, proveedor_id, categoria, zona,
               sla_minutos, vence_en, intentos, proveedores_excluidos,
               secuencia, actualizado_en)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
        ON CONFLICT (trabajo_id) DO UPDATE SET
              estado                = EXCLUDED.estado,
              proveedor_id          = EXCLUDED.proveedor_id,
              sla_minutos           = EXCLUDED.sla_minutos,
              vence_en              = EXCLUDED.vence_en,
              intentos              = EXCLUDED.intentos,
              proveedores_excluidos = EXCLUDED.proveedores_excluidos,
              secuencia             = EXCLUDED.secuencia,
              actualizado_en        = now()
        WHERE proyeccion_trabajo.secuencia < EXCLUDED.secuencia
        """,
        (trabajo.trabajo_id, trabajo.estado.value, trabajo.partner_id,
         trabajo.proveedor_id, trabajo.categoria, trabajo.zona,
         trabajo.sla_minutos, trabajo.vence_en, trabajo.intentos,
         list(trabajo.proveedores_excluidos), trabajo.secuencia),
    )


def buscar(cur: psycopg.Cursor, trabajo_id: str) -> VistaTrabajo | None:
    cur.execute(
        "SELECT trabajo_id, estado, partner_id, proveedor_id, categoria, zona, "
        "       sla_minutos, vence_en, intentos, proveedores_excluidos, "
        "       secuencia, actualizado_en "
        "FROM proyeccion_trabajo WHERE trabajo_id = %s",
        (trabajo_id,),
    )
    fila = cur.fetchone()
    if fila is None:
        return None
    return VistaTrabajo(
        trabajo_id=str(fila[0]), estado=fila[1], partner_id=fila[2],
        proveedor_id=fila[3], categoria=fila[4], zona=fila[5],
        sla_minutos=fila[6], vence_en=fila[7], intentos=fila[8],
        proveedores_excluidos=tuple(fila[9]), secuencia=fila[10],
        actualizado_en=fila[11],
    )


def vencidos(cur: psycopg.Cursor, ahora: datetime, limite: int = 100) -> list[str]:
    """Trabajos con el SLA vencido que siguen en estado no terminal.

    Usa el indice PARCIAL ix_trabajo_sla_pendiente: los terminales ni siquiera
    entran al indice, asi que el costo del barrido no crece con el historico.
    """
    cur.execute(
        f"SELECT trabajo_id FROM proyeccion_trabajo "
        f"WHERE vence_en < %s AND estado NOT IN {ESTADOS_TERMINALES} "
        f"ORDER BY vence_en LIMIT %s",
        (ahora, limite),
    )
    return [str(fila[0]) for fila in cur.fetchall()]
