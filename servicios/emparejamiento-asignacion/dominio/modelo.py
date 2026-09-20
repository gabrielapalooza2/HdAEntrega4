from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Sequence

ORIGEN_HABILITACION_PROYECCION_LOCAL = "PROYECCION_LOCAL"
PRODUCTOR = "emparejamiento-asignacion"
TIPO_TRABAJO_ASIGNADO = "TrabajoAsignado"
SPECVERSION = "v1"
DATACONTENTTYPE = "AVRO"


class EstadoAsignacion(str, Enum):
    ASIGNADO = "ASIGNADO"
    CONFIRMADO = "CONFIRMADO"
    RECHAZADO = "RECHAZADO"


class EstadoHabilitacion(str, Enum):
    HABILITADO = "HABILITADO"
    SUSPENDIDO = "SUSPENDIDO"
    INHABILITADO = "INHABILITADO"


@dataclass(frozen=True)
class TrabajoParaAsignar:
    trabajo_id: str
    partner_id: str
    mercado_id: str
    categoria: str
    urgencia: str
    ciudad: str
    sla_minutos: int
    ocurrido_en: int
    correlacion_id: str
    evento_id: str
    requiere_aprobacion: bool = False


@dataclass(frozen=True)
class ProyeccionReglaPartner:
    partner_id: str
    red_homologada: tuple[str, ...]
    activo: bool
    vigente_hasta: Optional[int]


@dataclass(frozen=True)
class ProyeccionHabilitacion:
    proveedor_id: str
    estado: str
    categorias: tuple[str, ...]
    ciudades: tuple[str, ...]
    vigente_hasta: Optional[int]


@dataclass
class Asignacion:
    asignacion_id: str
    trabajo_id: str
    proveedor_id: str
    partner_id: str
    correlacion_id: str
    sla_vence_en: int
    verificado_en: int
    ocurrido_en: int
    origen_habilitacion: str = ORIGEN_HABILITACION_PROYECCION_LOCAL
    estado: EstadoAsignacion = EstadoAsignacion.ASIGNADO

    def marcar_rechazado(self) -> None:
        self.estado = EstadoAsignacion.RECHAZADO

    def marcar_confirmado(self, verificado_en: int | None = None) -> None:
        self.estado = EstadoAsignacion.CONFIRMADO
        if verificado_en:
            self.verificado_en = verificado_en


@dataclass(frozen=True)
class AsignacionFallida:
    trabajo_id: str
    correlacion_id: str
    motivo: str
    ocurrido_en: int
    evento_id: str


@dataclass(frozen=True)
class TrabajoAsignado:
    id: str
    time: int
    ingestion: int
    specversion: str
    type: str
    datacontenttype: str
    service_name: str
    correlation_id: str
    trabajo_id: str
    asignacion_id: str
    proveedor_id: str
    partner_id: str
    sla_vence_en: int
    origen_habilitacion: str

    def a_dict(self) -> dict:
        return {
            "id": self.id,
            "time": self.time,
            "ingestion": self.ingestion,
            "specversion": self.specversion,
            "type": self.type,
            "datacontenttype": self.datacontenttype,
            "service_name": self.service_name,
            "correlation_id": self.correlation_id,
            "data": {
                "trabajo_id": self.trabajo_id,
                "asignacion_id": self.asignacion_id,
                "proveedor_id": self.proveedor_id,
                "partner_id": self.partner_id,
                "sla_vence_en": self.sla_vence_en,
                "origen_habilitacion": self.origen_habilitacion,
            },
        }


@dataclass(frozen=True)
class ResultadoEmparejamiento:
    asignacion: Optional[Asignacion] = None
    evento: Optional[TrabajoAsignado] = None
    fallida: Optional[AsignacionFallida] = None
    ya_procesado: bool = False
    ignorado: bool = False
    motivo_ignorado: str = ""


def minutos_a_millis(minutos: int) -> int:
    return minutos * 60 * 1000


def vigencia_abierta(vigente_hasta: Optional[int]) -> bool:
    """0 o None = sin fecha de fin (contrato vigencia_hasta default 0)."""
    return vigente_hasta is None or vigente_hasta == 0


def candidatos_habilitados(
    habilitaciones: Sequence[ProyeccionHabilitacion],
    categoria: str,
    ciudad: str,
    ahora_ms: int,
) -> list[str]:
    ids: list[str] = []
    for h in habilitaciones:
        if h.estado != EstadoHabilitacion.HABILITADO.value:
            continue
        if categoria not in h.categorias:
            continue
        if ciudad not in h.ciudades:
            continue
        if not vigencia_abierta(h.vigente_hasta) and h.vigente_hasta <= ahora_ms:
            continue
        ids.append(h.proveedor_id)
    return ids


def aplicar_red_homologada(
    proveedor_ids: Sequence[str],
    red_homologada: Sequence[str],
) -> list[str]:
    if not red_homologada:
        return list(proveedor_ids)
    permitidos = set(red_homologada)
    return [pid for pid in proveedor_ids if pid in permitidos]


def elegir_proveedor_determinista(proveedor_ids: Sequence[str]) -> Optional[str]:
    if not proveedor_ids:
        return None
    return sorted(proveedor_ids)[0]
