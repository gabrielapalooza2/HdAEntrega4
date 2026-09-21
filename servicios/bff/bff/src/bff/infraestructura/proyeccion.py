"""Proyeccion de lectura del BFF, y linea de tiempo de la saga.

QUE ES
------
Una vista en memoria construida escuchando los topicos de eventos. Es el lado de
LECTURA de CQRS, visto desde la capa de entrada.

POR QUE NO CONSULTAR A LOS SERVICIOS POR HTTP
---------------------------------------------
Seria mas corto de escribir, pero reintroduce exactamente el acoplamiento que la
arquitectura evita: con un servicio caido, el GET del BFF fallaria aunque el dato
ya estuviera publicado en el bus. Con proyeccion propia, el BFF sigue
respondiendo consultas aunque los cuatro servicios esten apagados.

POR QUE NO TIENE BASE DE DATOS
------------------------------
No la necesita. Los topicos tienen retencion infinita, asi que al arrancar se
suscribe desde el INICIO y reconstruye la vista completa. La fuente de verdad es
el log de eventos; esto es una cache derivada. Que se pueda tirar y reconstruir
es una propiedad, no una carencia.

SOBRE EL SAGA LOG
-----------------
El saga log AUTORITATIVO vive en Orquestacion de trabajos, que es el coordinador:
tablas `saga_asignacion` y `saga_paso` en PostgreSQL, consultables con SQL y por
`GET /sagas`. Lo que el BFF expone en `GET /sagas/{trabajo_id}` es una linea de
tiempo DERIVADA de los mismos eventos, construida sin llamar a nadie. No compite
con el log del coordinador: lo complementa desde el borde, y evita que el BFF
tenga que hacer una llamada sincrona entre servicios para responder.

EL PRECIO, DECLARADO
--------------------
Consistencia eventual: entre que un servicio publica y el BFF aplica el evento
pasan milisegundos en los que la vista esta atrasada. Y la reconstruccion tarda
proporcionalmente al tamano del log.
"""

import logging
import threading
import time
import uuid

from .. import config
from ..esquemas import avro
from .operaciones import COMPLETADA, RECHAZADA, registro

log = logging.getLogger("bff.proyeccion")

# Que significa cada evento para el desenlace de una saga.
_CIERRA_BIEN = {"TrabajoCreado", "TrabajoAsignado",
                "AsignacionAceptadaPorReglaPartner",
                "AsignacionConfirmadaPorHabilitacion"}
_CIERRA_MAL = {"TrabajoRechazado",
               "AsignacionRechazadaPorReglaPartner",
               "AsignacionRechazadaPorHabilitacion"}


class Proyeccion:
    """Cuatro diccionarios, una linea de tiempo y un candado."""

    def __init__(self):
        self.partners: dict[str, dict] = {}
        self.proveedores: dict[str, dict] = {}
        self.trabajos: dict[str, dict] = {}
        self.asignaciones: dict[str, dict] = {}
        self.sagas: dict[str, list[dict]] = {}       # trabajo_id -> pasos
        self._candado = threading.RLock()
        self._eventos_aplicados = 0

    # ── aplicacion de eventos ────────────────────────────────────────────────

    def aplicar(self, tipo: str, data: dict, correlation_id: str = "",
                service_name: str = "", momento: int | None = None):
        with self._candado:
            self._eventos_aplicados += 1
            self._anotar_paso(tipo, data, correlation_id, service_name, momento)
            manejador = getattr(self, f"_al_{_nombre_metodo(tipo)}", None)
            if manejador is None:
                log.debug("evento sin manejador: %s", tipo)
                return
            manejador(data, correlation_id)

    def _anotar_paso(self, tipo, data, correlation_id, service_name, momento):
        """Linea de tiempo por trabajo. Append-only, como el log del coordinador."""
        trabajo_id = data.get("trabajo_id")
        if not trabajo_id:
            return
        pasos = self.sagas.setdefault(trabajo_id, [])
        pasos.append({
            "secuencia": len(pasos) + 1,
            "tipo": tipo,
            "servicio": service_name or "desconocido",
            "resultado": ("OK" if tipo in _CIERRA_BIEN
                          else "COMPENSACION" if tipo in _CIERRA_MAL else "INFO"),
            "correlation_id": correlation_id,
            "momento": momento or int(time.time() * 1000),
            "motivo": data.get("motivo"),
            "proveedor_id": data.get("proveedor_id"),
            "asignacion_id": data.get("asignacion_id"),
        })

    def _al_regla_de_partner_actualizada(self, d: dict, corr: str):
        pid = d.get("partner_id")
        if not pid:
            return
        self.partners[pid] = d          # ultimo evento gana: estado VIGENTE
        registro.resolver(corr, COMPLETADA, resultado={
            "partner_id": pid, "version_regla": d.get("version_regla")})

    def _al_estado_de_habilitacion_cambiado(self, d: dict, corr: str):
        pid = d.get("proveedor_id")
        if not pid:
            return
        self.proveedores[pid] = d
        registro.resolver(corr, COMPLETADA, resultado={
            "proveedor_id": pid, "estado": d.get("estado")})

    def _al_trabajo_creado(self, d: dict, corr: str):
        tid = d.get("trabajo_id")
        if not tid:
            return
        self.trabajos[tid] = {**d, "estado": "CREADO"}
        registro.resolver(corr, COMPLETADA, resultado={
            "trabajo_id": tid, "sla_minutos": d.get("sla_minutos")})

    def _al_trabajo_rechazado(self, d: dict, corr: str):
        tid = d.get("trabajo_id") or f"rechazado-{corr}"
        self.trabajos[tid] = {**d, "estado": "RECHAZADO"}
        registro.resolver(corr, RECHAZADA,
                          resultado={"trabajo_id": d.get("trabajo_id")},
                          motivo=d.get("motivo"))

    def _al_trabajo_asignado(self, d: dict, corr: str):
        tid, aid = d.get("trabajo_id"), d.get("asignacion_id")
        if aid:
            self.asignaciones[aid] = {**d, "estado": "ASIGNADA"}
        if tid in self.trabajos:
            self.trabajos[tid].update(estado="ASIGNADO", asignacion_id=aid)

    # ── los tres eventos de verificacion de la saga ──────────────────────────

    def _al_asignacion_aceptada_por_regla_partner(self, d: dict, corr: str):
        """Motor reglas partner confirma que el partner podia pedir ese trabajo."""
        self._marcar_asignacion(d, "VERIFICADA_POR_REGLA")

    def _al_asignacion_rechazada_por_regla_partner(self, d: dict, corr: str):
        """COMPENSACION. El partner no estaba habilitado para esa categoria."""
        self._marcar_asignacion(d, "RECHAZADA_POR_REGLA", trabajo="ASIGNACION_REVERTIDA")
        registro.resolver(corr, RECHAZADA, motivo=d.get("motivo"),
                          resultado={"trabajo_id": d.get("trabajo_id")})

    def _al_asignacion_confirmada_por_habilitacion(self, d: dict, corr: str):
        """Acreditacion confirma que el proveedor estaba habilitado. Saga feliz."""
        self._marcar_asignacion(d, "CONFIRMADA", trabajo="CONFIRMADO")
        registro.resolver(corr, COMPLETADA, resultado={
            "trabajo_id": d.get("trabajo_id"), "proveedor_id": d.get("proveedor_id")})

    def _al_asignacion_rechazada_por_habilitacion(self, d: dict, corr: str):
        """COMPENSACION. La asignacion era optimista y se deshace.

        Que el BFF lo refleje es lo que permite mostrar en Postman una
        transaccion que se revierte, no solo una que sale bien.
        """
        self._marcar_asignacion(d, "RECHAZADA", trabajo="ASIGNACION_REVERTIDA")
        registro.resolver(corr, RECHAZADA, motivo=d.get("motivo"),
                          resultado={"trabajo_id": d.get("trabajo_id"),
                                     "asignacion_id": d.get("asignacion_id")})

    def _marcar_asignacion(self, d: dict, estado: str, trabajo: str | None = None):
        aid, tid = d.get("asignacion_id"), d.get("trabajo_id")
        if aid:
            self.asignaciones[aid] = {**self.asignaciones.get(aid, {}), **d,
                                      "estado": estado}
        if trabajo and tid in self.trabajos:
            self.trabajos[tid]["estado"] = trabajo
            if d.get("motivo"):
                self.trabajos[tid]["motivo_reversion"] = d["motivo"]

    # ── consultas ────────────────────────────────────────────────────────────

    def trabajo_compuesto(self, trabajo_id: str) -> dict | None:
        """LA RAZON DE SER DEL BFF.

        Devuelve el trabajo, la regla del partner que se le aplico y la
        asignacion con su proveedor, en UNA sola respuesta. Sin BFF, el cliente
        tendria que hacer tres llamadas a tres servicios distintos y componer el
        resultado el mismo, conociendo la topologia interna del sistema.
        """
        with self._candado:
            t = self.trabajos.get(trabajo_id)
            if t is None:
                return None
            salida: dict = {"trabajo": t}

            partner = self.partners.get(t.get("partner_id"))
            if partner:
                salida["partner"] = {
                    "partner_id": partner.get("partner_id"),
                    "nombre": partner.get("nombre"),
                    "tipo_partner": partner.get("tipo_partner"),
                    "version_regla": partner.get("version_regla"),
                    "sla_minutos": partner.get("sla_minutos"),
                    "cobertura_contratada": partner.get("cobertura_contratada"),
                }

            aid = t.get("asignacion_id")
            asignacion = self.asignaciones.get(aid) if aid else None
            if asignacion is None:
                asignacion = next((a for a in self.asignaciones.values()
                                   if a.get("trabajo_id") == trabajo_id), None)
            if asignacion:
                salida["asignacion"] = asignacion
                proveedor = self.proveedores.get(asignacion.get("proveedor_id"))
                if proveedor:
                    salida["proveedor"] = {
                        "proveedor_id": proveedor.get("proveedor_id"),
                        "nombre": proveedor.get("nombre"),
                        "estado": proveedor.get("estado"),
                    }
            salida["saga"] = self.saga(trabajo_id)
            return salida

    def saga(self, trabajo_id: str) -> dict:
        """Linea de tiempo derivada de los eventos, sin llamar a nadie."""
        with self._candado:
            pasos = list(self.sagas.get(trabajo_id, []))
            if not pasos:
                return {"trabajo_id": trabajo_id, "estado": "DESCONOCIDA", "pasos": []}
            compensada = any(p["resultado"] == "COMPENSACION" for p in pasos)
            confirmada = any(p["tipo"] == "AsignacionConfirmadaPorHabilitacion"
                             for p in pasos)
            estado = ("COMPENSADA" if compensada else
                      "COMPLETADA" if confirmada else "EN_CURSO")
            return {"trabajo_id": trabajo_id, "estado": estado,
                    "pasos": pasos, "total_pasos": len(pasos),
                    "nota": ("linea de tiempo derivada de los eventos; el saga log "
                             "autoritativo vive en orquestacion-trabajos")}

    def estadisticas(self) -> dict:
        with self._candado:
            return {
                "eventos_aplicados": self._eventos_aplicados,
                "partners": len(self.partners),
                "proveedores": len(self.proveedores),
                "trabajos": len(self.trabajos),
                "asignaciones": len(self.asignaciones),
                "sagas": len(self.sagas),
            }


def _nombre_metodo(tipo: str) -> str:
    """`ReglaDePartnerActualizada` -> `regla_de_partner_actualizada`."""
    fuera = []
    for i, c in enumerate(tipo):
        if c.isupper() and i > 0:
            fuera.append("_")
        fuera.append(c.lower())
    return "".join(fuera)


proyeccion = Proyeccion()


# ── consumidores ─────────────────────────────────────────────────────────────

_TOPICOS_DE_EVENTOS = [
    config.EVT_PARTNERS,
    config.EVT_PROVEEDORES,
    config.EVT_TRABAJOS,
    config.EVT_ASIGNACIONES,
]


def _escuchar(cliente, topico: str, sufijo: str, parar: threading.Event):
    """Un hilo por topico.

    `BytesSchema` y no `AvroSchema`: `evt.trabajos` lleva TRES tipos de evento y
    `evt.asignaciones` lleva CUATRO. Pulsar valida un esquema por consumidor, asi
    que se lee en bytes y se decodifica segun el campo `type` del sobre.

    La suscripcion lleva un sufijo distinto en cada arranque a proposito. Una
    suscripcion duradera recuerda por donde iba, asi que al reiniciar el BFF la
    proyeccion en memoria quedaria vacia y no se volveria a llenar. Con un
    nombre nuevo, cada arranque relee el topico desde el inicio y reconstruye la
    vista. El precio: quedan suscripciones huerfanas en el broker, inofensivas
    aqui porque la retencion del namespace ya es infinita.
    """
    import pulsar

    consumidor = cliente.subscribe(
        topico,
        subscription_name=f"{config.SERVICE_NAME}-proyeccion-{sufijo}",
        consumer_type=pulsar.ConsumerType.Exclusive,
        initial_position=pulsar.InitialPosition.Earliest,
        schema=pulsar.schema.BytesSchema(),
    )
    log.info("escuchando %s desde el inicio", topico)

    while not parar.is_set():
        try:
            mensaje = consumidor.receive(timeout_millis=2000)
        except Exception:                                  # noqa: BLE001
            continue                                       # timeout: revisa `parar`
        try:
            sobre = avro.decodificar(mensaje.data())
            if sobre:
                proyeccion.aplicar(
                    sobre.get("type", ""),
                    sobre.get("data") or {},
                    sobre.get("correlation_id") or "",
                    sobre.get("service_name") or "",
                    sobre.get("time"),
                )
            consumidor.acknowledge(mensaje)
        except Exception as e:                             # noqa: BLE001
            log.exception("error procesando mensaje de %s: %s", topico, e)
            consumidor.negative_acknowledge(mensaje)


def iniciar_consumidores(cliente) -> tuple[list[threading.Thread], threading.Event]:
    parar = threading.Event()
    sufijo = uuid.uuid4().hex[:8]
    hilos = []
    for topico in _TOPICOS_DE_EVENTOS:
        h = threading.Thread(target=_escuchar, args=(cliente, topico, sufijo, parar),
                             daemon=True,
                             name=f"proyeccion-{topico.rsplit('/', 1)[-1]}")
        h.start()
        hilos.append(h)
    return hilos, parar
