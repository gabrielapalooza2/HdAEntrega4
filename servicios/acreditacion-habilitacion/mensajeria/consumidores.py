"""Consumidores reales de Pulsar. Arrancan como threads en background
desde infraestructura/http/api.py (un solo contenedor, un solo proceso,
igual que el resto de los servicios del equipo).
"""
from __future__ import annotations

import logging
import threading
import uuid

import pulsar

from dominio.excepciones import ExcepcionDominio
from infraestructura.db import Session
from infraestructura.idempotencia import marcar_procesado, ya_procesado
from infraestructura.repositorios import RepositorioProveedoresSQLAlchemy

from aplicacion.comandos import acreditar_proveedor, suspender_proveedor, verificar_asignacion

from . import contratos
from .cliente import (
    SUSCRIPCION_CMD_PROVEEDORES,
    SUSCRIPCION_EVT_TRABAJOS,
    TOPICO_CMD_PROVEEDORES,
    TOPICO_EVT_TRABAJOS,
    Publicador,
    crear_cliente,
)

logger = logging.getLogger(__name__)


def _despachar_comando_proveedores(sobre: dict, session, publicar_evento):
    tipo, data = sobre["type"], (sobre.get("data") or {})

    if tipo == "AcreditarProveedor":
        comando = acreditar_proveedor.AcreditarProveedor(
            proveedor_id=data.get("proveedor_id"), nombre=data.get("nombre") or "",
            categorias=data.get("categorias") or [], ciudades=data.get("ciudades") or [],
            vigente_hasta=contratos.epoch_millis_a_datetime(data.get("vigente_hasta")),
        )
        repositorio = RepositorioProveedoresSQLAlchemy(session)
        acreditar_proveedor.ejecutar(comando, repositorio, session, publicar_evento)

    elif tipo == "SuspenderProveedor":
        comando = suspender_proveedor.SuspenderProveedor(
            proveedor_id=data.get("proveedor_id"), motivo=data.get("motivo") or "",
        )
        repositorio = RepositorioProveedoresSQLAlchemy(session)
        suspender_proveedor.ejecutar(comando, repositorio, session, publicar_evento)

    else:
        raise NotImplementedError(f"cmd.proveedores no reconoce el type '{tipo}'")


def _despachar_evento_trabajos(sobre: dict, session, publicar_evento):
    data = sobre.get("data") or {}
    comando = verificar_asignacion.VerificarAsignacion(
        trabajo_id=data.get("trabajo_id"), asignacion_id=data.get("asignacion_id"),
        proveedor_id=data.get("proveedor_id"),
    )
    repositorio = RepositorioProveedoresSQLAlchemy(session)
    verificar_asignacion.ejecutar(comando, repositorio, session, publicar_evento)


def _procesar_mensaje(msg: pulsar.Message, tipos_validos: set[str], despachar, publicador: Publicador) -> bool:
    propiedades = msg.properties() or {}
    tipo = propiedades.get("type")

    if tipo not in tipos_validos:
        logger.debug("Ignorando type='%s' (fuera de interes de este consumidor)", tipo)
        return True

    try:
        sobre = contratos.decodificar(tipo, msg.data())
    except Exception:
        logger.exception("Error decodificando Avro, se descarta (ack)")
        return True

    evento_id = sobre.get("id")
    correlation_id = sobre.get("correlation_id") or propiedades.get("correlation_id") or str(uuid.uuid4())

    session = Session()
    try:
        if evento_id and ya_procesado(session, evento_id):
            logger.info("evento_id=%s ya procesado (idempotencia)", evento_id)
            return True

        publicar_evento = lambda evento: publicador.publicar(evento, correlation_id)
        despachar(sobre, session, publicar_evento)

        if evento_id:
            marcar_procesado(session, evento_id)
            session.commit()
        return True

    except ExcepcionDominio as e:
        logger.error("Error de dominio: %s", e)
        session.rollback()
        return True
    except Exception as e:
        logger.exception("Error de infraestructura, se reintentara: %s", e)
        session.rollback()
        return False
    finally:
        session.close()


def _loop(consumer: pulsar.Consumer, tipos_validos: set[str], despachar, publicador: Publicador, nombre: str):
    logger.info("Consumidor '%s' iniciado", nombre)
    while True:
        msg = consumer.receive()
        if _procesar_mensaje(msg, tipos_validos, despachar, publicador):
            consumer.acknowledge(msg)
        else:
            consumer.negative_acknowledge(msg)


def iniciar_en_background() -> pulsar.Client:
    """Se llama UNA vez al crear la app Flask (ver infraestructura/http/api.py).
    Arranca ambos consumidores como daemon threads y devuelve el cliente
    para poder cerrarlo en shutdown si hace falta."""
    cliente = crear_cliente()
    publicador = Publicador(cliente)

    consumer_comandos = cliente.subscribe(
        TOPICO_CMD_PROVEEDORES, SUSCRIPCION_CMD_PROVEEDORES,
        consumer_type=pulsar.ConsumerType.Failover,
    )
    consumer_trabajos = cliente.subscribe(
        TOPICO_EVT_TRABAJOS, SUSCRIPCION_EVT_TRABAJOS,
        consumer_type=pulsar.ConsumerType.KeyShared,
    )

    threading.Thread(
        target=_loop,
        args=(consumer_comandos, contratos.TIPOS_CMD_PROVEEDORES, _despachar_comando_proveedores, publicador, "cmd.proveedores"),
        daemon=True,
    ).start()

    threading.Thread(
        target=_loop,
        args=(consumer_trabajos, contratos.TIPOS_EVT_TRABAJOS, _despachar_evento_trabajos, publicador, "evt.trabajos"),
        daemon=True,
    ).start()

    return cliente
