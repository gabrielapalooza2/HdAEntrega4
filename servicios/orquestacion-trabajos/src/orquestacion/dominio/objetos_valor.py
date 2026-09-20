"""Objetos valor del agregado Trabajo.

CONTINUIDAD CON LA ENTREGA ANTERIOR (vista de informacion HDA-004)
------------------------------------------------------------------
Se conservan los nombres del modelo tactico ya sustentado -Urgencia,
CategoriaDeServicio, AcuerdoDeServicio- y se recorta lo que el flujo dirigido
por eventos de esta entrega no ejercita (Diagnostico, Novedad, Ejecucion,
VentanaDeAtencion, Canal). Queda justificado en DECISIONES.md.

Dos evoluciones respecto de HDA-004 que hay que poder defender:

1. EstadoSolicitud tenia cinco estados de EJECUCION (REGISTRADO, ASIGNADO,
   EN_EJECUCION, COMPLETADO, CANCELADO). Esta entrega modela el ciclo de
   RESPUESTA, que es mas corto y es el que la coreografia entre microservicios
   realmente recorre. Correspondencia:

       REGISTRADO  -> CREADO
       ASIGNADO    -> ASIGNADO
       CANCELADO   -> RECHAZADO (cuando la regla del partner no cubre)
       (nuevo)     -> ESCALADO_MANUAL

2. El SLA ya NO sale de `Urgencia.horas_sla()`.

   En HDA-004 el SLA era una politica CABLEADA en el codigo: un diccionario
   {BAJA: 72, ALTA: 8, ...}. Aqui sale de la regla del partner, que llega como
   DATO por evt.partners.

   Ese cambio es justamente lo que hace posible el escenario de
   modificabilidad: cambiarle el SLA a una aseguradora es publicar un evento,
   no editar y redesplegar codigo. Y es lo que permite cumplir la regla dura
   "cero condicionales por partner".
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum


class EstadoTrabajo(str, Enum):
    """Ciclo de vida de RESPUESTA del trabajo.

        CREADO ──> ASIGNADO           (SLA de respuesta se detiene)
           ^            │
           └─compensacion (ProveedorDescartado)
                        │
                        └────> ESCALADO_MANUAL  (3 intentos, o SLA vencido)

        RECHAZADO                     (la regla del partner no cubre)

    ASIGNADO es terminal para el barrido de SLA solo mientras no haya
    compensacion. Si Acreditacion revierte la asignacion, el trabajo vuelve
    a CREADO y el reloj sigue: el SLA no se cumplio de verdad.
    """
    CREADO = "CREADO"
    ASIGNADO = "ASIGNADO"
    RECHAZADO = "RECHAZADO"
    ESCALADO_MANUAL = "ESCALADO_MANUAL"

    def es_terminal(self) -> bool:
        """ASIGNADO es terminal porque DETIENE EL RELOJ DEL SLA.

        El SLA es de RESPUESTA, no de ejecucion: se cumple cuando hay un tecnico
        asignado, no cuando el tecnico termina. Lo que pase despues (ejecucion,
        diagnostico, novedades) es el ciclo de HDA-004 y queda fuera del alcance
        de esta entrega.
        """
        return self in (EstadoTrabajo.ASIGNADO, EstadoTrabajo.RECHAZADO,
                        EstadoTrabajo.ESCALADO_MANUAL)


class Urgencia(str, Enum):
    """Igual que en HDA-004, pero SIN horas_sla().

    El metodo se elimino a proposito: era una tabla de SLA cableada en el
    codigo, y en esta arquitectura el SLA es un dato del partner. Dejarlo seria
    tener dos fuentes de verdad para el mismo numero.
    """
    BAJA = "BAJA"
    MEDIA = "MEDIA"
    ALTA = "ALTA"
    SINIESTRO = "SINIESTRO"

    @classmethod
    def de_texto(cls, valor: str | None) -> "Urgencia":
        try:
            return cls((valor or "MEDIA").upper())
        except ValueError:
            # Una urgencia desconocida NO puede tumbar la creacion de un
            # trabajo: viene de un sistema ajeno y no decide nada en este flujo.
            return cls.MEDIA


@dataclass(frozen=True)
class CategoriaDeServicio:
    """Categoria del servicio pedido.

    DIFERENCIA CON HDA-004: alla habia un CATALOGO cerrado de seis categorias y
    construir una fuera de la lista lanzaba ValueError.

    Aqui no hay catalogo. Que categorias existen lo dice la regla del partner
    (`categorias_cubiertas`), que llega por evt.partners. Mantener una lista
    constante en el codigo seria una segunda fuente de verdad que se
    desincroniza el dia que el grupo agregue una categoria, y ademas volveria a
    meter politica de negocio en el codigo.
    """
    codigo: str

    def __post_init__(self):
        if not (self.codigo or "").strip():
            raise ValueError("La categoria de servicio no puede estar vacia")

    @classmethod
    def de_codigo(cls, codigo: str) -> "CategoriaDeServicio":
        return cls((codigo or "").strip().upper())

    def __str__(self) -> str:
        return self.codigo


@dataclass(frozen=True)
class AcuerdoDeServicio:
    """SLA comprometido con el partner. CONGELADO al crear el trabajo.

    HDA-004 ya declaraba la intencion: "se calcula en el momento de registrar el
    trabajo y queda congelado: cambiar la politica no debe alterar acuerdos
    vigentes".

    Lo que agrega esta entrega es que el congelamiento pasa de ser una INTENCION
    a ser VERIFICABLE: este objeto se serializa dentro del payload de
    TrabajoCreado, en un event store append-only sobre el que nunca se hace
    UPDATE ni DELETE. No es que no queramos cambiarlo: es que no se puede.

    `regla_version` viaja con el acuerdo para poder decir DE QUE VERSION de la
    regla salio, que es la evidencia que se muestra al sustentar.
    """
    minutos_respuesta: int
    regla_version: int
    vence_en: datetime

    def __post_init__(self):
        if self.minutos_respuesta <= 0:
            raise ValueError("El acuerdo de servicio requiere minutos positivos")

    @classmethod
    def desde_regla(cls, minutos: int, regla_version: int,
                    creado_en: datetime) -> "AcuerdoDeServicio":
        """Congela el SLA vigente AHORA. Ver el comentario de la clase."""
        return cls(
            minutos_respuesta=minutos,
            regla_version=regla_version,
            vence_en=creado_en + timedelta(minutes=minutos),
        )

    def vencido(self, momento: datetime) -> bool:
        return momento >= self.vence_en


class MotivoRechazo(str, Enum):
    """Codigos estables de rechazo. Van en el cable para que una maquina pueda
    reaccionar; el texto libre va aparte, en `detalle`, para las personas."""
    PARTNER_DESCONOCIDO = "PARTNER_DESCONOCIDO"
    PARTNER_INACTIVO = "PARTNER_INACTIVO"
    CATEGORIA_NO_CUBIERTA = "CATEGORIA_NO_CUBIERTA"


class MotivoEscalamiento(str, Enum):
    INTENTOS_AGOTADOS = "INTENTOS_AGOTADOS"
    SLA_VENCIDO = "SLA_VENCIDO"
