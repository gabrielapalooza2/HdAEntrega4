"""Deduplicacion de mensajes entrantes (Pulsar entrega at-least-once)."""
from __future__ import annotations
from datetime import datetime, timezone

from .dto import EventoProcesadoDBO


def ya_procesado(session, evento_id: str) -> bool:
    return session.query(EventoProcesadoDBO).filter_by(evento_id=evento_id).one_or_none() is not None


def marcar_procesado(session, evento_id: str):
    session.add(EventoProcesadoDBO(evento_id=evento_id, procesado_en=datetime.now(timezone.utc)))
