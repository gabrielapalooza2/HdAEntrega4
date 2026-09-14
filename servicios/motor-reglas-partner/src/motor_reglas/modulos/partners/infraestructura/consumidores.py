"""Consumidor de COMANDOS desde Apache Pulsar.

Este es el canal por el que otros servicios le hablan a Motor reglas partner. No
hay ningún endpoint HTTP entre servicios: la API REST de este servicio existe solo
para que un operador o el BFF de la entrega 5 empujen comandos desde afuera del
sistema.

Suscripción `Shared` y no `Exclusive`: con Shared, N réplicas del servicio reparten
los mensajes de la misma suscripción y el consumo escala horizontalmente. Con
Exclusive solo una réplica recibiría, y el escenario de escalabilidad no se podría
demostrar.
"""

import logging
import traceback
from datetime import datetime

import _pulsar
import pulsar
from pulsar.schema import AvroSchema

from motor_reglas.config.db import db
from motor_reglas.seedwork.aplicacion.comandos import ejecutar_comando
from motor_reglas.seedwork.infraestructura import utils
from motor_reglas.seedwork.infraestructura.utils import millis_a_datetime

from ..aplicacion.comandos.actualizar_regla import ActualizarReglaDePartner
from ..aplicacion.comandos.registrar_partner import RegistrarPartner
from .dto import MensajeProcesado
from .schema.v1.comandos import ComandoActualizarReglaDePartner, ComandoRegistrarPartner

logger = logging.getLogger(__name__)

TOPICO_COMANDOS_PARTNER = "persistent://hda/poc/comandos-partner"


def _ya_procesado(mensaje_id: str) -> bool:
    """Idempotencia. Pulsar entrega al menos una vez."""
    return db.session.query(MensajeProcesado).filter_by(mensaje_id=mensaje_id).one_or_none() is not None


def _marcar_procesado(mensaje_id: str):
    db.session.add(MensajeProcesado(mensaje_id=mensaje_id, procesado_en=datetime.utcnow()))
    db.session.commit()


def _manejar_registrar_partner(datos, correlation_id: str):
    comando = RegistrarPartner(
        partner_id=datos.partner_id or None,
        nombre=datos.nombre,
        tipo_partner=datos.tipo_partner,
        convenio_numero=datos.convenio_numero,
        vigencia_desde=millis_a_datetime(datos.vigencia_desde),
        vigencia_hasta=millis_a_datetime(datos.vigencia_hasta) if datos.vigencia_hasta else None,
        porcentaje_comision=datos.porcentaje_comision,
        moneda_tarifa=datos.moneda_tarifa,
        cobertura_contratada=list(datos.cobertura_contratada),
        sla_minutos=datos.sla_minutos,
        monto_maximo_monto=datos.monto_maximo_sin_aprobacion.monto,
        monto_maximo_moneda=datos.monto_maximo_sin_aprobacion.moneda,
        pasos_de_aprobacion=list(datos.pasos_de_aprobacion),
        red_homologada=list(datos.red_homologada),
        correlation_id=correlation_id,
    )
    return ejecutar_comando(comando)


def suscribirse_a_comandos(app=None, topico: str = TOPICO_COMANDOS_PARTNER):
    cliente = None
    try:
        cliente = pulsar.Client(utils.broker_url())
        consumidor = cliente.subscribe(
            topico,
            consumer_type=_pulsar.ConsumerType.Shared,
            subscription_name="motor-reglas-partner-sub-comandos",
            schema=AvroSchema(ComandoRegistrarPartner),
        )
        logger.info("Escuchando comandos en %s", topico)

        while True:
            mensaje = consumidor.receive()
            try:
                with app.app_context():
                    if _ya_procesado(mensaje.value().id):
                        logger.info("Comando %s ya procesado; se descarta", mensaje.value().id)
                        consumidor.acknowledge(mensaje)
                        continue

                    _manejar_registrar_partner(mensaje.value().data, mensaje.value().correlation_id)
                    _marcar_procesado(mensaje.value().id)

                consumidor.acknowledge(mensaje)
            except Exception:
                logger.exception("Error procesando el comando; se devuelve al broker")
                # negative_acknowledge hace que Pulsar lo reentregue en vez de perderlo
                consumidor.negative_acknowledge(mensaje)

    except Exception:
        logger.error("ERROR suscribiéndose al tópico de comandos")
        traceback.print_exc()
    finally:
        if cliente:
            cliente.close()
