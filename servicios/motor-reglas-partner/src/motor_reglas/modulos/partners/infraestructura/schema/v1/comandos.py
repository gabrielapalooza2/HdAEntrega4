"""Esquemas Avro de los COMANDOS que este servicio consume.

Un comando se dirige a un destinatario concreto y puede ser rechazado. Por eso
tiene su propio tópico y no viaja en el de eventos.
"""

import uuid

from pulsar.schema import Array, Float, Integer, Long, Record, String

from motor_reglas.seedwork.infraestructura.schema.v1.comandos import ComandoIntegracion
from motor_reglas.seedwork.infraestructura.utils import time_millis

from .eventos import DineroSchema


class RegistrarPartnerPayload(Record):
    partner_id = String(default="")           # vacío = lo asigna el servicio
    nombre = String()
    tipo_partner = String()
    convenio_numero = String()
    vigencia_desde = Long()
    vigencia_hasta = Long(default=0)
    porcentaje_comision = Float(default=0.0)
    moneda_tarifa = String(default="COP")

    cobertura_contratada = Array(String())
    sla_minutos = Integer()
    monto_maximo_sin_aprobacion = DineroSchema()
    pasos_de_aprobacion = Array(String())
    red_homologada = Array(String())


class ComandoRegistrarPartner(ComandoIntegracion):
    id = String(default=str(uuid.uuid4()))
    time = Long()
    ingestion = Long(default=time_millis())
    specversion = String(default="v1")
    type = String(default="RegistrarPartner")
    datacontenttype = String(default="AVRO")
    service_name = String(default="motor-reglas-partner")
    correlation_id = String()
    data = RegistrarPartnerPayload()


class ActualizarReglaDePartnerPayload(Record):
    partner_id = String()
    cobertura_contratada = Array(String())
    sla_minutos = Integer()
    monto_maximo_sin_aprobacion = DineroSchema()
    pasos_de_aprobacion = Array(String())
    red_homologada = Array(String())


class ComandoActualizarReglaDePartner(ComandoIntegracion):
    id = String(default=str(uuid.uuid4()))
    time = Long()
    ingestion = Long(default=time_millis())
    specversion = String(default="v1")
    type = String(default="ActualizarReglaDePartner")
    datacontenttype = String(default="AVRO")
    service_name = String(default="motor-reglas-partner")
    correlation_id = String()
    data = ActualizarReglaDePartnerPayload()
