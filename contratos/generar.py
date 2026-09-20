#!/usr/bin/env python3
"""FUENTE DE VERDAD de los contratos del equipo — Hogar de los Alpes, Entrega 4.

Este archivo define los 12 mensajes del sistema como `Record` de pulsar-client, y
genera los .avsc que se versionan en el repositorio.

COMO LO USA CADA PERSONA
------------------------
Copie a su servicio SOLO las clases de los mensajes que produce o consume, en
`<su_servicio>/infraestructura/schema/v1/`. No importe este archivo: crearia una
dependencia de codigo entre los cuatro servicios, y el unico acoplamiento que
queremos es el del esquema registrado en el broker.

    python generar.py          # regenera todos los .avsc
"""
import json
import os

from pulsar.schema import Array, Boolean, Float, Integer, Long, Record, String

# ─────────────────────────────────────────────────────────────────────────────
# EL SOBRE COMUN — especificacion CloudEvents
#
# AVISO CRITICO: `Record` de pulsar-client NO serializa campos heredados. Si estos
# ocho campos no se REPITEN literalmente en cada clase concreta, los valores se
# pierden al codificar. Esta limitacion esta documentada en el tutorial 7 del curso.
# Por eso abajo se repiten en todas las clases: no es descuido, es obligatorio.
#
# Copie este bloque tal cual al inicio de cada Record:
#
#     id              = String()
#     time            = Long()
#     ingestion       = Long()
#     specversion     = String(default="v1")
#     type            = String()
#     datacontenttype = String(default="AVRO")
#     service_name    = String()
#     correlation_id  = String()
# ─────────────────────────────────────────────────────────────────────────────

CATEGORIAS = ["PLOMERIA", "ELECTRICIDAD", "CARPINTERIA", "PINTURA", "CERRAJERIA", "OTRO"]


class Dinero(Record):
    """Monto en la unidad minima (centavos) + moneda ISO-4217, inseparables."""
    monto = Long()
    moneda = String()


# ══════════════════════════════ FLUJO A — ADMINISTRATIVO ══════════════════════
# Configurar con quien trabajamos. Baja frecuencia. NO crea trabajos.

class RegistrarPartnerPayload(Record):
    partner_id = String(default="")
    nombre = String()
    tipo_partner = String()            # ASEGURADORA | BANCO | COMERCIO
    convenio_numero = String()
    vigencia_desde = Long()
    vigencia_hasta = Long(default=0)   # 0 = sin fecha de fin
    porcentaje_comision = Float(default=0.0)
    moneda_tarifa = String(default="COP")
    cobertura_contratada = Array(String())
    sla_minutos = Integer()
    monto_maximo_sin_aprobacion = Dinero()
    pasos_de_aprobacion = Array(String())
    red_homologada = Array(String())


class ComandoRegistrarPartner(Record):
    """cmd.partners → Motor reglas partner. Lo emite el area comercial vía el BFF."""
    id = String(); time = Long(); ingestion = Long()
    specversion = String(default="v1"); type = String(default="RegistrarPartner")
    datacontenttype = String(default="AVRO"); service_name = String(); correlation_id = String()
    data = RegistrarPartnerPayload()


class ActualizarReglaDePartnerPayload(Record):
    partner_id = String()
    cobertura_contratada = Array(String())
    sla_minutos = Integer()
    monto_maximo_sin_aprobacion = Dinero()
    pasos_de_aprobacion = Array(String())
    red_homologada = Array(String())


class ComandoActualizarReglaDePartner(Record):
    """cmd.partners → Motor reglas partner."""
    id = String(); time = Long(); ingestion = Long()
    specversion = String(default="v1"); type = String(default="ActualizarReglaDePartner")
    datacontenttype = String(default="AVRO"); service_name = String(); correlation_id = String()
    data = ActualizarReglaDePartnerPayload()


class ReglaDePartnerActualizadaPayload(Record):
    """CARGA DE ESTADO. Lleva la regla COMPLETA.

    Por que gorda: el consumidor debe poder operar con Motor reglas partner
    apagado. Si fuera delgada tendria que venir a preguntar, y el acoplamiento de
    disponibilidad volveria por la puerta de atras. Es la decision que sostiene el
    escenario de disponibilidad.
    """
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
    """evt.partners (COMPACTADO, clave=partner_id) ← Motor reglas partner.
    Consumen: Orquestacion de trabajos, Emparejamiento y asignacion."""
    id = String(); time = Long(); ingestion = Long()
    specversion = String(default="v1"); type = String(default="ReglaDePartnerActualizada")
    datacontenttype = String(default="AVRO"); service_name = String(); correlation_id = String()
    data = ReglaDePartnerActualizadaPayload()


class AcreditarProveedorPayload(Record):
    proveedor_id = String(default="")
    nombre = String()
    categorias = Array(String())
    ciudades = Array(String())
    vigente_hasta = Long(default=0)


class ComandoAcreditarProveedor(Record):
    """cmd.proveedores → Acreditacion y Habilitacion."""
    id = String(); time = Long(); ingestion = Long()
    specversion = String(default="v1"); type = String(default="AcreditarProveedor")
    datacontenttype = String(default="AVRO"); service_name = String(); correlation_id = String()
    data = AcreditarProveedorPayload()


class SuspenderProveedorPayload(Record):
    proveedor_id = String()
    motivo = String()


class ComandoSuspenderProveedor(Record):
    """cmd.proveedores → Acreditacion. Es el disparador de la demo de compensacion:
    se suspende un proveedor y se observa que las asignaciones a ese proveedor se
    revierten."""
    id = String(); time = Long(); ingestion = Long()
    specversion = String(default="v1"); type = String(default="SuspenderProveedor")
    datacontenttype = String(default="AVRO"); service_name = String(); correlation_id = String()
    data = SuspenderProveedorPayload()


class EstadoDeHabilitacionCambiadoPayload(Record):
    """CARGA DE ESTADO. Un solo tipo con campo `estado`, no dos tipos separados:
    el topico esta compactado y la compactacion conserva el ultimo mensaje por
    clave sin mirar el tipo, asi que dos tipos se pisarian entre si."""
    proveedor_id = String()
    nombre = String()
    estado = String()                 # HABILITADO | SUSPENDIDO | INHABILITADO
    categorias = Array(String())
    ciudades = Array(String())
    motivo = String(default="")
    vigente_hasta = Long(default=0)


class EventoEstadoDeHabilitacionCambiado(Record):
    """evt.proveedores (COMPACTADO, clave=proveedor_id) ← Acreditacion y Habilitacion.
    Consume: Emparejamiento y asignacion."""
    id = String(); time = Long(); ingestion = Long()
    specversion = String(default="v1"); type = String(default="EstadoDeHabilitacionCambiado")
    datacontenttype = String(default="AVRO"); service_name = String(); correlation_id = String()
    data = EstadoDeHabilitacionCambiadoPayload()


# ══════════════════════════════ FLUJO B — OPERATIVO ═══════════════════════════
# El ciclo de vida de un trabajo. Alto volumen: 12.000/dia, picos de 4x.

class CrearTrabajoPayload(Record):
    partner_id = String()             # referencia POR IDENTIDAD, nunca el objeto Partner
    mercado_id = String()
    categoria = String()
    urgencia = String()               # PROGRAMADA | ALTA | EMERGENCIA
    ciudad = String()
    descripcion = String()
    monto_estimado = Long(default=0)
    moneda = String(default="COP")


class ComandoCrearTrabajo(Record):
    """cmd.trabajos → Orquestacion de trabajos. Lo emite el ACL de un partner o el canal."""
    id = String(); time = Long(); ingestion = Long()
    specversion = String(default="v1"); type = String(default="CrearTrabajo")
    datacontenttype = String(default="AVRO"); service_name = String(); correlation_id = String()
    data = CrearTrabajoPayload()


class TrabajoCreadoPayload(Record):
    """EVENTO DE INTEGRACION DELGADO.

    `sla_minutos` viene de la regla del partner y queda CONGELADO en el trabajo:
    cambiar la regla manana no altera los trabajos ya creados. Esa es la semantica
    correcta de negocio y la razon por la que este campo se copia en vez de
    consultarse despues.
    """
    trabajo_id = String()
    partner_id = String()
    mercado_id = String()
    categoria = String()
    urgencia = String()
    ciudad = String()
    sla_minutos = Integer()
    requiere_aprobacion = Boolean(default=False)


class EventoTrabajoCreado(Record):
    """evt.trabajos (clave=trabajo_id) ← Orquestacion. Consume: Emparejamiento."""
    id = String(); time = Long(); ingestion = Long()
    specversion = String(default="v1"); type = String(default="TrabajoCreado")
    datacontenttype = String(default="AVRO"); service_name = String(); correlation_id = String()
    data = TrabajoCreadoPayload()


class TrabajoRechazadoPayload(Record):
    """LA EVIDENCIA OBSERVABLE DE QUE LA REGLA DEL PARTNER SE APLICO.

    Sin este evento, el escenario de modificabilidad no se puede demostrar: un
    trabajo de CARPINTERIA de un partner que solo contrato PLOMERIA tiene que
    rechazarse, y ese rechazo lo decide un DATO de la proyeccion, no un condicional.
    """
    trabajo_id = String()
    partner_id = String()
    categoria = String()
    motivo = String()                 # FUERA_DE_COBERTURA | CONVENIO_NO_VIGENTE | PARTNER_INACTIVO
    detalle = String(default="")


class EventoTrabajoRechazado(Record):
    """evt.trabajos (clave=trabajo_id) ← Orquestacion."""
    id = String(); time = Long(); ingestion = Long()
    specversion = String(default="v1"); type = String(default="TrabajoRechazado")
    datacontenttype = String(default="AVRO"); service_name = String(); correlation_id = String()
    data = TrabajoRechazadoPayload()


class AsignarProveedorPayload(Record):
    trabajo_id = String()
    motivo = String()                 # TIMEOUT_ASIGNACION | PROVEEDOR_RECHAZO | PROVEEDOR_INHABILITADO
    excluir_proveedores = Array(String())
    intento = Integer(default=1)


class ComandoAsignarProveedor(Record):
    """cmd.emparejamiento ← Orquestacion → Emparejamiento.

    Es el UNICO punto ORQUESTADO del sistema. El camino feliz es coreografiado:
    nadie le ordena a Emparejamiento que asigne, reacciona a TrabajoCreado. Este
    comando aparece solo en la excepcion, cuando hay que reasignar, porque ahi si
    hay alguien que decide y que lleva la cuenta de los intentos.
    """
    id = String(); time = Long(); ingestion = Long()
    specversion = String(default="v1"); type = String(default="AsignarProveedor")
    datacontenttype = String(default="AVRO"); service_name = String(); correlation_id = String()
    data = AsignarProveedorPayload()


class TrabajoAsignadoPayload(Record):
    trabajo_id = String()
    asignacion_id = String()
    proveedor_id = String()
    partner_id = String()
    sla_vence_en = Long()
    origen_habilitacion = String(default="PROYECCION_LOCAL")


class EventoTrabajoAsignado(Record):
    """evt.trabajos (clave=trabajo_id) ← Emparejamiento.
    Consumen: Orquestacion (para cerrar el ciclo) y Acreditacion (para VERIFICAR)."""
    id = String(); time = Long(); ingestion = Long()
    specversion = String(default="v1"); type = String(default="TrabajoAsignado")
    datacontenttype = String(default="AVRO"); service_name = String(); correlation_id = String()
    data = TrabajoAsignadoPayload()


class AsignacionRechazadaPorHabilitacionPayload(Record):
    """LA COMPENSACION.

    Reemplaza a la consulta sincrona de habilitacion, que el enunciado prohibe.
    Emparejamiento asigna de forma OPTIMISTA leyendo su proyeccion; Acreditacion,
    unico dueno del dato autoritativo, verifica y revierte si hace falta.

    Consecuencia declarada: el invariante de habilitacion deja de ser de
    consistencia inmediata y pasa a ser consistencia eventual con compensacion. Es
    decir, deja de ser una transaccion y se convierte en una transaccion larga —
    exactamente el material de la saga de la entrega 5.
    """
    trabajo_id = String()
    asignacion_id = String()
    proveedor_id = String()
    estado_real = String()
    motivo = String()
    verificado_en = Long()


class EventoAsignacionRechazadaPorHabilitacion(Record):
    """evt.asignaciones (clave=trabajo_id) ← Acreditacion.
    Consumen: Orquestacion y Emparejamiento."""
    id = String(); time = Long(); ingestion = Long()
    specversion = String(default="v1")
    type = String(default="AsignacionRechazadaPorHabilitacion")
    datacontenttype = String(default="AVRO"); service_name = String(); correlation_id = String()
    data = AsignacionRechazadaPorHabilitacionPayload()


class AsignacionConfirmadaPorHabilitacionPayload(Record):
    """CIERRE FELIZ DE LA SAGA.

    Simetrico al rechazo: Acreditacion es el unico dueno del dato autoritativo
    de habilitacion. Sin este evento la transaccion larga quedaria EN_CURSO
    para siempre, esperando un silencio que ningun broker reporta.
    """
    trabajo_id = String()
    asignacion_id = String()
    proveedor_id = String()
    estado_real = String()
    verificado_en = Long()


class EventoAsignacionConfirmadaPorHabilitacion(Record):
    """evt.asignaciones (clave=trabajo_id) ← Acreditacion.
    Consumen: Orquestacion (cierra el saga log) y Emparejamiento (CONFIRMADO)."""
    id = String(); time = Long(); ingestion = Long()
    specversion = String(default="v1")
    type = String(default="AsignacionConfirmadaPorHabilitacion")
    datacontenttype = String(default="AVRO"); service_name = String(); correlation_id = String()
    data = AsignacionConfirmadaPorHabilitacionPayload()


# ─────────────────────────────────────────────────────────────────────────────
CATALOGO = {
    # flujo A — administrativo
    "cmd.partners/RegistrarPartner.avsc":               ComandoRegistrarPartner,
    "cmd.partners/ActualizarReglaDePartner.avsc":       ComandoActualizarReglaDePartner,
    "evt.partners/ReglaDePartnerActualizada.avsc":      EventoReglaDePartnerActualizada,
    "cmd.proveedores/AcreditarProveedor.avsc":          ComandoAcreditarProveedor,
    "cmd.proveedores/SuspenderProveedor.avsc":          ComandoSuspenderProveedor,
    "evt.proveedores/EstadoDeHabilitacionCambiado.avsc": EventoEstadoDeHabilitacionCambiado,
    # flujo B — operativo
    "cmd.trabajos/CrearTrabajo.avsc":                   ComandoCrearTrabajo,
    "evt.trabajos/TrabajoCreado.avsc":                  EventoTrabajoCreado,
    "evt.trabajos/TrabajoRechazado.avsc":               EventoTrabajoRechazado,
    "cmd.emparejamiento/AsignarProveedor.avsc":         ComandoAsignarProveedor,
    "evt.trabajos/TrabajoAsignado.avsc":                EventoTrabajoAsignado,
    "evt.asignaciones/AsignacionRechazadaPorHabilitacion.avsc":
        EventoAsignacionRechazadaPorHabilitacion,
    "evt.asignaciones/AsignacionConfirmadaPorHabilitacion.avsc":
        EventoAsignacionConfirmadaPorHabilitacion,
}

if __name__ == "__main__":
    from pulsar.schema import AvroSchema

    base = os.path.dirname(os.path.abspath(__file__))
    for ruta, clase in CATALOGO.items():
        destino = os.path.join(base, "esquemas", ruta)
        os.makedirs(os.path.dirname(destino), exist_ok=True)
        esquema = json.loads(AvroSchema(clase).schema_info().schema())
        with open(destino, "w", encoding="utf-8") as f:
            json.dump(esquema, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"generado  esquemas/{ruta}")
    print(f"\n{len(CATALOGO)} contratos generados.")
