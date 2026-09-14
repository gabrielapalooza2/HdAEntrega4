"""Modelos SQLAlchemy (DBO) de Acreditacion."""
from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, JSON, String

from .db import Base


class ProveedorDBO(Base):
    __tablename__ = "proveedores"
    id = Column(String(36), primary_key=True)
    nombre = Column(String(200), nullable=False, default="")
    tipo_proveedor = Column(String(30), nullable=False)
    estado = Column(String(20), nullable=False)
    categorias = Column(JSON, nullable=False, default=list)
    ciudades = Column(JSON, nullable=False, default=list)
    motivo = Column(String(500), nullable=True)
    vigente_hasta = Column(DateTime, nullable=True)
    fecha_creacion = Column(DateTime, nullable=False)
    fecha_actualizacion = Column(DateTime, nullable=False)


class EventoProcesadoDBO(Base):
    """Idempotencia de mensajeria (Pulsar entrega at-least-once)."""
    __tablename__ = "eventos_procesados"
    evento_id = Column(String(36), primary_key=True)
    procesado_en = Column(DateTime, nullable=False)


class ValidacionPreviaDBO(Base):
    """Cache de validaciones externas. Escenario 8."""
    __tablename__ = "validaciones_previas"
    proveedor_id = Column(String(36), primary_key=True)
    fuente = Column(String(50), primary_key=True)
    aprobado = Column(Boolean, nullable=False)
    motivo = Column(String(500), nullable=True)
    verificado_en = Column(DateTime, nullable=False)
