"""Esquemas Avro de los eventos de INTEGRACIÓN que publica este servicio.

Estos Records SON el contrato. pulsar-client deriva el esquema Avro de la clase y
lo registra en el Schema Registry nativo de Apache Pulsar, que rechaza en el
momento de conectar cualquier productor cuyo esquema viole la política de
compatibilidad del namespace. El contrato deja de depender de la disciplina del
equipo y pasa a estar aplicado por el broker.

RECORDATORIO: pulsar.schema.Record no serializa campos heredados. Los campos del
sobre CloudEvents están repetidos a propósito en cada clase concreta.
"""

import uuid

from pulsar.schema import Array, Boolean, Float, Integer, Long, Record, String

from motor_reglas.seedwork.infraestructura.schema.v1.eventos import EventoIntegracion
from motor_reglas.seedwork.infraestructura.utils import time_millis


class DineroSchema(Record):
    monto = Long()
    moneda = String()


class ReglaDePartnerActualizadaPayload(Record):
    """EVENTO CON CARGA DE ESTADO (event-carried state transfer).

    Lleva la regla COMPLETA, no un aviso de que cambió. La razón es el escenario de
    disponibilidad: Orquestación de trabajos tiene que poder seguir resolviendo
    trabajos con este servicio apagado. Si el evento fuera delgado, el consumidor
    tendría que venir a preguntar y el acoplamiento de disponibilidad volvería por
    la puerta de atrás.

    El precio, declarado: el mensaje es más grande y hay consistencia eventual.
    """

    partner_id = String()
    convenio_id = String()
    nombre = String()
    tipo_partner = String()
    activo = Boolean()

    vigencia_desde = Long()
    vigencia_hasta = Long(default=0)          # 0 = sin fecha de fin

    version_regla = Integer()
    cobertura_contratada = Array(String())
    sla_minutos = Integer()
    monto_maximo_sin_aprobacion = DineroSchema()
    pasos_de_aprobacion = Array(String())
    red_homologada = Array(String())

    porcentaje_comision = Float(default=0.0)
    moneda_tarifa = String(default="")


class EventoReglaDePartnerActualizada(EventoIntegracion):
    id = String(default=str(uuid.uuid4()))
    time = Long()
    ingestion = Long(default=time_millis())
    specversion = String(default="v1")
    type = String(default="ReglaDePartnerActualizada")
    datacontenttype = String(default="AVRO")
    service_name = String(default="motor-reglas-partner")
    correlation_id = String()
    data = ReglaDePartnerActualizadaPayload()
