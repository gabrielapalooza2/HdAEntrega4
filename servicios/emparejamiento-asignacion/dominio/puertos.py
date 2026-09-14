from __future__ import annotations

from typing import Optional, Protocol, Sequence

from dominio.modelo import (
    Asignacion,
    AsignacionFallida,
    ProyeccionHabilitacion,
    ProyeccionReglaPartner,
    TrabajoAsignado,
)


class RepositorioAsignaciones(Protocol):
    def obtener_por_trabajo(self, trabajo_id: str) -> Optional[Asignacion]:
        ...

    def obtener_por_id(self, asignacion_id: str) -> Optional[Asignacion]:
        ...

    def guardar(self, asignacion: Asignacion) -> None:
        ...


class RepositorioProyeccionRegla(Protocol):
    def upsert(self, regla: ProyeccionReglaPartner) -> None:
        ...

    def obtener(self, partner_id: str) -> Optional[ProyeccionReglaPartner]:
        ...

    def contar(self) -> int:
        ...


class RepositorioProyeccionHabilitacion(Protocol):
    def upsert(self, habilitacion: ProyeccionHabilitacion) -> None:
        ...

    def listar(self) -> Sequence[ProyeccionHabilitacion]:
        ...

    def contar(self) -> int:
        ...


class RepositorioEventosProcesados(Protocol):
    def ya_procesado(self, evento_id: str) -> bool:
        ...

    def marcar(self, evento_id: str) -> None:
        ...


class RepositorioAsignacionesFallidas(Protocol):
    def guardar(self, fallida: AsignacionFallida) -> None:
        ...


class PublicadorTrabajoAsignado(Protocol):
    def publicar(self, evento: TrabajoAsignado) -> None:
        ...


class Reloj(Protocol):
    def ahora_ms(self) -> int:
        ...


class UnidadDeTrabajo(Protocol):
    asignaciones: RepositorioAsignaciones
    reglas: RepositorioProyeccionRegla
    habilitaciones: RepositorioProyeccionHabilitacion
    eventos_procesados: RepositorioEventosProcesados
    fallidas: RepositorioAsignacionesFallidas

    def commit(self) -> None:
        ...

    def rollback(self) -> None:
        ...
