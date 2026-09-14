from __future__ import annotations

from typing import Optional

from sqlalchemy import BigInteger, Boolean, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AsignacionRow(Base):
    __tablename__ = "asignacion"

    asignacion_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    trabajo_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    proveedor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    partner_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    correlacion_id: Mapped[str] = mapped_column(String(64), nullable=False)
    estado: Mapped[str] = mapped_column(String(32), nullable=False)
    sla_vence_en: Mapped[int] = mapped_column(BigInteger, nullable=False)
    verificado_en: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ocurrido_en: Mapped[int] = mapped_column(BigInteger, nullable=False)
    origen_habilitacion: Mapped[str] = mapped_column(String(64), nullable=False, default="PROYECCION_LOCAL")


class ProyeccionReglaPartnerRow(Base):
    __tablename__ = "proyeccion_regla_partner"

    partner_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    red_homologada: Mapped[list] = mapped_column(JSONB, nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    vigente_hasta: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)


class ProyeccionHabilitacionRow(Base):
    __tablename__ = "proyeccion_habilitacion"

    proveedor_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    estado: Mapped[str] = mapped_column(String(32), nullable=False)
    categorias: Mapped[list] = mapped_column(JSONB, nullable=False)
    ciudades: Mapped[list] = mapped_column(JSONB, nullable=False)
    vigente_hasta: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)


class EventoProcesadoRow(Base):
    __tablename__ = "eventos_procesados"

    evento_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    procesado_en: Mapped[int] = mapped_column(BigInteger, nullable=False)


class AsignacionFallidaRow(Base):
    __tablename__ = "asignacion_fallida"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    trabajo_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    correlacion_id: Mapped[str] = mapped_column(String(64), nullable=False)
    motivo: Mapped[str] = mapped_column(Text, nullable=False)
    ocurrido_en: Mapped[int] = mapped_column(BigInteger, nullable=False)
    evento_id: Mapped[str] = mapped_column(String(36), nullable=False)
