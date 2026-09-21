"""Records copiados de entrega4/contratos/generar.py (solo produce/consume).

AVISO: Record de pulsar-client NO serializa campos heredados. Los ocho campos
del sobre CloudEvents se repiten en cada clase.
"""
from pulsar.schema import Array, Boolean, Float, Integer, Long, Record, String


class Dinero(Record):
    monto = Long()
    moneda = String()


class ReglaDePartnerActualizadaPayload(Record):
    partner_id = String()
    convenio_id = String()
    nombre = String()
    tipo_partner = String()
    activo = Boolean()
    vigencia_desde = Long()
    vigencia_hasta = Long(default=0)
    version_regla = Integer()
    cobertura_contratada = Array(String())
    sla_minutos = Integer()
    monto_maximo_sin_aprobacion = Dinero()
    pasos_de_aprobacion = Array(String())
    red_homologada = Array(String())
    porcentaje_comision = Float(default=0.0)
    moneda_tarifa = String(default="")


class EventoReglaDePartnerActualizada(Record):
    """evt.partners (COMPACTADO, clave=partner_id). Consume Emparejamiento."""
    id = String(); time = Long(); ingestion = Long()
    specversion = String(default="v1"); type = String(default="ReglaDePartnerActualizada")
    datacontenttype = String(default="AVRO"); service_name = String(); correlation_id = String()
    data = ReglaDePartnerActualizadaPayload()


class EstadoDeHabilitacionCambiadoPayload(Record):
    proveedor_id = String()
    nombre = String()
    estado = String()
    categorias = Array(String())
    ciudades = Array(String())
    motivo = String(default="")
    vigente_hasta = Long(default=0)


class EventoEstadoDeHabilitacionCambiado(Record):
    """evt.proveedores (COMPACTADO, clave=proveedor_id). Consume Emparejamiento."""
    id = String(); time = Long(); ingestion = Long()
    specversion = String(default="v1"); type = String(default="EstadoDeHabilitacionCambiado")
    datacontenttype = String(default="AVRO"); service_name = String(); correlation_id = String()
    data = EstadoDeHabilitacionCambiadoPayload()


class TrabajoCreadoPayload(Record):
    trabajo_id = String()
    partner_id = String()
    mercado_id = String()
    categoria = String()
    urgencia = String()
    ciudad = String()
    sla_minutos = Integer()
    requiere_aprobacion = Boolean(default=False)


class EventoTrabajoCreado(Record):
    """evt.trabajos (clave=trabajo_id). Consume Emparejamiento."""
    id = String(); time = Long(); ingestion = Long()
    specversion = String(default="v1"); type = String(default="TrabajoCreado")
    datacontenttype = String(default="AVRO"); service_name = String(); correlation_id = String()
    data = TrabajoCreadoPayload()


class TrabajoRechazadoPayload(Record):
    trabajo_id = String()
    partner_id = String()
    categoria = String()
    motivo = String()
    detalle = String(default="")


class EventoTrabajoRechazado(Record):
    """evt.trabajos. Emparejamiento filtra por type y no procesa."""
    id = String(); time = Long(); ingestion = Long()
    specversion = String(default="v1"); type = String(default="TrabajoRechazado")
    datacontenttype = String(default="AVRO"); service_name = String(); correlation_id = String()
    data = TrabajoRechazadoPayload()


class TrabajoAsignadoPayload(Record):
    trabajo_id = String()
    asignacion_id = String()
    proveedor_id = String()
    partner_id = String()
    sla_vence_en = Long()
    origen_habilitacion = String(default="PROYECCION_LOCAL")


class EventoTrabajoAsignado(Record):
    """evt.trabajos. Único productor: Emparejamiento."""
    id = String(); time = Long(); ingestion = Long()
    specversion = String(default="v1"); type = String(default="TrabajoAsignado")
    datacontenttype = String(default="AVRO"); service_name = String(); correlation_id = String()
    data = TrabajoAsignadoPayload()


class AsignacionRechazadaPorHabilitacionPayload(Record):
    trabajo_id = String()
    asignacion_id = String()
    proveedor_id = String()
    estado_real = String()
    motivo = String()
    verificado_en = Long()


class EventoAsignacionRechazadaPorHabilitacion(Record):
    """evt.asignaciones. Consume Emparejamiento (marca RECHAZADO, no reasigna)."""
    id = String(); time = Long(); ingestion = Long()
    specversion = String(default="v1")
    type = String(default="AsignacionRechazadaPorHabilitacion")
    datacontenttype = String(default="AVRO"); service_name = String(); correlation_id = String()
    data = AsignacionRechazadaPorHabilitacionPayload()


class AsignacionConfirmadaPorHabilitacionPayload(Record):
    trabajo_id = String()
    asignacion_id = String()
    proveedor_id = String()
    estado_real = String()
    verificado_en = Long()


class EventoAsignacionConfirmadaPorHabilitacion(Record):
    """evt.asignaciones. Consume Emparejamiento (marca CONFIRMADO)."""
    id = String(); time = Long(); ingestion = Long()
    specversion = String(default="v1")
    type = String(default="AsignacionConfirmadaPorHabilitacion")
    datacontenttype = String(default="AVRO"); service_name = String(); correlation_id = String()
    data = AsignacionConfirmadaPorHabilitacionPayload()
