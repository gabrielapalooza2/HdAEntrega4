"""Manejadores del agregado Trabajo.

La capa de aplicacion ORQUESTA: abre la transaccion, reconstruye el agregado,
pide una decision al dominio, guarda los eventos, sincroniza la proyeccion y
encola los mensajes salientes. No decide nada de negocio -eso es del dominio- y
no sabe de Pulsar ni de Avro -eso es de la costura-.

─── LA TRANSACCION ES LA PIEZA CENTRAL ───────────────────────────────────
Los cuatro pasos de escritura ocurren dentro de UNA SOLA transaccion de
PostgreSQL:

    1. marcar el mensaje como procesado   (idempotencia)
    2. anexar los eventos al event store  (fuente de verdad)
    3. sincronizar la proyeccion          (lado de lectura)
    4. encolar los mensajes salientes     (outbox)

O se aplican los cuatro, o ninguno. Sin eso habria estados imposibles: un evento
guardado que nadie publica, o un mensaje publicado sobre un evento que se
revirtio, o una marca de idempotencia que bloquea un mensaje cuyo efecto nunca
ocurrio.
───────────────────────────────────────────────────────────────────────────
"""
import logging
import uuid
from datetime import datetime, timezone

from orquestacion import config
from orquestacion.dominio import eventos as ev
from orquestacion.dominio import trabajo as dominio
from orquestacion.infraestructura.persistencia import bd, eventos as almacen, outbox, reglas, trabajos
from orquestacion.mensajeria import contratos as c

logger = logging.getLogger(__name__)

# Espacio de nombres propio para derivar identidades deterministas.
_NS_TRABAJOS = uuid.uuid5(uuid.NAMESPACE_OID, "hogaralpes.orquestacion.trabajos")


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _publicar(cur, eventos_nuevos: list[ev.EventoDeDominio], *,
              trabajo: dominio.Trabajo, correlation_id: str) -> None:
    """Traduce eventos de DOMINIO a mensajes de INTEGRACION y los encola.

    Aqui se ve la distincion con toda claridad: no todo evento de dominio se
    publica, y los que se publican viajan RECORTADOS a lo que el contrato ajeno
    admite. El evento de integracion es una proyeccion del hecho, no el hecho.

    Los mensajes se construyen en VOCABULARIO PROPIO (zona, proveedores_
    excluidos); la traduccion a los nombres del grupo la hace la costura al
    codificar. Esta capa nunca escribe "ciudad" ni "excluir_proveedores".
    """
    for evento in eventos_nuevos:
        mensaje = None

        match evento:
            case ev.TrabajoCreado():
                mensaje = c.TrabajoCreado(
                    trabajo_id=evento.trabajo_id, partner_id=evento.partner_id,
                    mercado_id=evento.mercado_id, categoria=evento.categoria,
                    urgencia=evento.urgencia, zona=evento.zona,
                    sla_minutos=evento.sla_minutos,
                    requiere_aprobacion=evento.requiere_aprobacion,
                )

            case ev.TrabajoRechazado():
                mensaje = c.TrabajoRechazado(
                    trabajo_id=evento.trabajo_id, partner_id=evento.partner_id,
                    categoria=evento.categoria, motivo=evento.motivo,
                    detalle=evento.detalle,
                )

            case ev.ReasignacionSolicitada():
                # El UNICO comando que este servicio emite. Todo lo demas son
                # hechos. Ver decidir_rechazo_de_habilitacion.
                mensaje = c.AsignarProveedor(
                    trabajo_id=evento.trabajo_id, motivo=evento.motivo,
                    proveedores_excluidos=list(evento.proveedores_excluidos),
                    intento=evento.intento,
                )

            # ProveedorAsignado, ProveedorDescartado y TrabajoEscalado NO se
            # publican: son hechos internos de nuestra maquina de estados y
            # ningun contrato del grupo los admite. Se quedan en el event store,
            # que es donde tienen que estar.

        if mensaje is None:
            continue

        sobre = c.empaquetar(mensaje, correlation_id=correlation_id)
        outbox.encolar(cur, topico=mensaje.TOPICO,
                       clave=mensaje.clave_particion(), payload=sobre.a_bytes())


def _confirmar(cur, trabajo_id: str, eventos_nuevos: list[ev.EventoDeDominio],
               *, secuencia_actual: int, correlation_id: str) -> dominio.Trabajo:
    """Pasos 2, 3 y 4: event store, proyeccion y outbox."""
    secuencia = almacen.anexar(cur, trabajo_id, eventos_nuevos,
                               correlation_id=correlation_id,
                               secuencia_actual=secuencia_actual)

    # Se reconstruye el agregado con los eventos nuevos ya aplicados para
    # sincronizar la proyeccion. Releer de la base seria mas lento y daria lo
    # mismo: la transaccion ya ve sus propias escrituras.
    historia = almacen.leer(cur, trabajo_id)
    trabajo = dominio.Trabajo.reconstruir(trabajo_id, historia)
    trabajo.secuencia = secuencia
    trabajos.sincronizar(cur, trabajo)

    _publicar(cur, eventos_nuevos, trabajo=trabajo, correlation_id=correlation_id)
    return trabajo


# ═════════════════════════════════════════════════════════ CrearTrabajo ════

def manejar_crear_trabajo(sobre: c.Sobre) -> None:
    """cmd.trabajos -> TrabajoCreado o TrabajoRechazado."""
    comando: c.CrearTrabajo = sobre.contenido()

    # ─── DE DONDE SALE LA IDENTIDAD ───────────────────────────────────────
    # El contrato del grupo no trae trabajo_id, asi que lo genera este servicio,
    # que es el dueno del agregado. Se DERIVA del id del sobre en vez de sortear
    # un uuid4: asi el mismo comando produce siempre el mismo trabajo_id, y la
    # PK del event store se vuelve una SEGUNDA linea de defensa contra
    # duplicados, por si la primera -mensajes_procesados- fallara.
    trabajo_id = str(uuid.uuid5(_NS_TRABAJOS, sobre.id))

    with bd.pool().connection() as con, con.cursor() as cur:
        if not bd.reclamar_mensaje(cur, sobre.id):
            logger.info("CrearTrabajo: sobre %s repetido, se descarta", sobre.id)
            return

        # Se lee la regla de la PROYECCION LOCAL. No se llama a Motor de Reglas
        # por red: si ese servicio esta caido, aqui sigue estando la ultima
        # regla conocida y este servicio sigue operando. Escenario de
        # disponibilidad.
        regla = reglas.buscar(cur, comando.partner_id)

        evento = dominio.decidir_creacion(
            trabajo_id, partner_id=comando.partner_id, categoria=comando.categoria,
            zona=comando.zona, regla=regla, ahora=_ahora(),
            mercado_id=comando.mercado_id, urgencia=comando.urgencia,
            descripcion=comando.descripcion, monto_estimado=comando.monto_estimado,
            moneda=comando.moneda,
        )

        _confirmar(cur, trabajo_id, [evento], secuencia_actual=0,
                   correlation_id=sobre.correlation_id)

    if isinstance(evento, ev.TrabajoCreado):
        logger.info("Trabajo %s CREADO partner=%s cat=%s sla=%smin (regla v%s) "
                    "vence=%s", trabajo_id, evento.partner_id, evento.categoria,
                    evento.sla_minutos, evento.regla_version,
                    evento.vence_en.isoformat())
    else:
        logger.info("Trabajo %s RECHAZADO partner=%s motivo=%s | %s",
                    trabajo_id, evento.partner_id, evento.motivo, evento.detalle)


# ═══════════════════════════════════════════════════════ TrabajoAsignado ═══

def manejar_trabajo_asignado(sobre: c.Sobre) -> None:
    """evt.trabajos -> estado ASIGNADO. Detiene el reloj del SLA.

    El sobre ya paso el filtro anti-eco del consumidor: si llega hasta aqui, no
    lo emitimos nosotros.
    """
    mensaje: c.TrabajoAsignado = sobre.contenido()

    with bd.pool().connection() as con, con.cursor() as cur:
        if not bd.reclamar_mensaje(cur, sobre.id):
            logger.info("TrabajoAsignado: sobre %s repetido, se descarta", sobre.id)
            return

        historia = almacen.leer(cur, mensaje.trabajo_id)
        trabajo = dominio.Trabajo.reconstruir(mensaje.trabajo_id, historia)

        if not trabajo.existe:
            # Emparejamiento asigno un trabajo que no conocemos. Puede pasar si
            # el TrabajoCreado todavia no se proceso. Se deja reintentar.
            raise LookupError(
                f"TrabajoAsignado para {mensaje.trabajo_id}, que aun no existe "
                f"en el event store; se devuelve al broker para reintentar")

        nuevos = dominio.decidir_asignacion(
            trabajo, proveedor_id=mensaje.proveedor_id,
            asignacion_id=mensaje.asignacion_id)

        if not nuevos:
            logger.info("Trabajo %s: asignacion sin efecto (estado %s)",
                        trabajo.trabajo_id, trabajo.estado.value)
            return

        _confirmar(cur, trabajo.trabajo_id, nuevos,
                   secuencia_actual=trabajo.secuencia,
                   correlation_id=sobre.correlation_id)

    logger.info("Trabajo %s ASIGNADO a %s", mensaje.trabajo_id, mensaje.proveedor_id)


# ════════════════════════════════ AsignacionRechazadaPorHabilitacion ═══════

def manejar_asignacion_rechazada(sobre: c.Sobre) -> None:
    """evt.asignaciones -> reintento acotado, o escalamiento.

    EL UNICO PUNTO ORQUESTADO DEL SISTEMA. Ver
    dominio.decidir_rechazo_de_habilitacion.
    """
    mensaje: c.AsignacionRechazadaPorHabilitacion = sobre.contenido()

    with bd.pool().connection() as con, con.cursor() as cur:
        if not bd.reclamar_mensaje(cur, sobre.id):
            logger.info("AsignacionRechazada: sobre %s repetido, se descarta",
                        sobre.id)
            return

        historia = almacen.leer(cur, mensaje.trabajo_id)
        trabajo = dominio.Trabajo.reconstruir(mensaje.trabajo_id, historia)

        if not trabajo.existe:
            raise LookupError(
                f"AsignacionRechazada para {mensaje.trabajo_id}, que aun no "
                f"existe en el event store; se devuelve al broker")

        nuevos = dominio.decidir_rechazo_de_habilitacion(
            trabajo, proveedor_id=mensaje.proveedor_id,
            motivo=mensaje.motivo or mensaje.estado_real,
            max_intentos=config.MAX_INTENTOS_ASIGNACION)

        if not nuevos:
            return

        _confirmar(cur, trabajo.trabajo_id, nuevos,
                   secuencia_actual=trabajo.secuencia,
                   correlation_id=sobre.correlation_id)

    for evento in nuevos:
        if isinstance(evento, ev.ReasignacionSolicitada):
            logger.info("Trabajo %s: intento %s, se pide otro proveedor "
                        "(excluidos %s)", mensaje.trabajo_id, evento.intento,
                        sorted(evento.proveedores_excluidos))
        elif isinstance(evento, ev.TrabajoEscalado):
            logger.warning("Trabajo %s ESCALADO_MANUAL: %s | %s",
                           mensaje.trabajo_id, evento.motivo, evento.detalle)


# ══════════════════════════════════════════════════════ barrido de SLA ═════

def barrer_sla(ahora: datetime | None = None) -> int:
    """Escala los trabajos cuyo SLA vencio. Devuelve cuantos escalo.

    Hace falta porque LOS EVENTOS TE DICEN LO QUE PASO, NUNCA LO QUE NO PASO.
    En coreografia nadie espera: si Emparejamiento jamas responde no llega
    ningun mensaje, y sin este barrido el trabajo se queda quieto para siempre.
    El paso del tiempo es el unico estimulo que ningun broker puede entregar.

    Cada trabajo se escala en SU PROPIA transaccion: un trabajo que falle no
    debe impedir que se escalen los demas del lote.
    """
    # El reloj se inyecta para poder probar el vencimiento adelantando el
    # tiempo, en vez de EDITANDO eventos ya ocurridos. Un event store append-only
    # no se puede envejecer a mano, ni siquiera en una prueba.
    ahora = ahora or _ahora()
    with bd.pool().connection() as con, con.cursor() as cur:
        candidatos = trabajos.vencidos(cur, ahora)

    escalados = 0
    for trabajo_id in candidatos:
        try:
            with bd.pool().connection() as con, con.cursor() as cur:
                historia = almacen.leer(cur, trabajo_id)
                trabajo = dominio.Trabajo.reconstruir(trabajo_id, historia)

                # Se vuelve a evaluar contra el EVENT STORE y no contra la
                # proyeccion: entre la consulta del lote y este momento pudo
                # llegar la asignacion, y la proyeccion pudo quedar rezagada.
                # La fuente de verdad manda.
                nuevos = dominio.decidir_vencimiento(trabajo, ahora)
                if not nuevos:
                    continue

                _confirmar(cur, trabajo_id, nuevos,
                           secuencia_actual=trabajo.secuencia,
                           # Cadena nueva: el vencimiento no lo origino ningun
                           # mensaje, lo origino el reloj.
                           correlation_id=str(uuid.uuid4()))
            escalados += 1
            logger.warning("Trabajo %s ESCALADO_MANUAL por SLA vencido", trabajo_id)
        except almacen.ConflictoDeConcurrencia:
            # Alguien mas escribio sobre este trabajo mientras lo escalabamos.
            # Se deja para la vuelta siguiente: en 30 segundos se reevalua.
            logger.info("Trabajo %s cambio durante el barrido; se reevalua luego",
                        trabajo_id)
    return escalados
