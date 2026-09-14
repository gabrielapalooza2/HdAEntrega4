"""Sobre común de todos los mensajes, siguiendo la especificación CloudEvents.

Por qué CloudEvents y no un sobre propio: es un estándar CNCF, así que el sobre
deja de ser una convención interna del equipo y pasa a ser algo que cualquier
herramienta de observabilidad entiende. `specversion` versiona el sobre y `type`
versiona el contenido: son dos ejes de evolución independientes.

AVISO IMPORTANTE (documentado también en el tutorial 7 del curso): la clase
`Record` de pulsar-client NO reconoce campos heredados al serializar. Los campos
del sobre deben REPETIRSE en cada clase concreta o los valores se pierden en el
encoding. Esta jerarquía existe por claridad conceptual; la repetición de abajo
es obligatoria.
"""

import uuid

from pulsar.schema import Long, Record, String

from motor_reglas.seedwork.infraestructura.utils import time_millis


class Mensaje(Record):
    id = String(default=str(uuid.uuid4()))
    time = Long()
    ingestion = Long(default=time_millis())
    specversion = String(default="v1")
    type = String()
    datacontenttype = String(default="AVRO")
    service_name = String()
    correlation_id = String()
