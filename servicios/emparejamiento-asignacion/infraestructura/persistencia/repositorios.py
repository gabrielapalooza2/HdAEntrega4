from __future__ import annotations

import time
import uuid
from typing import Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from infraestructura.persistencia.modelos import (
    AsignacionFallidaRow,
    AsignacionRow,
    EventoProcesadoRow,
    ProyeccionHabilitacionRow,
    ProyeccionReglaPartnerRow,
)
from dominio.modelo import (
    Asignacion,
    AsignacionFallida,
    EstadoAsignacion,
    ProyeccionHabilitacion,
    ProyeccionReglaPartner,
)


def _ahora_ms() -> int:
    return int(time.time() * 1000)


class RepositorioAsignacionesSql:
    def __init__(self, session: Session) -> None:
        self._s = session

    def obtener_por_trabajo(self, trabajo_id: str) -> Optional[Asignacion]:
        row = self._s.scalar(
            select(AsignacionRow)
            .where(AsignacionRow.trabajo_id == trabajo_id)
            .order_by(AsignacionRow.ocurrido_en.desc())
        )
        return _a_asignacion(row) if row else None

    def obtener_por_id(self, asignacion_id: str) -> Optional[Asignacion]:
        row = self._s.get(AsignacionRow, asignacion_id)
        return _a_asignacion(row) if row else None

    def guardar(self, asignacion: Asignacion) -> None:
        row = self._s.get(AsignacionRow, asignacion.asignacion_id)
        if row is None:
            row = AsignacionRow(asignacion_id=asignacion.asignacion_id)
            self._s.add(row)
        row.trabajo_id = asignacion.trabajo_id
        row.proveedor_id = asignacion.proveedor_id
        row.partner_id = asignacion.partner_id
        row.correlacion_id = asignacion.correlacion_id
        row.estado = asignacion.estado.value
        row.sla_vence_en = asignacion.sla_vence_en
        row.verificado_en = asignacion.verificado_en
        row.ocurrido_en = asignacion.ocurrido_en
        row.origen_habilitacion = asignacion.origen_habilitacion


class RepositorioProyeccionReglaSql:
    def __init__(self, session: Session) -> None:
        self._s = session

    def upsert(self, regla: ProyeccionReglaPartner) -> None:
        row = self._s.get(ProyeccionReglaPartnerRow, regla.partner_id)
        if row is None:
            row = ProyeccionReglaPartnerRow(partner_id=regla.partner_id)
            self._s.add(row)
        row.red_homologada = list(regla.red_homologada)
        row.activo = regla.activo
        row.vigente_hasta = regla.vigente_hasta

    def obtener(self, partner_id: str) -> Optional[ProyeccionReglaPartner]:
        row = self._s.get(ProyeccionReglaPartnerRow, partner_id)
        if row is None:
            return None
        return ProyeccionReglaPartner(
            partner_id=row.partner_id,
            red_homologada=tuple(row.red_homologada or ()),
            activo=row.activo,
            vigente_hasta=row.vigente_hasta,
        )

    def contar(self) -> int:
        return int(self._s.scalar(select(func.count()).select_from(ProyeccionReglaPartnerRow)) or 0)


class RepositorioProyeccionHabilitacionSql:
    def __init__(self, session: Session) -> None:
        self._s = session

    def upsert(self, habilitacion: ProyeccionHabilitacion) -> None:
        row = self._s.get(ProyeccionHabilitacionRow, habilitacion.proveedor_id)
        if row is None:
            row = ProyeccionHabilitacionRow(proveedor_id=habilitacion.proveedor_id)
            self._s.add(row)
        row.estado = habilitacion.estado
        row.categorias = list(habilitacion.categorias)
        row.ciudades = list(habilitacion.ciudades)
        row.vigente_hasta = habilitacion.vigente_hasta

    def listar(self) -> Sequence[ProyeccionHabilitacion]:
        rows = self._s.scalars(select(ProyeccionHabilitacionRow)).all()
        return [
            ProyeccionHabilitacion(
                proveedor_id=r.proveedor_id,
                estado=r.estado,
                categorias=tuple(r.categorias or ()),
                ciudades=tuple(r.ciudades or ()),
                vigente_hasta=r.vigente_hasta,
            )
            for r in rows
        ]

    def contar(self) -> int:
        return int(self._s.scalar(select(func.count()).select_from(ProyeccionHabilitacionRow)) or 0)


class RepositorioEventosProcesadosSql:
    def __init__(self, session: Session) -> None:
        self._s = session

    def ya_procesado(self, evento_id: str) -> bool:
        return self._s.get(EventoProcesadoRow, evento_id) is not None

    def marcar(self, evento_id: str) -> None:
        if self._s.get(EventoProcesadoRow, evento_id) is not None:
            return
        self._s.add(EventoProcesadoRow(evento_id=evento_id, procesado_en=_ahora_ms()))


class RepositorioAsignacionesFallidasSql:
    def __init__(self, session: Session) -> None:
        self._s = session

    def guardar(self, fallida: AsignacionFallida) -> None:
        self._s.add(
            AsignacionFallidaRow(
                id=str(uuid.uuid4()),
                trabajo_id=fallida.trabajo_id,
                correlacion_id=fallida.correlacion_id,
                motivo=fallida.motivo,
                ocurrido_en=fallida.ocurrido_en,
                evento_id=fallida.evento_id,
            )
        )


def _a_asignacion(row: AsignacionRow) -> Asignacion:
    return Asignacion(
        asignacion_id=row.asignacion_id,
        trabajo_id=row.trabajo_id,
        proveedor_id=row.proveedor_id,
        partner_id=row.partner_id,
        correlacion_id=row.correlacion_id,
        sla_vence_en=row.sla_vence_en,
        verificado_en=row.verificado_en,
        ocurrido_en=row.ocurrido_en,
        origen_habilitacion=row.origen_habilitacion,
        estado=EstadoAsignacion(row.estado),
    )
