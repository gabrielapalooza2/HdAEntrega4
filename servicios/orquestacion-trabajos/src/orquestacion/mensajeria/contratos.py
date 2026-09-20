"""LA COSTURA. Capa anticorrupcion de Orquestacion de Trabajos.

╔══════════════════════════════════════════════════════════════════════════╗
║  Este modulo traduce entre DOS vocabularios:                             ║
║                                                                          ║
║    adentro   el lenguaje ubicuo de este servicio                        ║
║              (zona, regla_version, categorias_cubiertas,                ║
║               proveedores_excluidos, monto_max)                         ║
║                                                                          ║
║    afuera    el contrato Avro del grupo, en contratos/esquemas/         ║
║              (ciudad, version_regla, cobertura_contratada,              ║
║               excluir_proveedores, monto_maximo_sin_aprobacion)         ║
║                                                                          ║
║  Los nombres NO coinciden, y esa es exactamente la razon de que exista   ║
║  una capa anticorrupcion: el dominio no se deforma para parecerse al     ║
║  contrato ajeno, y el contrato ajeno puede cambiar sin tocar el dominio. ║
║                                                                          ║
║  REGLA DURA: ningun otro modulo conoce los nombres de afuera ni sabe en  ║
║  que topico va nada. Si en dominio/ o aplicacion/ aparece la cadena      ║
║  "cobertura_contratada", la capa se rompio.                             ║
╚══════════════════════════════════════════════════════════════════════════╝

Por que BytesSchema y no AvroSchema
-----------------------------------
evt.trabajos lleva TRES tipos (TrabajoCreado, TrabajoRechazado, TrabajoAsignado)
y Pulsar registra UN SOLO esquema por topico: ninguna politica de compatibilidad
admite los tres a la vez. Asi que se codifica Avro a mano, se publica como bytes
crudos y el consumidor discrimina por el campo `type` del sobre. Es lo mismo que
hace Emparejamiento.

Se usa fastavro y no pulsar.schema a proposito: asi este modulo -y los tests que
lo prueban- no dependen de tener el cliente nativo de Pulsar instalado. La
traduccion es logica pura y se prueba sin broker.
"""
import io
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from functools import lru_cache
from typing import ClassVar

from fastavro import parse_schema, schemaless_reader, schemaless_writer

# Unica dependencia de este modulo fuera de la stdlib y fastavro. config no
# importa nada del servicio, asi que la costura sigue siendo logica pura.
from orquestacion.config import CONTRATOS_DIR, SERVICE_NAME

# ═══════════════════════════════════════════════════════════ constantes ════

SPECVERSION = "v1"
DATACONTENTTYPE = "AVRO"

# Namespace del GRUPO. Es hda/poc, no hda/core: es el que ya usan Emparejamiento
# y el script de topicos de la raiz. Dos namespaces distintos no fallan con
# error, que es lo peligroso: cada servicio publica feliz en el suyo y el otro
# nunca recibe nada.
NAMESPACE = "persistent://hda/poc"

TOPICO_CMD_TRABAJOS       = f"{NAMESPACE}/cmd.trabajos"
TOPICO_EVT_PARTNERS       = f"{NAMESPACE}/evt.partners"
TOPICO_EVT_TRABAJOS       = f"{NAMESPACE}/evt.trabajos"
TOPICO_EVT_ASIGNACIONES   = f"{NAMESPACE}/evt.asignaciones"
TOPICO_CMD_EMPAREJAMIENTO = f"{NAMESPACE}/cmd.emparejamiento"


def ahora_ms() -> int:
    """El contrato del grupo expresa los tiempos como long de MILISEGUNDOS
    desde epoch, no como ISO-8601. Traducir eso es trabajo de esta capa."""
    return int(time.time() * 1000)


def a_ms(momento: datetime | None) -> int | None:
    return None if momento is None else int(momento.timestamp() * 1000)


def de_ms(milis: int | None) -> datetime | None:
    return None if milis is None else datetime.fromtimestamp(milis / 1000, timezone.utc)


# ═══════════════════════════════════════════════════════ esquemas Avro ═════

# tipo de mensaje -> carpeta de esquemas (que coincide con el topico corto).
# Los OCHO tipos que este servicio toca tienen .avsc publicado, incluido
# CrearTrabajo. La regla del equipo es: hay .avsc -> Avro binario; no hay ->
# JSON provisional. Hoy no queda ninguno en el segundo caso.
CARPETA_DE_TIPO = {
    "CrearTrabajo":                       "cmd.trabajos",
    "ReglaDePartnerActualizada":          "evt.partners",
    "TrabajoCreado":                      "evt.trabajos",
    "TrabajoRechazado":                   "evt.trabajos",
    "TrabajoAsignado":                    "evt.trabajos",
    "AsignacionRechazadaPorHabilitacion": "evt.asignaciones",
    "AsignacionConfirmadaPorHabilitacion": "evt.asignaciones",
    "AsignarProveedor":                   "cmd.emparejamiento",
}


@lru_cache(maxsize=None)
def cargar_avsc(tipo: str) -> dict:
    carpeta = CARPETA_DE_TIPO.get(tipo)
    if carpeta is None:
        raise KeyError(f"Tipo de mensaje desconocido para esta costura: {tipo}")
    ruta = CONTRATOS_DIR / "esquemas" / carpeta / f"{tipo}.avsc"
    if not ruta.is_file():
        raise FileNotFoundError(
            f"Contrato Avro no encontrado: {ruta}. Revisa CONTRATOS_DIR."
        )
    return parse_schema(json.loads(ruta.read_text(encoding="utf-8")))


# El sobre es un PREFIJO POSICIONAL comun a los ocho esquemas: los mismos ocho
# campos, en el mismo orden, antes de `data`. Avro binario es posicional y no
# lleva nombres de campo en el cable, asi que se puede leer el sobre SIN SABER
# TODAVIA que tipo viene, parar ahi, mirar `type` y recien entonces decodificar
# el mensaje completo con el esquema correcto.
#
# Esto es lo que hace viable publicar con BytesSchema: el discriminador viaja
# dentro del propio mensaje, en una posicion conocida.
_ESQUEMA_SOBRE = parse_schema({
    "type": "record",
    "name": "SobreComun",
    "fields": [
        {"name": "id",              "type": ["null", "string"]},
        {"name": "time",            "type": ["null", "long"]},
        {"name": "ingestion",       "type": ["null", "long"]},
        {"name": "specversion",     "type": ["null", "string"]},
        {"name": "type",            "type": ["null", "string"]},
        {"name": "datacontenttype", "type": ["null", "string"]},
        {"name": "service_name",    "type": ["null", "string"]},
        {"name": "correlation_id",  "type": ["null", "string"]},
    ],
})


# ═══════════════════════════════════════════════════════════ el sobre ══════

@dataclass
class Sobre:
    """Sobre CloudEvents del grupo.

    NO HAY causation_id. Con correlation_id se sabe a que historia pertenece un
    mensaje, pero no quien es su padre inmediato, asi que el arbol causal se
    aplana a una lista. Se conserva de todos modos DENTRO del servicio, en
    eventos_trabajo, donde nadie mas manda.

    `time` es cuando ocurrio el hecho; `ingestion` es cuando el mensaje entra al
    bus. Los emitimos iguales porque publicamos en el acto.
    """
    type: str
    data: dict
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    time: int = field(default_factory=ahora_ms)
    ingestion: int = field(default_factory=ahora_ms)
    specversion: str = SPECVERSION
    datacontenttype: str = DATACONTENTTYPE
    service_name: str = SERVICE_NAME
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def a_dict(self) -> dict:
        return {
            "id": self.id,
            "time": self.time,
            "ingestion": self.ingestion,
            "specversion": self.specversion,
            "type": self.type,
            "datacontenttype": self.datacontenttype,
            "service_name": self.service_name,
            "correlation_id": self.correlation_id,
            "data": self.data,
        }

    @classmethod
    def desde_dict(cls, d: dict) -> "Sobre":
        return cls(
            type=d.get("type") or "",
            data=d.get("data") or {},
            id=d.get("id") or "",
            time=d.get("time") or 0,
            ingestion=d.get("ingestion") or 0,
            specversion=d.get("specversion") or SPECVERSION,
            datacontenttype=d.get("datacontenttype") or DATACONTENTTYPE,
            service_name=d.get("service_name") or "desconocido",
            correlation_id=d.get("correlation_id") or "",
        )

    def a_bytes(self) -> bytes:
        buf = io.BytesIO()
        schemaless_writer(buf, cargar_avsc(self.type), self.a_dict())
        return buf.getvalue()

    def contenido(self):
        """Mensaje tipado en vocabulario PROPIO, o None si es un tipo que este
        servicio no modela.

        Devolver None no es un error: los topicos son por agregado, no por tipo
        de mensaje, asi que recibir tipos ajenos por el mismo topico es lo
        normal y esperado.
        """
        clase = REGISTRO.get(self.type)
        return clase.desde_datos(self.data) if clase else None

    def es_propio(self) -> bool:
        """True si lo emitio este mismo servicio. Ver NOTA DEL CICLO abajo."""
        return self.service_name == SERVICE_NAME


def decodificar(crudo: bytes) -> Sobre | None:
    """Bytes del cable -> Sobre. Devuelve None si no se reconoce el tipo.

    Dos pasadas sobre los mismos bytes, que es barato porque son bytes en
    memoria:
      1. leer solo el prefijo del sobre para averiguar `type`
      2. decodificar entero con el esquema de ese tipo

    No hace falta que el llamador diga que tipos espera: el mensaje se
    autodescribe.
    """
    # ─── JSON legado ──────────────────────────────────────────────────────
    # Antes de que el grupo publicara el .avsc de cmd.trabajos, CrearTrabajo
    # viajaba en JSON, y el topico tiene retencion infinita: esos mensajes
    # siguen ahi y van a seguir llegandole a un consumidor que lea desde el
    # inicio. Se aceptan.
    #
    # Es la ley de Postel aplicada a proposito: LIBERAL al recibir, ESTRICTO al
    # emitir. Este servicio nunca emite JSON -a_bytes() siempre codifica Avro-,
    # pero no deja caer en silencio un comando real solo porque sea viejo.
    if crudo[:1] == b"{":
        try:
            datos = json.loads(crudo.decode("utf-8"))
            if isinstance(datos, dict) and datos.get("type") in CARPETA_DE_TIPO:
                return Sobre.desde_dict(datos)
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        return None

    try:
        cabecera = schemaless_reader(io.BytesIO(crudo), _ESQUEMA_SOBRE)
    except Exception:
        return None

    tipo = (cabecera or {}).get("type")
    if tipo not in CARPETA_DE_TIPO:
        # Tipo de otro equipo que no modelamos. Se ignora en silencio.
        return None

    try:
        completo = schemaless_reader(io.BytesIO(crudo), cargar_avsc(tipo))
    except Exception:
        return None
    return Sobre.desde_dict(completo)


# ══════════════════════════════════════════════════════════ los mensajes ═══
#
# Los dataclasses estan en VOCABULARIO PROPIO.
#   a_datos()    traduce hacia el contrato del grupo
#   desde_datos() traduce de vuelta
# Toda la traduccion vive aqui y en ningun otro lado.
#
# a_datos() enumera TODOS los campos del .avsc, incluidos los que este servicio
# no usa, poniendolos en None. No es ruido: Avro exige que el registro este
# completo al codificar, y dejar los ajenos explicitos documenta que sabemos
# que existen y que decidimos no usarlos.

@dataclass
class _Mensaje:
    TIPO: ClassVar[str] = ""
    TOPICO: ClassVar[str] = ""
    CAMPO_CLAVE: ClassVar[str] = "trabajo_id"

    def clave_particion(self) -> str:
        """La clave hace DOS cosas a la vez: fija la particion, lo que preserva
        el orden de los hechos de un mismo agregado; y es la clave de
        compactacion en los topicos compactados."""
        return str(getattr(self, self.CAMPO_CLAVE))


# ─────────────────────────────────────────────────────────────── entrantes ──

@dataclass
class CrearTrabajo(_Mensaje):
    """Comando de la aseguradora, en cmd.trabajos.

    ─── DE DONDE SALE EL trabajo_id ──────────────────────────────────────
    El contrato del grupo NO trae trabajo_id en el payload. La identidad del
    agregado la genera ESTE servicio, que es su dueno.

    Consecuencia directa: el comando NO es idempotente por su contenido, asi
    que la clave de idempotencia pasa a ser el `id` DEL SOBRE, contrastado
    contra la tabla mensajes_procesados. Reenviar el mismo sobre no crea un
    segundo trabajo; enviar dos sobres distintos con el mismo contenido si
    crea dos trabajos, y eso es correcto: son dos siniestros.
    ───────────────────────────────────────────────────────────────────────

    Traduccion: ciudad -> zona.

    mercado_id, urgencia, monto_estimado y moneda se reciben y se congelan en
    el event store aunque el dominio de hoy no decida con ellos, salvo
    monto_estimado, que se compara contra monto_max para marcar
    requiere_aprobacion. Guardar lo que no se usa todavia es barato en un event
    store y es lo que permite responder preguntas futuras sobre el pasado.
    """
    TIPO: ClassVar[str] = "CrearTrabajo"
    TOPICO: ClassVar[str] = TOPICO_CMD_TRABAJOS

    # Se particiona por partner_id porque el trabajo_id TODAVIA NO EXISTE
    # cuando este comando viaja: lo genera este servicio al recibirlo.
    #
    # Tradeoff: un partner muy activo concentra carga en una particion. La
    # alternativa -sin clave, reparto circular- distribuiria mejor, porque cada
    # CrearTrabajo crea un agregado independiente y entre ellos no hay orden que
    # preservar. Se elige partner_id igual para que el reparto sea DETERMINISTA
    # y las corridas del escenario de escalabilidad sean reproducibles.
    CAMPO_CLAVE: ClassVar[str] = "partner_id"

    partner_id: str = ""
    mercado_id: str = ""
    categoria: str = ""
    urgencia: str = ""
    zona: str = ""
    descripcion: str = ""
    monto_estimado: int | None = None
    moneda: str | None = None

    def a_datos(self) -> dict:
        return {
            "partner_id": self.partner_id,
            "mercado_id": self.mercado_id,
            "categoria": self.categoria,
            "urgencia": self.urgencia,
            "ciudad": self.zona,            # zona -> ciudad
            "descripcion": self.descripcion,
            "monto_estimado": self.monto_estimado,
            "moneda": self.moneda,
        }

    @classmethod
    def desde_datos(cls, d: dict) -> "CrearTrabajo":
        return cls(
            partner_id=d.get("partner_id") or "",
            mercado_id=d.get("mercado_id") or "",
            categoria=d.get("categoria") or "",
            urgencia=d.get("urgencia") or "",
            # `zona` es el nombre que usaba el JSON legado; `ciudad` es el del
            # contrato Avro. Se aceptan los dos al leer.
            zona=d.get("ciudad") or d.get("zona") or "",
            descripcion=d.get("descripcion") or "",
            monto_estimado=d.get("monto_estimado"),
            moneda=d.get("moneda"),
        )


@dataclass
class ReglaDePartnerActualizada(_Mensaje):
    """Evento del Motor de Reglas de Partner, en evt.partners.

    Alimenta la proyeccion local de reglas: TODA la variabilidad entre
    aseguradoras entra por aqui COMO DATO, nunca como condicional.

    Traduccion de nombres:
        regla_version         <- version_regla
        categorias_cubiertas  <- cobertura_contratada
        monto_max / moneda    <- monto_maximo_sin_aprobacion{monto, moneda}

    OJO con monto: el contrato lo declara `long`, no decimal. Se asume que viene
    en unidades enteras de la moneda (pesos, no centavos). Falta confirmarlo con
    el grupo; si fueran centavos, todo monto queda 100x.
    """
    TIPO: ClassVar[str] = "ReglaDePartnerActualizada"
    TOPICO: ClassVar[str] = TOPICO_EVT_PARTNERS
    CAMPO_CLAVE: ClassVar[str] = "partner_id"

    partner_id: str = ""
    regla_version: int = 0
    sla_minutos: int = 0
    categorias_cubiertas: list[str] = field(default_factory=list)
    monto_max: Decimal | None = None
    moneda: str | None = None
    activo: bool = True

    def a_datos(self) -> dict:
        return {
            "partner_id": self.partner_id,
            "convenio_id": None,
            "nombre": None,
            "tipo_partner": None,
            "activo": self.activo,
            "vigencia_desde": None,
            "vigencia_hasta": None,
            "version_regla": self.regla_version,
            "cobertura_contratada": list(self.categorias_cubiertas),
            "sla_minutos": self.sla_minutos,
            "monto_maximo_sin_aprobacion": (
                None if self.monto_max is None
                else {"monto": int(self.monto_max), "moneda": self.moneda}
            ),
            "pasos_de_aprobacion": [],
            "red_homologada": [],
            "porcentaje_comision": None,
            "moneda_tarifa": self.moneda,
        }

    @classmethod
    def desde_datos(cls, d: dict) -> "ReglaDePartnerActualizada":
        dinero = d.get("monto_maximo_sin_aprobacion") or {}
        monto = dinero.get("monto")
        return cls(
            partner_id=d.get("partner_id") or "",
            regla_version=d.get("version_regla") or 0,
            sla_minutos=d.get("sla_minutos") or 0,
            categorias_cubiertas=list(d.get("cobertura_contratada") or []),
            monto_max=None if monto is None else Decimal(monto),
            moneda=dinero.get("moneda") or d.get("moneda_tarifa"),
            activo=True if d.get("activo") is None else bool(d.get("activo")),
        )


@dataclass
class TrabajoAsignado(_Mensaje):
    """Evento de Emparejamiento y Asignacion, en evt.trabajos.

    ─── NOTA DEL CICLO ───────────────────────────────────────────────────
    Este servicio es el dueno del agregado Trabajo y publica en evt.trabajos.
    Emparejamiento tambien publica ahi, y NO existe ningun ProveedorAsignado en
    otro topico, asi que para enterarnos de una asignacion hay que CONSUMIR
    NUESTRO PROPIO TOPICO.

    Eso es un ciclo y no es como deberia estar modelado: el dueno de un agregado
    deberia ser el unico productor de su topico. Se acepta porque es lo que hay
    construido, y se MITIGA descartando todo sobre con service_name propio
    (Sobre.es_propio), para no reaccionar a nuestro propio eco.

    DEUDA REGISTRADA: pedir a Emparejamiento que publique tambien en
    evt.asignaciones y mover el consumidor alli.
    ───────────────────────────────────────────────────────────────────────

    Traduccion: sla_vence_en (long de ms) -> vence_en (datetime).
    """
    TIPO: ClassVar[str] = "TrabajoAsignado"
    TOPICO: ClassVar[str] = TOPICO_EVT_TRABAJOS

    trabajo_id: str = ""
    asignacion_id: str = ""
    proveedor_id: str = ""
    partner_id: str = ""
    vence_en: datetime | None = None
    origen_habilitacion: str = ""

    def a_datos(self) -> dict:
        return {
            "trabajo_id": self.trabajo_id,
            "asignacion_id": self.asignacion_id,
            "proveedor_id": self.proveedor_id,
            "partner_id": self.partner_id,
            "sla_vence_en": a_ms(self.vence_en),   # vence_en -> sla_vence_en
            "origen_habilitacion": self.origen_habilitacion,
        }

    @classmethod
    def desde_datos(cls, d: dict) -> "TrabajoAsignado":
        return cls(
            trabajo_id=d.get("trabajo_id") or "",
            asignacion_id=d.get("asignacion_id") or "",
            proveedor_id=d.get("proveedor_id") or "",
            partner_id=d.get("partner_id") or "",
            vence_en=de_ms(d.get("sla_vence_en")),
            origen_habilitacion=d.get("origen_habilitacion") or "",
        )


@dataclass
class AsignacionRechazadaPorHabilitacion(_Mensaje):
    """Evento de Acreditacion y Habilitacion, en evt.asignaciones.

    Es la COMPENSACION del sistema: Emparejamiento asigno de forma optimista y
    Acreditacion descubrio despues que el proveedor no estaba habilitado. No hay
    transaccion distribuida que deshaga eso; hay un mensaje que dice que salio
    mal y alguien que reacciona. Ese alguien es este servicio, y ese es el UNICO
    punto orquestado del sistema.
    """
    TIPO: ClassVar[str] = "AsignacionRechazadaPorHabilitacion"
    TOPICO: ClassVar[str] = TOPICO_EVT_ASIGNACIONES

    trabajo_id: str = ""
    asignacion_id: str = ""
    proveedor_id: str = ""
    estado_real: str = ""
    motivo: str = ""
    verificado_en: datetime | None = None

    def a_datos(self) -> dict:
        return {
            "trabajo_id": self.trabajo_id,
            "asignacion_id": self.asignacion_id,
            "proveedor_id": self.proveedor_id,
            "estado_real": self.estado_real,
            "motivo": self.motivo,
            "verificado_en": a_ms(self.verificado_en) or ahora_ms(),
        }

    @classmethod
    def desde_datos(cls, d: dict) -> "AsignacionRechazadaPorHabilitacion":
        return cls(
            trabajo_id=d.get("trabajo_id") or "",
            asignacion_id=d.get("asignacion_id") or "",
            proveedor_id=d.get("proveedor_id") or "",
            estado_real=d.get("estado_real") or "",
            motivo=d.get("motivo") or "",
            verificado_en=de_ms(d.get("verificado_en")),
        )


@dataclass
class AsignacionConfirmadaPorHabilitacion(_Mensaje):
    """Evento de Acreditacion, en evt.asignaciones.

    Cierra la transaccion larga: el dato autoritativo coincidio con la
    asignacion optimista. No muta el agregado Trabajo (ya esta ASIGNADO);
    solo cierra el saga log.
    """
    TIPO: ClassVar[str] = "AsignacionConfirmadaPorHabilitacion"
    TOPICO: ClassVar[str] = TOPICO_EVT_ASIGNACIONES

    trabajo_id: str = ""
    asignacion_id: str = ""
    proveedor_id: str = ""
    estado_real: str = ""
    verificado_en: datetime | None = None

    def a_datos(self) -> dict:
        return {
            "trabajo_id": self.trabajo_id,
            "asignacion_id": self.asignacion_id,
            "proveedor_id": self.proveedor_id,
            "estado_real": self.estado_real,
            "verificado_en": a_ms(self.verificado_en) or ahora_ms(),
        }

    @classmethod
    def desde_datos(cls, d: dict) -> "AsignacionConfirmadaPorHabilitacion":
        return cls(
            trabajo_id=d.get("trabajo_id") or "",
            asignacion_id=d.get("asignacion_id") or "",
            proveedor_id=d.get("proveedor_id") or "",
            estado_real=d.get("estado_real") or "",
            verificado_en=de_ms(d.get("verificado_en")),
        )


# ─────────────────────────────────────────────────────────────── salientes ──

@dataclass
class TrabajoCreado(_Mensaje):
    """Evento propio, a evt.trabajos.

    ─── QUE SE PIERDE EN EL CABLE ────────────────────────────────────────
    El contrato del grupo NO lleva regla_version, vence_en ni descripcion, y
    llama `ciudad` a lo que aqui es `zona`.

    regla_version y vence_en son la evidencia del CONGELAMIENTO DEL SLA, que es
    el escenario de modificabilidad del proyecto. Que no viajen no lo rompe: el
    congelamiento ocurre y se PRUEBA en el event store, en
    eventos_trabajo.payload, que es la fuente de verdad y es solo nuestra.

    El evento de integracion es una PROYECCION del hecho, recortada a lo que el
    contrato ajeno admite. Es la distincion entre evento de DOMINIO y evento de
    INTEGRACION, y es justo lo que una capa anticorrupcion hace.
    ───────────────────────────────────────────────────────────────────────
    """
    TIPO: ClassVar[str] = "TrabajoCreado"
    TOPICO: ClassVar[str] = TOPICO_EVT_TRABAJOS

    trabajo_id: str = ""
    partner_id: str = ""
    mercado_id: str = ""
    categoria: str = ""
    urgencia: str = ""
    zona: str = ""
    sla_minutos: int = 0
    requiere_aprobacion: bool = False

    def a_datos(self) -> dict:
        return {
            "trabajo_id": self.trabajo_id,
            "partner_id": self.partner_id,
            "mercado_id": self.mercado_id,
            "categoria": self.categoria,
            "urgencia": self.urgencia,
            "ciudad": self.zona,            # zona -> ciudad
            "sla_minutos": self.sla_minutos,
            "requiere_aprobacion": self.requiere_aprobacion,
        }

    @classmethod
    def desde_datos(cls, d: dict) -> "TrabajoCreado":
        return cls(
            trabajo_id=d.get("trabajo_id") or "",
            partner_id=d.get("partner_id") or "",
            mercado_id=d.get("mercado_id") or "",
            categoria=d.get("categoria") or "",
            urgencia=d.get("urgencia") or "",
            zona=d.get("ciudad") or "",
            sla_minutos=d.get("sla_minutos") or 0,
            requiere_aprobacion=bool(d.get("requiere_aprobacion")),
        )


@dataclass
class TrabajoRechazado(_Mensaje):
    """Evento propio, a evt.trabajos.

    El rechazo es un HECHO DE NEGOCIO publicado, no un error tecnico. Un trabajo
    que la regla del partner no cubre no es una excepcion: es una decision, y la
    aseguradora tiene derecho a enterarse y a saber por que. Por eso lleva
    motivo (codigo estable, para que una maquina reaccione) y detalle (texto,
    para que una persona entienda).
    """
    TIPO: ClassVar[str] = "TrabajoRechazado"
    TOPICO: ClassVar[str] = TOPICO_EVT_TRABAJOS

    trabajo_id: str = ""
    partner_id: str = ""
    categoria: str = ""
    motivo: str = ""
    detalle: str = ""

    def a_datos(self) -> dict:
        return {
            "trabajo_id": self.trabajo_id,
            "partner_id": self.partner_id,
            "categoria": self.categoria,
            "motivo": self.motivo,
            "detalle": self.detalle,
        }

    @classmethod
    def desde_datos(cls, d: dict) -> "TrabajoRechazado":
        return cls(
            trabajo_id=d.get("trabajo_id") or "",
            partner_id=d.get("partner_id") or "",
            categoria=d.get("categoria") or "",
            motivo=d.get("motivo") or "",
            detalle=d.get("detalle") or "",
        )


@dataclass
class AsignarProveedor(_Mensaje):
    """Comando propio hacia Emparejamiento, a cmd.emparejamiento.

    ─── SIN CONSUMIDOR HOY ───────────────────────────────────────────────
    Emparejamiento declara este topico como "no se consume (E5)". El .avsc
    existe, asi que no hay que inventar nada, pero nadie escucha todavia. Se
    publica igual: la reasignacion es el unico punto ORQUESTADO del sistema y es
    alcance propio de este servicio. Sin consumidor, la demo de punta a punta se
    corta aqui.
    ───────────────────────────────────────────────────────────────────────

    proveedores_excluidos viaja CON el comando porque Emparejamiento no puede
    leer nuestra base de datos. En una arquitectura de eventos el estado
    necesario para decidir va EN EL MENSAJE, no en una consulta al emisor.
    En el cable se llama `excluir_proveedores`.
    """
    TIPO: ClassVar[str] = "AsignarProveedor"
    TOPICO: ClassVar[str] = TOPICO_CMD_EMPAREJAMIENTO

    trabajo_id: str = ""
    motivo: str = ""
    proveedores_excluidos: list[str] = field(default_factory=list)
    intento: int = 1

    def a_datos(self) -> dict:
        return {
            "trabajo_id": self.trabajo_id,
            "motivo": self.motivo,
            # proveedores_excluidos -> excluir_proveedores
            "excluir_proveedores": list(self.proveedores_excluidos),
            "intento": self.intento,
        }

    @classmethod
    def desde_datos(cls, d: dict) -> "AsignarProveedor":
        return cls(
            trabajo_id=d.get("trabajo_id") or "",
            motivo=d.get("motivo") or "",
            proveedores_excluidos=list(d.get("excluir_proveedores") or []),
            intento=d.get("intento") or 1,
        )


# ═══════════════════════════════════════════════════════════ el registro ═══

MENSAJES_ENTRANTES = (
    CrearTrabajo,
    ReglaDePartnerActualizada,
    TrabajoAsignado,
    AsignacionRechazadaPorHabilitacion,
    AsignacionConfirmadaPorHabilitacion,
)

MENSAJES_SALIENTES = (
    TrabajoCreado,
    TrabajoRechazado,
    AsignarProveedor,
)

REGISTRO: dict[str, type] = {
    c.TIPO: c for c in (*MENSAJES_ENTRANTES, *MENSAJES_SALIENTES)
}


def empaquetar(mensaje: _Mensaje, *, correlation_id: str | None = None,
               service_name: str = SERVICE_NAME) -> Sobre:
    """Mete un mensaje de negocio en su sobre.

    correlation_id se PROPAGA desde el mensaje que origino la reaccion; solo se
    genera uno nuevo al iniciar una cadena. No hay causation_id: el contrato del
    grupo no lo lleva.
    """
    return Sobre(
        type=mensaje.TIPO,
        data=mensaje.a_datos(),
        correlation_id=correlation_id or str(uuid.uuid4()),
        service_name=service_name,
    )
