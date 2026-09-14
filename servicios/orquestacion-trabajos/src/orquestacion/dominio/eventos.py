"""Eventos de DOMINIO del agregado Trabajo.

No confundir con los eventos de INTEGRACION de mensajeria/contratos.py. Son el
mismo hecho en dos formas distintas:

  evento de dominio       lo que de verdad paso, completo, en vocabulario
                          propio. Se guarda en eventos_trabajo y es la FUENTE
                          DE VERDAD. Nadie fuera de este servicio lo ve.

  evento de integracion   una PROYECCION del mismo hecho, recortada a lo que el
                          contrato del grupo admite. Es lo que viaja por Pulsar.

Que TrabajoCreado exista en los dos lados es intencional y hay que poder
explicarlo: el de dominio lleva regla_version y vence_en -la evidencia del
congelamiento del SLA- y el de integracion NO, porque el contrato ajeno no tiene
esos campos. Perderlos en el cable no rompe nada, porque el congelamiento se
prueba en el event store.

Python puro: este modulo no importa Flask, ni psycopg, ni pulsar. Nada.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, ClassVar


def _iso(momento: datetime | None) -> str | None:
    return None if momento is None else momento.astimezone(timezone.utc).isoformat()


def _de_iso(texto: str | None) -> datetime | None:
    return None if texto is None else datetime.fromisoformat(texto)


@dataclass(frozen=True)
class EventoDeDominio:
    """Los eventos son INMUTABLES (frozen).

    Un hecho que ya ocurrio no se corrige: se le agrega otro hecho encima. Por
    eso eventos_trabajo es append-only y por eso estos dataclasses son frozen.
    """
    TIPO: ClassVar[str] = ""

    def a_payload(self) -> dict[str, Any]:
        raise NotImplementedError

    @classmethod
    def desde_payload(cls, d: dict) -> "EventoDeDominio":
        raise NotImplementedError


@dataclass(frozen=True)
class TrabajoCreado(EventoDeDominio):
    """El trabajo fue aceptado: la regla del partner lo cubre.

    ─── EL CONGELAMIENTO DEL SLA ─────────────────────────────────────────
    sla_minutos, regla_version y vence_en se copian de la regla vigente AL
    MOMENTO DE CREAR y quedan escritos aqui, en el payload del evento.

    Como eventos_trabajo es append-only, cambiar la regla del partner manana no
    puede alterar este evento: no hay UPDATE que lo toque. El trabajo se sigue
    evaluando con la v7 aunque el partner ya vaya por la v12.

    Eso ES el escenario de modificabilidad, y se prueba mirando esta fila.
    ───────────────────────────────────────────────────────────────────────
    """
    TIPO: ClassVar[str] = "TrabajoCreado"

    trabajo_id: str
    partner_id: str
    categoria: str
    zona: str
    sla_minutos: int
    regla_version: int
    vence_en: datetime
    mercado_id: str = ""
    urgencia: str = ""
    descripcion: str = ""
    monto_estimado: int | None = None
    moneda: str | None = None
    requiere_aprobacion: bool = False

    def a_payload(self) -> dict:
        return {
            "trabajo_id": self.trabajo_id,
            "partner_id": self.partner_id,
            "categoria": self.categoria,
            "zona": self.zona,
            "sla_minutos": self.sla_minutos,
            "regla_version": self.regla_version,
            "vence_en": _iso(self.vence_en),
            "mercado_id": self.mercado_id,
            "urgencia": self.urgencia,
            "descripcion": self.descripcion,
            "monto_estimado": self.monto_estimado,
            "moneda": self.moneda,
            "requiere_aprobacion": self.requiere_aprobacion,
        }

    @classmethod
    def desde_payload(cls, d: dict) -> "TrabajoCreado":
        return cls(
            trabajo_id=d["trabajo_id"], partner_id=d["partner_id"],
            categoria=d["categoria"], zona=d["zona"],
            sla_minutos=d["sla_minutos"], regla_version=d["regla_version"],
            vence_en=_de_iso(d["vence_en"]), mercado_id=d.get("mercado_id", ""),
            urgencia=d.get("urgencia", ""), descripcion=d.get("descripcion", ""),
            monto_estimado=d.get("monto_estimado"), moneda=d.get("moneda"),
            requiere_aprobacion=bool(d.get("requiere_aprobacion")),
        )


@dataclass(frozen=True)
class TrabajoRechazado(EventoDeDominio):
    """La regla del partner no cubre este trabajo.

    Es un HECHO DE NEGOCIO, no un error tecnico. Por eso se guarda en el event
    store y se publica, en vez de lanzar una excepcion: la aseguradora tiene
    derecho a enterarse y a saber por que.

    `motivo` es un codigo estable, para que una maquina reaccione. `detalle` es
    texto, para que una persona entienda.
    """
    TIPO: ClassVar[str] = "TrabajoRechazado"

    trabajo_id: str
    partner_id: str
    categoria: str
    motivo: str
    detalle: str
    zona: str = ""
    regla_version: int | None = None

    def a_payload(self) -> dict:
        return {
            "trabajo_id": self.trabajo_id, "partner_id": self.partner_id,
            "categoria": self.categoria, "motivo": self.motivo,
            "detalle": self.detalle, "zona": self.zona,
            "regla_version": self.regla_version,
        }

    @classmethod
    def desde_payload(cls, d: dict) -> "TrabajoRechazado":
        return cls(
            trabajo_id=d["trabajo_id"], partner_id=d["partner_id"],
            categoria=d["categoria"], motivo=d["motivo"], detalle=d["detalle"],
            zona=d.get("zona", ""), regla_version=d.get("regla_version"),
        )


@dataclass(frozen=True)
class ProveedorAsignado(EventoDeDominio):
    """Emparejamiento asigno un proveedor. DETIENE EL RELOJ DEL SLA.

    El SLA es de RESPUESTA, no de ejecucion: se cumple cuando hay un tecnico
    asignado, no cuando el tecnico termina el trabajo. Por eso ASIGNADO es un
    estado terminal para efectos del barrido.
    """
    TIPO: ClassVar[str] = "ProveedorAsignado"

    trabajo_id: str
    proveedor_id: str
    asignacion_id: str = ""

    def a_payload(self) -> dict:
        return {"trabajo_id": self.trabajo_id, "proveedor_id": self.proveedor_id,
                "asignacion_id": self.asignacion_id}

    @classmethod
    def desde_payload(cls, d: dict) -> "ProveedorAsignado":
        return cls(trabajo_id=d["trabajo_id"], proveedor_id=d["proveedor_id"],
                   asignacion_id=d.get("asignacion_id", ""))


@dataclass(frozen=True)
class ProveedorDescartado(EventoDeDominio):
    """El proveedor asignado no estaba habilitado: se excluye y se cuenta el
    intento.

    Guardar el descarte como un hecho -en vez de solo incrementar un contador en
    una tabla- es lo que permite responder despues "por que este trabajo se
    escalo" leyendo la historia del agregado.
    """
    TIPO: ClassVar[str] = "ProveedorDescartado"

    trabajo_id: str
    proveedor_id: str
    motivo: str
    intento: int

    def a_payload(self) -> dict:
        return {"trabajo_id": self.trabajo_id, "proveedor_id": self.proveedor_id,
                "motivo": self.motivo, "intento": self.intento}

    @classmethod
    def desde_payload(cls, d: dict) -> "ProveedorDescartado":
        return cls(trabajo_id=d["trabajo_id"], proveedor_id=d["proveedor_id"],
                   motivo=d["motivo"], intento=d["intento"])


@dataclass(frozen=True)
class ReasignacionSolicitada(EventoDeDominio):
    """Se pidio otro proveedor. Es el hecho que dispara AsignarProveedor."""
    TIPO: ClassVar[str] = "ReasignacionSolicitada"

    trabajo_id: str
    intento: int
    proveedores_excluidos: tuple[str, ...] = ()
    motivo: str = ""

    def a_payload(self) -> dict:
        return {"trabajo_id": self.trabajo_id, "intento": self.intento,
                "proveedores_excluidos": list(self.proveedores_excluidos),
                "motivo": self.motivo}

    @classmethod
    def desde_payload(cls, d: dict) -> "ReasignacionSolicitada":
        return cls(trabajo_id=d["trabajo_id"], intento=d["intento"],
                   proveedores_excluidos=tuple(d.get("proveedores_excluidos") or []),
                   motivo=d.get("motivo", ""))


@dataclass(frozen=True)
class TrabajoEscalado(EventoDeDominio):
    """Se agoto el reintento automatico, o vencio el SLA. Lo toma una persona.

    Es el destino de las dos formas de fallo que la coreografia no resuelve
    sola: demasiados rechazos, o SILENCIO -que ningun evento reporta nunca-.
    """
    TIPO: ClassVar[str] = "TrabajoEscalado"

    trabajo_id: str
    motivo: str
    detalle: str = ""

    def a_payload(self) -> dict:
        return {"trabajo_id": self.trabajo_id, "motivo": self.motivo,
                "detalle": self.detalle}

    @classmethod
    def desde_payload(cls, d: dict) -> "TrabajoEscalado":
        return cls(trabajo_id=d["trabajo_id"], motivo=d["motivo"],
                   detalle=d.get("detalle", ""))


REGISTRO: dict[str, type[EventoDeDominio]] = {
    e.TIPO: e for e in (TrabajoCreado, TrabajoRechazado, ProveedorAsignado,
                        ProveedorDescartado, ReasignacionSolicitada, TrabajoEscalado)
}


def rehidratar(tipo: str, payload: dict) -> EventoDeDominio:
    """payload guardado -> evento tipado. Lo usa el event store al reconstruir."""
    return REGISTRO[tipo].desde_payload(payload)
