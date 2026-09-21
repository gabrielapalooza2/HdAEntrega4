"""Escrituras: traducen una peticion HTTP en un comando publicado en el bus.

El patron es el mismo en las cinco:

  1. Registrar la operacion  -> nace el correlation_id
  2. Traducir el modelo de la API al payload del contrato
  3. Publicar el comando con ese correlation_id en el sobre
  4. Devolver 202 con la URL donde consultar el desenlace

Ninguna espera una respuesta. Ninguna llama a otro servicio.

NO HAY ENDPOINT DE ASIGNACION, Y ES DELIBERADO
----------------------------------------------
El topico `cmd.emparejamiento` existe en el contrato pero NADIE lo consume:
Emparejamiento reacciona a `TrabajoCreado` en `evt.trabajos`, y tiene una prueba
(`test_sin_asignar_proveedor.py`) que prohibe que esa cadena aparezca en su
codigo. Un `POST /trabajos/{id}/asignacion` publicaria en el vacio y devolveria
202 sin que pasara nada: peor que no existir. La asignacion la dispara la saga
al crear el trabajo.
"""

import uuid

from fastapi import APIRouter, status

from .. import config
from ..esquemas import api
from ..infraestructura.operaciones import registro
from ..infraestructura.publicador import publicador

router = APIRouter(tags=["Escrituras"])


def _aceptar(tipo: str, topico: str) -> api.OperacionAceptada:
    op = registro.registrar(tipo, topico)
    return api.OperacionAceptada(
        correlation_id=op.correlation_id,
        tipo=tipo,
        topico=topico,
        consultar_en=f"/operaciones/{op.correlation_id}",
    )


def _dinero(d: api.DineroEntrada | None) -> dict:
    if d is None:
        return {"monto": 0, "moneda": "COP"}
    return {"monto": d.a_centavos(), "moneda": d.moneda}


# ── Flujo A: administrativo ──────────────────────────────────────────────────

@router.post("/partners", status_code=status.HTTP_202_ACCEPTED,
             response_model=api.OperacionAceptada,
             summary="Registrar un partner con su convenio y su regla")
def registrar_partner(entrada: api.RegistrarPartnerEntrada):
    """Acto del area comercial. NO crea ningun trabajo.

    El `partner_id` lo genera el BFF y no el servicio, para poder devolverselo al
    cliente de inmediato sin esperar a que el comando se procese.
    """
    partner_id = str(uuid.uuid4())
    aceptada = _aceptar("RegistrarPartner", config.CMD_PARTNERS)
    publicador.publicar(config.CMD_PARTNERS, "RegistrarPartner", {
        "partner_id": partner_id,
        "nombre": entrada.nombre,
        "tipo_partner": entrada.tipo_partner,
        "convenio_numero": entrada.convenio_numero,
        "vigencia_desde": api.a_millis(entrada.vigencia_desde),
        "vigencia_hasta": api.a_millis(entrada.vigencia_hasta),
        "porcentaje_comision": entrada.porcentaje_comision,
        "moneda_tarifa": entrada.moneda_tarifa,
        "cobertura_contratada": entrada.regla.cobertura_contratada,
        "sla_minutos": entrada.regla.sla_minutos,
        "monto_maximo_sin_aprobacion": _dinero(entrada.regla.monto_maximo_sin_aprobacion),
        "pasos_de_aprobacion": entrada.regla.pasos_de_aprobacion,
        "red_homologada": entrada.regla.red_homologada,
    }, aceptada.correlation_id, clave_particion=partner_id)
    aceptada.recurso_id = partner_id
    return aceptada


@router.put("/partners/{partner_id}/regla", status_code=status.HTTP_202_ACCEPTED,
            response_model=api.OperacionAceptada,
            summary="Cambiar la regla de operacion de un partner")
def actualizar_regla(partner_id: str, entrada: api.ActualizarReglaEntrada):
    """Sube la version de la regla. Ningun componente se redespliega."""
    aceptada = _aceptar("ActualizarReglaDePartner", config.CMD_PARTNERS)
    publicador.publicar(config.CMD_PARTNERS, "ActualizarReglaDePartner", {
        "partner_id": partner_id,
        "cobertura_contratada": entrada.cobertura_contratada,
        "sla_minutos": entrada.sla_minutos,
        "monto_maximo_sin_aprobacion": _dinero(entrada.monto_maximo_sin_aprobacion),
        "pasos_de_aprobacion": entrada.pasos_de_aprobacion,
        "red_homologada": entrada.red_homologada,
    }, aceptada.correlation_id, clave_particion=partner_id)
    aceptada.recurso_id = partner_id
    return aceptada


@router.post("/proveedores", status_code=status.HTTP_202_ACCEPTED,
             response_model=api.OperacionAceptada,
             summary="Acreditar un proveedor")
def acreditar_proveedor(entrada: api.AcreditarProveedorEntrada):
    proveedor_id = str(uuid.uuid4())
    aceptada = _aceptar("AcreditarProveedor", config.CMD_PROVEEDORES)
    publicador.publicar(config.CMD_PROVEEDORES, "AcreditarProveedor", {
        "proveedor_id": proveedor_id,
        "nombre": entrada.nombre,
        "categorias": entrada.categorias,
        "ciudades": entrada.ciudades,
        "vigente_hasta": api.a_millis(entrada.vigente_hasta),
    }, aceptada.correlation_id, clave_particion=proveedor_id)
    aceptada.recurso_id = proveedor_id
    return aceptada


@router.post("/proveedores/{proveedor_id}/suspension",
             status_code=status.HTTP_202_ACCEPTED,
             response_model=api.OperacionAceptada,
             summary="Suspender un proveedor (dispara la compensacion de la saga)")
def suspender_proveedor(proveedor_id: str, entrada: api.SuspenderProveedorEntrada):
    """Este endpoint es el que hace visible la compensacion.

    Suspender un proveedor cambia el dato autoritativo en Acreditacion, que
    publica `EstadoDeHabilitacionCambiado`. Cuando llegue la siguiente asignacion
    a ese proveedor, Acreditacion la rechaza con
    `AsignacionRechazadaPorHabilitacion` y la saga compensa. Es el camino infeliz,
    y se dispara desde aqui.
    """
    aceptada = _aceptar("SuspenderProveedor", config.CMD_PROVEEDORES)
    publicador.publicar(config.CMD_PROVEEDORES, "SuspenderProveedor", {
        "proveedor_id": proveedor_id,
        "motivo": entrada.motivo,
    }, aceptada.correlation_id, clave_particion=proveedor_id)
    aceptada.recurso_id = proveedor_id
    return aceptada


# ── Flujo B: operativo ───────────────────────────────────────────────────────

@router.post("/trabajos", status_code=status.HTTP_202_ACCEPTED,
             response_model=api.OperacionAceptada,
             summary="Crear un trabajo para un partner (dispara la saga)")
def crear_trabajo(entrada: api.CrearTrabajoEntrada):
    """El caso de uso central, y el unico disparador de la saga.

    Orquestacion lee su proyeccion local de la regla del partner y publica
    `TrabajoCreado` o `TrabajoRechazado`. A partir de ahi la coreografia sigue
    sola: Emparejamiento asigna, Motor reglas verifica y Acreditacion confirma o
    compensa. El BFF no dirige ninguno de esos pasos.
    """
    aceptada = _aceptar("CrearTrabajo", config.CMD_TRABAJOS)
    monto = entrada.monto_estimado
    publicador.publicar(config.CMD_TRABAJOS, "CrearTrabajo", {
        "partner_id": entrada.partner_id,
        "mercado_id": entrada.mercado_id,
        "categoria": entrada.categoria,
        "urgencia": entrada.urgencia,
        "ciudad": entrada.ciudad,
        "descripcion": entrada.descripcion,
        "monto_estimado": monto.a_centavos() if monto else 0,
        "moneda": monto.moneda if monto else "COP",
    }, aceptada.correlation_id, clave_particion=entrada.partner_id)
    return aceptada
