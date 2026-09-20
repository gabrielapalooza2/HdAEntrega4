"""Paso de Motor en la saga coreografiada de asignacion.

Reacciona a TrabajoAsignado. Nadie le ordena el siguiente paso: publica un
hecho sobre la red homologada (dato autoritativo del agregado Partner).
Orquestacion solo anota el saga log; Acreditacion reacciona al hecho.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from motor_reglas.config.db import db
from motor_reglas.modulos.partners.dominio.excepciones import PartnerNoExiste
from motor_reglas.modulos.partners.infraestructura.dto import MensajeProcesado
from motor_reglas.modulos.partners.infraestructura.outbox import registrar_en_outbox
from motor_reglas.modulos.partners.infraestructura.repositorios import (
    RepositorioPartnersSQLAlchemy,
)

TOPICO_EVT_ASIGNACIONES = "persistent://hda/poc/evt.asignaciones"


@dataclass(frozen=True)
class VerificarAsignacion:
    trabajo_id: str
    asignacion_id: str
    proveedor_id: str
    partner_id: str
    correlation_id: str
    mensaje_id: str


def _ya_procesado(mensaje_id: str) -> bool:
    if not mensaje_id:
        return False
    return (
        db.session.query(MensajeProcesado)
        .filter_by(mensaje_id=mensaje_id)
        .one_or_none()
        is not None
    )


def _marcar_procesado(mensaje_id: str) -> None:
    if not mensaje_id:
        return
    db.session.add(
        MensajeProcesado(mensaje_id=mensaje_id, procesado_en=datetime.utcnow())
    )


def _payload(*, trabajo_id, asignacion_id, proveedor_id, partner_id,
             regla_version, motivo) -> dict:
    return {
        "trabajo_id": trabajo_id,
        "asignacion_id": asignacion_id,
        "proveedor_id": proveedor_id,
        "partner_id": partner_id,
        "regla_version": regla_version,
        "motivo": motivo,
        "verificado_en": int(datetime.now(timezone.utc).timestamp() * 1000),
    }


def ejecutar(comando: VerificarAsignacion) -> str:
    """Devuelve ACEPTADA, RECHAZADA o DUPLICADO. Escribe outbox + idempotencia."""
    if _ya_procesado(comando.mensaje_id):
        return "DUPLICADO"

    aceptada = False
    motivo = "PARTNER_DESCONOCIDO"
    version = 0
    partner_id = comando.partner_id or ""

    try:
        partner_uuid = uuid.UUID(str(comando.partner_id))
        partner = RepositorioPartnersSQLAlchemy().obtener_por_id(partner_uuid)
        aceptada, motivo, version = partner.evaluar_asignacion(comando.proveedor_id)
        partner_id = str(partner.id)
    except (ValueError, PartnerNoExiste):
        aceptada = False
        motivo = "PARTNER_DESCONOCIDO"
        version = 0

    tipo = (
        "AsignacionAceptadaPorReglaPartner"
        if aceptada
        else "AsignacionRechazadaPorReglaPartner"
    )
    registrar_en_outbox(
        tipo=tipo,
        clave=comando.trabajo_id,
        payload=_payload(
            trabajo_id=comando.trabajo_id,
            asignacion_id=comando.asignacion_id,
            proveedor_id=comando.proveedor_id,
            partner_id=partner_id,
            regla_version=version,
            motivo="" if aceptada else motivo,
        ),
        correlation_id=comando.correlation_id,
        topico=TOPICO_EVT_ASIGNACIONES,
    )
    _marcar_procesado(comando.mensaje_id)
    db.session.commit()
    return "ACEPTADA" if aceptada else "RECHAZADA"
