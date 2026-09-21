"""El agregado Trabajo. Python puro: ni Flask, ni psycopg, ni pulsar.

Este modulo es el nucleo del microservicio y se puede probar entero sin
infraestructura. Esa es la prueba de que la arquitectura hexagonal se sostiene:
si para probar una regla de negocio hiciera falta un broker, la capa se rompio.

FORMA DEL AGREGADO (Event Sourcing)
-----------------------------------
El estado NO se guarda: se DERIVA reproduciendo los eventos en orden.

    reconstruir(eventos)  ->  estado actual
    decidir(comando)      ->  eventos nuevos  (NO muta nada)
    aplicar(evento)       ->  muta el estado

Separar `decidir` de `aplicar` es lo que hace el agregado probable sin base de
datos: decidir es una funcion de (estado, comando) a eventos, sin efectos.
"""
from dataclasses import dataclass, field
from datetime import datetime

from orquestacion.dominio import eventos as ev
from orquestacion.dominio.objetos_valor import (
    AcuerdoDeServicio,
    CategoriaDeServicio,
    EstadoTrabajo,
    MotivoEscalamiento,
    MotivoRechazo,
    Urgencia,
)


class ErrorDeDominio(Exception):
    """Violacion de una regla del agregado. No es un fallo tecnico."""


@dataclass
class Trabajo:
    """Estado derivado del agregado. Nunca se construye a mano: sale de
    `reconstruir`."""
    trabajo_id: str
    estado: EstadoTrabajo = EstadoTrabajo.CREADO
    partner_id: str = ""
    categoria: str = ""
    zona: str = ""
    proveedor_id: str | None = None
    sla_minutos: int | None = None
    regla_version: int | None = None
    vence_en: datetime | None = None
    intentos: int = 0
    proveedores_excluidos: tuple[str, ...] = ()

    # Cuantos eventos se reprodujeron. Es la version del agregado, y es lo que
    # se usa como control de concurrencia optimista al escribir el siguiente.
    secuencia: int = 0

    # ═════════════════════════════════════════════════ reconstruccion ══════

    @classmethod
    def reconstruir(cls, trabajo_id: str,
                    historia: list[tuple[int, ev.EventoDeDominio]]) -> "Trabajo":
        """Reproduce la historia del agregado.

        Si la historia esta vacia devuelve un agregado en secuencia 0, que es
        como se representa "todavia no existe". No es un caso de error: es el
        estado inicial legitimo antes del primer evento.
        """
        trabajo = cls(trabajo_id=trabajo_id)
        for secuencia, evento in historia:
            trabajo.aplicar(evento)
            trabajo.secuencia = secuencia
        return trabajo

    @property
    def existe(self) -> bool:
        return self.secuencia > 0

    def aplicar(self, evento: ev.EventoDeDominio) -> None:
        """Muta el estado. Un evento por rama, sin logica de negocio.

        Aqui NO se valida nada: los eventos son hechos que YA ocurrieron, y
        rechazar un hecho pasado no tiene sentido. La validacion vive en
        `decidir_*`, antes de que el hecho exista.
        """
        match evento:
            case ev.TrabajoCreado():
                self.estado = EstadoTrabajo.CREADO
                self.partner_id = evento.partner_id
                self.categoria = evento.categoria
                self.zona = evento.zona
                self.sla_minutos = evento.sla_minutos
                self.regla_version = evento.regla_version
                self.vence_en = evento.vence_en

            case ev.TrabajoRechazado():
                self.estado = EstadoTrabajo.RECHAZADO
                self.partner_id = evento.partner_id
                self.categoria = evento.categoria
                self.zona = evento.zona

            case ev.ProveedorAsignado():
                self.estado = EstadoTrabajo.ASIGNADO
                self.proveedor_id = evento.proveedor_id

            case ev.ProveedorDescartado():
                # Compensacion: la asignacion optimista queda deshecha.
                # El trabajo vuelve a CREADO para que el reloj del SLA siga
                # corriendo: ASIGNADO solo es terminal cuando la habilitacion
                # autoritativa confirma, o mientras nadie haya revertido.
                self.intentos = evento.intento
                self.proveedor_id = None
                if self.estado is EstadoTrabajo.ASIGNADO:
                    self.estado = EstadoTrabajo.CREADO
                if evento.proveedor_id not in self.proveedores_excluidos:
                    self.proveedores_excluidos += (evento.proveedor_id,)

            case ev.ReasignacionSolicitada():
                # No cambia el estado: el trabajo sigue CREADO esperando.
                self.proveedores_excluidos = evento.proveedores_excluidos

            case ev.TrabajoEscalado():
                self.estado = EstadoTrabajo.ESCALADO_MANUAL


# ═══════════════════════════════════════════════════════════ decisiones ════
#
# Funciones puras: (estado, datos) -> eventos. No tocan la base ni el broker.


def decidir_creacion(trabajo_id: str, *, partner_id: str, categoria: str, zona: str,
                     regla, ahora: datetime, mercado_id: str = "", urgencia: str = "",
                     descripcion: str = "", monto_estimado: int | None = None,
                     moneda: str | None = None) -> ev.EventoDeDominio:
    """Acepta o rechaza un trabajo contra la regla del partner.

    `regla` es una ReglaDePartner de la proyeccion local, o None si nunca vimos
    a ese partner. NO se llama a ningun servicio por red: esa es la razon de que
    la proyeccion exista, y es el escenario de disponibilidad.

    ─── CERO CONDICIONALES POR PARTNER ───────────────────────────────────
    No hay ni un `if partner_id == ...` aqui ni en ninguna parte. Las tres
    causas de rechazo se evaluan contra DATOS de la regla, iguales para todos
    los partners. Agregar una aseguradora nueva es publicar un evento en
    evt.partners, no tocar este archivo.
    ───────────────────────────────────────────────────────────────────────
    """
    cat = CategoriaDeServicio.de_codigo(categoria)

    def rechazo(motivo: MotivoRechazo, detalle: str) -> ev.TrabajoRechazado:
        return ev.TrabajoRechazado(
            trabajo_id=trabajo_id, partner_id=partner_id, categoria=cat.codigo,
            motivo=motivo.value, detalle=detalle, zona=zona,
            regla_version=(regla.regla_version if regla else None),
        )

    if regla is None:
        return rechazo(
            MotivoRechazo.PARTNER_DESCONOCIDO,
            f"No hay regla conocida para el partner {partner_id}",
        )

    if not regla.activo:
        return rechazo(
            MotivoRechazo.PARTNER_INACTIVO,
            f"El partner {partner_id} no esta activo en la regla v{regla.regla_version}",
        )

    if not regla.cubre(cat.codigo):
        return rechazo(
            MotivoRechazo.CATEGORIA_NO_CUBIERTA,
            f"La regla v{regla.regla_version} de {partner_id} no cubre {cat.codigo}; "
            f"cubre {sorted(regla.categorias_cubiertas)}",
        )

    # ─── AQUI SE CONGELA EL SLA ───────────────────────────────────────────
    # Se copian sla_minutos y regla_version de la regla VIGENTE AHORA y se
    # calcula vence_en. Los tres quedan escritos en el payload del evento, en un
    # event store append-only. Cambiar la regla manana no los puede mover.
    acuerdo = AcuerdoDeServicio.desde_regla(
        minutos=regla.sla_minutos, regla_version=regla.regla_version, creado_en=ahora)

    return ev.TrabajoCreado(
        trabajo_id=trabajo_id, partner_id=partner_id, categoria=cat.codigo, zona=zona,
        sla_minutos=acuerdo.minutos_respuesta,
        regla_version=acuerdo.regla_version,
        vence_en=acuerdo.vence_en,
        mercado_id=mercado_id, urgencia=Urgencia.de_texto(urgencia).value,
        descripcion=descripcion, monto_estimado=monto_estimado, moneda=moneda,
        requiere_aprobacion=regla.requiere_aprobacion(monto_estimado),
    )


def decidir_asignacion(trabajo: Trabajo, *, proveedor_id: str,
                       asignacion_id: str = "") -> list[ev.EventoDeDominio]:
    """Emparejamiento asigno un proveedor. Detiene el reloj del SLA."""
    if not trabajo.existe:
        raise ErrorDeDominio(f"Trabajo {trabajo.trabajo_id} desconocido")

    if trabajo.estado is EstadoTrabajo.ASIGNADO:
        # Reentrega del mismo hecho, o una segunda asignacion al mismo
        # proveedor. Sin eventos: el estado ya es el correcto.
        return []

    if trabajo.estado.es_terminal():
        # Llego tarde: el trabajo ya se rechazo o se escalo. No se puede
        # deshacer un estado terminal, y forzarlo seria peor que ignorarlo.
        return []

    return [ev.ProveedorAsignado(trabajo_id=trabajo.trabajo_id,
                                 proveedor_id=proveedor_id,
                                 asignacion_id=asignacion_id)]


def decidir_rechazo_de_habilitacion(trabajo: Trabajo, *, proveedor_id: str,
                                    motivo: str, max_intentos: int
                                    ) -> list[ev.EventoDeDominio]:
    """COMPENSACION: el proveedor asignado no estaba habilitado.

    ─── EL UNICO PUNTO ORQUESTADO DEL SISTEMA ────────────────────────────
    Todo lo demas es coreografia: cada servicio reacciona a lo que ve y nadie
    dirige. Aqui no: aqui hay alguien que DECIDE y que LLEVA LA CUENTA de los
    intentos. Es el unico lugar donde este servicio manda un comando en vez de
    publicar un hecho.

    Se orquesta porque el reintento acotado necesita memoria -cuantas veces ya
    lo intentamos- y esa memoria tiene que vivir en algun lado. Vive en el
    agregado, que es su dueno natural.
    ───────────────────────────────────────────────────────────────────────
    """
    if not trabajo.existe:
        raise ErrorDeDominio(f"Trabajo {trabajo.trabajo_id} desconocido")

    if trabajo.estado.es_terminal() and trabajo.estado is not EstadoTrabajo.ASIGNADO:
        return []

    intento = trabajo.intentos + 1
    descarte = ev.ProveedorDescartado(
        trabajo_id=trabajo.trabajo_id, proveedor_id=proveedor_id,
        motivo=motivo, intento=intento)

    excluidos = trabajo.proveedores_excluidos
    if proveedor_id not in excluidos:
        excluidos += (proveedor_id,)

    if intento >= max_intentos:
        # Se agoto el reintento automatico. Lo toma una persona.
        return [descarte, ev.TrabajoEscalado(
            trabajo_id=trabajo.trabajo_id,
            motivo=MotivoEscalamiento.INTENTOS_AGOTADOS.value,
            detalle=f"{intento} intentos fallidos; excluidos {sorted(excluidos)}")]

    return [descarte, ev.ReasignacionSolicitada(
        trabajo_id=trabajo.trabajo_id, intento=intento + 1,
        proveedores_excluidos=excluidos, motivo=motivo)]


def decidir_vencimiento(trabajo: Trabajo, ahora: datetime) -> list[ev.EventoDeDominio]:
    """El SLA vencio sin que nadie respondiera.

    ─── POR QUE HACE FALTA UN BARRIDO ────────────────────────────────────
    Los eventos te dicen lo que PASO, nunca lo que NO paso. En coreografia nadie
    espera: si Emparejamiento jamas responde, no llega ningun evento que diga
    "no respondi", y sin este barrido el trabajo se queda quieto para siempre.

    El paso del tiempo es el unico estimulo que ningun mensaje puede entregar.
    ───────────────────────────────────────────────────────────────────────
    """
    if not trabajo.existe or trabajo.estado.es_terminal():
        return []
    if trabajo.vence_en is None or ahora < trabajo.vence_en:
        return []

    return [ev.TrabajoEscalado(
        trabajo_id=trabajo.trabajo_id,
        motivo=MotivoEscalamiento.SLA_VENCIDO.value,
        detalle=f"El SLA de {trabajo.sla_minutos} min (regla v{trabajo.regla_version}) "
                f"vencio en {trabajo.vence_en.isoformat()}")]
