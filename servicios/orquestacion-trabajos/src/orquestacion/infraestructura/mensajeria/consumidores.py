"""Consumidores de Pulsar. El unico lugar del servicio que recibe del broker.

El bucle es generico: decodifica con la costura, descarta lo que no nos toca y
despacha por el campo `type` del sobre. Los topicos son POR AGREGADO, no por
tipo de mensaje, asi que recibir tipos que no modelamos es lo normal.
"""
import logging
import threading
from dataclasses import dataclass, field
from typing import Callable

import _pulsar
import pulsar

from orquestacion import config
from orquestacion.mensajeria import contratos as c

logger = logging.getLogger(__name__)

Manejador = Callable[[c.Sobre], None]


@dataclass(frozen=True)
class Suscripcion:
    topico: str
    nombre: str
    tipo: int
    manejadores: dict[str, Manejador]
    desde_el_inicio: bool = False
    compactado: bool = False


def _abrir(cliente: pulsar.Client, sus: Suscripcion):
    return cliente.subscribe(
        sus.topico,
        subscription_name=sus.nombre,
        consumer_type=sus.tipo,
        # BytesSchema y no AvroSchema: evt.trabajos lleva TRES tipos y Pulsar
        # registra un solo esquema por topico. La costura decodifica a mano.
        schema=pulsar.schema.BytesSchema(),
        is_read_compacted=sus.compactado,
        initial_position=(_pulsar.InitialPosition.Earliest if sus.desde_el_inicio
                          else _pulsar.InitialPosition.Latest),
    )


def escuchar(sus: Suscripcion, parar: threading.Event) -> None:
    """Bucle de consumo. Se lanza en un hilo por suscripcion."""
    cliente = pulsar.Client(
        config.broker_url(),
        # Warn y no Info: por defecto el cliente nativo escupe ~30 lineas por
        # conexion y sepulta el log util del servicio.
        logger=pulsar.ConsoleLogger(pulsar.LoggerLevel.Warn),
        **config.opciones_cliente(),
    )
    try:
        consumidor = _abrir(cliente, sus)
        logger.info("Escuchando %s (suscripcion %s)", sus.topico, sus.nombre)

        while not parar.is_set():
            try:
                # Con timeout, no sin el: un receive() bloqueante para siempre
                # dejaria el hilo sordo a la senal de apagado.
                mensaje = consumidor.receive(timeout_millis=1000)
            except Exception:
                continue

            try:
                _despachar(sus, mensaje)
                consumidor.acknowledge(mensaje)
            except Exception:
                logger.exception("Error procesando mensaje de %s; se devuelve "
                                 "al broker", sus.topico)
                # negative_acknowledge hace que Pulsar lo REENTREGUE en vez de
                # perderlo. Es seguro porque el efecto y la marca de
                # idempotencia comparten transaccion: si fallo, no quedo nada a
                # medias.
                consumidor.negative_acknowledge(mensaje)
    finally:
        cliente.close()
        logger.info("Consumidor de %s detenido", sus.topico)


def _despachar(sus: Suscripcion, mensaje) -> None:
    sobre = c.decodificar(mensaje.data())

    if sobre is None:
        # Tipo de otro equipo, o bytes que no casan con ningun contrato nuestro.
        # Se confirma igual: reintentarlo daria el mismo resultado para siempre.
        logger.debug("Mensaje ilegible en %s (%s bytes)", sus.topico,
                     len(mensaje.data()))
        return

    # ─── MITIGACION DEL CICLO DE evt.trabajos ─────────────────────────────
    # Publicamos TrabajoCreado y TrabajoRechazado en evt.trabajos, y tenemos que
    # CONSUMIR ESE MISMO TOPICO porque es ahi donde Emparejamiento publica
    # TrabajoAsignado y no existe ningun ProveedorAsignado en otro lado.
    #
    # Sin este filtro reaccionariamos a nuestro propio eco. Es una mitigacion,
    # no una solucion: la solucion es que Emparejamiento publique en
    # evt.asignaciones y mover el consumidor alli.
    if sobre.es_propio():
        logger.debug("Eco propio en %s (%s), descartado", sus.topico, sobre.type)
        return

    manejador = sus.manejadores.get(sobre.type)
    if manejador is None:
        logger.debug("Tipo %s no manejado en %s", sobre.type, sus.topico)
        return

    manejador(sobre)


# ═════════════════════════════════════════════════════════ suscripciones ═══

def suscripciones() -> list[Suscripcion]:
    """Que escucha este servicio. Crece con cada fase."""
    from orquestacion.aplicacion import reglas as aplicacion_reglas
    from orquestacion.aplicacion import trabajos as aplicacion_trabajos

    return [
        # ─── evt.partners ─────────────────────────────────────────────────
        # Topico NO PARTICIONADO y COMPACTADO: es un stream clave-valor donde
        # solo importa el ultimo estado de cada partner.
        #
        # DESVIACION DEL DISENO INICIAL, a conciencia: la especificacion decia
        # suscripcion Shared, pero Pulsar RECHAZA `read_compacted` sobre una
        # suscripcion Shared (InvalidConfiguration; verificado contra el broker).
        # Y sin read_compacted la compactacion del topico no sirve de nada: un
        # arranque en frio tendria que releer el historico entero en vez de la
        # ultima regla por partner.
        #
        # Se elige Failover, que ademas preserva el orden por partner. Como el
        # topico no esta particionado y los cambios de regla son administrativos
        # y raros, no se pierde escalabilidad: no hay volumen que repartir.
        Suscripcion(
            topico=c.TOPICO_EVT_PARTNERS,
            nombre="orquestacion-trabajos-reglas",
            tipo=_pulsar.ConsumerType.Failover,
            # Desde el inicio y compactado: asi una replica nueva, o una base
            # recien creada, RECONSTRUYE la proyeccion de reglas sola, leyendo
            # la ultima version de cada partner. Es la razon de que el topico
            # este compactado.
            desde_el_inicio=True,
            compactado=True,
            manejadores={
                c.ReglaDePartnerActualizada.TIPO:
                    aplicacion_reglas.manejar_regla_actualizada,
            },
        ),

        # ─── cmd.trabajos ─────────────────────────────────────────────────
        # Failover y no Shared: con Failover hay un consumidor activo POR
        # PARTICION, asi que las tres particiones se consumen en paralelo pero
        # el orden DENTRO de cada una se preserva. Como la clave de particion es
        # el partner_id, los comandos de un mismo partner se procesan en orden.
        Suscripcion(
            topico=c.TOPICO_CMD_TRABAJOS,
            nombre="orquestacion-trabajos-comandos",
            tipo=_pulsar.ConsumerType.Failover,
            manejadores={
                c.CrearTrabajo.TIPO: aplicacion_trabajos.manejar_crear_trabajo,
            },
        ),

        # ─── evt.trabajos ─────────────────────────────────────────────────
        # NUESTRO PROPIO TOPICO. Ver la NOTA DEL CICLO en contratos.py y el
        # filtro `es_propio` de _despachar: sin el, reaccionariamos a nuestro
        # propio eco.
        #
        # Key_Shared y no Shared: reparte entre consumidores PERO garantiza que
        # todos los mensajes de una misma clave -un mismo trabajo_id- caen
        # siempre en el mismo consumidor. Sin eso, dos eventos del mismo trabajo
        # podrian procesarse en paralelo y chocar en el control de concurrencia
        # optimista una y otra vez.
        Suscripcion(
            topico=c.TOPICO_EVT_TRABAJOS,
            nombre="orquestacion-trabajos-asignaciones",
            tipo=_pulsar.ConsumerType.KeyShared,
            manejadores={
                c.TrabajoAsignado.TIPO: aplicacion_trabajos.manejar_trabajo_asignado,
            },
        ),

        # ─── evt.asignaciones ─────────────────────────────────────────────
        # La compensacion. Shared porque cada rechazo es independiente y el
        # control de concurrencia optimista ya protege el agregado.
        Suscripcion(
            topico=c.TOPICO_EVT_ASIGNACIONES,
            nombre="orquestacion-trabajos-rechazos",
            tipo=_pulsar.ConsumerType.Shared,
            manejadores={
                c.AsignacionRechazadaPorHabilitacion.TIPO:
                    aplicacion_trabajos.manejar_asignacion_rechazada,
                c.AsignacionConfirmadaPorHabilitacion.TIPO:
                    aplicacion_trabajos.manejar_asignacion_confirmada,
                c.AsignacionAceptadaPorReglaPartner.TIPO:
                    aplicacion_trabajos.manejar_regla_aceptada,
                c.AsignacionRechazadaPorReglaPartner.TIPO:
                    aplicacion_trabajos.manejar_regla_rechazada,
            },
        ),
    ]


def arrancar(parar: threading.Event) -> list[threading.Thread]:
    hilos = []
    for sus in suscripciones():
        hilo = threading.Thread(target=escuchar, args=(sus, parar),
                                name=f"consumidor-{sus.topico.rsplit('/', 1)[-1]}",
                                daemon=True)
        hilo.start()
        hilos.append(hilo)
    return hilos
