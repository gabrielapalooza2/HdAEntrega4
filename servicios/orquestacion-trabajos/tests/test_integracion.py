"""Fase 7: el camino completo contra PostgreSQL real.

Event store + proyeccion + outbox + idempotencia, todo dentro de una
transaccion. Se salta solo si no hay base disponible.
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from orquestacion.aplicacion import reglas as aplicacion_reglas
from orquestacion.aplicacion import trabajos as aplicacion
from orquestacion.dominio import eventos as ev
from orquestacion.dominio import trabajo as dom
from orquestacion.infraestructura.persistencia import eventos as almacen
from orquestacion.infraestructura.persistencia import outbox, trabajos
from orquestacion.mensajeria import contratos as c


def sembrar_regla(base, partner_id="SEGUROS_ANDES", version=1, sla=120,
                  categorias=("PLOMERIA", "ELECTRICIDAD"), activo=True):
    aplicacion_reglas.manejar_regla_actualizada(c.empaquetar(
        c.ReglaDePartnerActualizada(
            partner_id=partner_id, regla_version=version, sla_minutos=sla,
            categorias_cubiertas=list(categorias), activo=activo,
            monto_max=Decimal("500000"), moneda="COP"),
        service_name="motor-reglas-partner"))


def sobre_crear(partner_id="SEGUROS_ANDES", categoria="PLOMERIA", **extra):
    return c.empaquetar(
        c.CrearTrabajo(partner_id=partner_id, categoria=categoria, zona="BOGOTA",
                       mercado_id="BOG", urgencia="ALTA", descripcion="Fuga",
                       **extra),
        service_name="portal-aseguradora")


def id_de(sobre):
    """El trabajo_id que el manejador va a derivar de este sobre."""
    return str(uuid.uuid5(aplicacion._NS_TRABAJOS, sobre.id))


def filas(base, sql, args=()):
    with base.pool().connection() as con, con.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchall()


# ═════════════════════════════════════════════════ el camino de escritura ══

def test_crear_trabajo_escribe_evento_proyeccion_y_outbox(limpia):
    """Los tres efectos, en UNA transaccion."""
    sembrar_regla(limpia)
    sobre = sobre_crear()
    aplicacion.manejar_crear_trabajo(sobre)
    tid = id_de(sobre)

    # 1. event store: la fuente de verdad
    eventos = filas(limpia, "SELECT secuencia, tipo, payload FROM eventos_trabajo "
                            "WHERE trabajo_id = %s ORDER BY secuencia", (tid,))
    assert len(eventos) == 1
    assert eventos[0][1] == "TrabajoCreado"

    # 2. proyeccion: el lado de lectura
    vista = filas(limpia, "SELECT estado, sla_minutos, secuencia FROM "
                          "proyeccion_trabajo WHERE trabajo_id = %s", (tid,))
    assert vista == [("CREADO", 120, 1)]

    # 3. outbox: el mensaje saliente, ya codificado
    salientes = filas(limpia, "SELECT topico, clave, payload FROM outbox")
    assert len(salientes) == 1
    topico, clave, payload = salientes[0]
    assert topico == c.TOPICO_EVT_TRABAJOS
    assert clave == tid
    assert c.decodificar(bytes(payload)).type == "TrabajoCreado"


def test_el_sla_congelado_queda_en_el_payload_del_event_store(limpia):
    """EL ESCENARIO DE MODIFICABILIDAD, probado donde de verdad vive.

    regla_version y vence_en NO viajan en el contrato del grupo. Que el
    congelamiento se pruebe aqui -en eventos_trabajo.payload- y no en el mensaje
    es justamente la distincion entre evento de dominio y evento de integracion.
    """
    sembrar_regla(limpia, version=7, sla=120)
    sobre = sobre_crear()
    aplicacion.manejar_crear_trabajo(sobre)

    payload = filas(limpia, "SELECT payload FROM eventos_trabajo WHERE trabajo_id = %s",
                    (id_de(sobre),))[0][0]
    assert payload["sla_minutos"] == 120
    assert payload["regla_version"] == 7
    assert payload["vence_en"] is not None

    # ...y el mensaje de integracion NO los lleva: el contrato no los admite
    saliente = c.decodificar(bytes(filas(limpia, "SELECT payload FROM outbox")[0][0]))
    assert "regla_version" not in saliente.data
    assert "sla_vence_en" not in saliente.data
    assert saliente.data["ciudad"] == "BOGOTA"      # zona -> ciudad


def test_cambiar_la_regla_no_toca_el_trabajo_ya_creado(limpia):
    """La version end-to-end del escenario de modificabilidad."""
    sembrar_regla(limpia, version=7, sla=120)
    sobre = sobre_crear()
    aplicacion.manejar_crear_trabajo(sobre)
    tid = id_de(sobre)

    # el partner cambia su regla
    sembrar_regla(limpia, version=12, sla=15)

    # el trabajo viejo sigue igual: nadie hizo UPDATE sobre su evento
    payload = filas(limpia, "SELECT payload FROM eventos_trabajo WHERE trabajo_id = %s",
                    (tid,))[0][0]
    assert payload["sla_minutos"] == 120
    assert payload["regla_version"] == 7

    vista = filas(limpia, "SELECT sla_minutos FROM proyeccion_trabajo "
                          "WHERE trabajo_id = %s", (tid,))
    assert vista == [(120,)]


def test_rechazo_por_categoria_no_cubierta_tambien_se_publica(limpia):
    """El rechazo es un HECHO DE NEGOCIO, no una excepcion: se guarda y se
    publica para que la aseguradora se entere y sepa por que."""
    sembrar_regla(limpia, categorias=("ELECTRICIDAD",))
    sobre = sobre_crear(categoria="PLOMERIA")
    aplicacion.manejar_crear_trabajo(sobre)

    tipos = [f[0] for f in filas(limpia, "SELECT tipo FROM eventos_trabajo")]
    assert tipos == ["TrabajoRechazado"]

    estado = filas(limpia, "SELECT estado FROM proyeccion_trabajo")[0][0]
    assert estado == "RECHAZADO"

    saliente = c.decodificar(bytes(filas(limpia, "SELECT payload FROM outbox")[0][0]))
    assert saliente.type == "TrabajoRechazado"
    assert saliente.data["motivo"] == "CATEGORIA_NO_CUBIERTA"


def test_partner_desconocido_no_llama_a_nadie_y_rechaza(limpia):
    """DISPONIBILIDAD: sin regla local no se consulta a nadie por red. Se
    rechaza con lo que se sabe."""
    sobre = sobre_crear(partner_id="JAMAS_VISTO")
    aplicacion.manejar_crear_trabajo(sobre)
    saliente = c.decodificar(bytes(filas(limpia, "SELECT payload FROM outbox")[0][0]))
    assert saliente.data["motivo"] == "PARTNER_DESCONOCIDO"


# ═════════════════════════════════════════════════════════ idempotencia ════

def test_el_mismo_comando_dos_veces_crea_un_solo_trabajo(limpia):
    """Pulsar entrega al menos una vez. El MISMO sobre no puede crear dos
    trabajos."""
    sembrar_regla(limpia)
    sobre = sobre_crear()

    aplicacion.manejar_crear_trabajo(sobre)
    aplicacion.manejar_crear_trabajo(sobre)   # reentrega

    assert filas(limpia, "SELECT count(*) FROM eventos_trabajo")[0][0] == 1
    assert filas(limpia, "SELECT count(*) FROM proyeccion_trabajo")[0][0] == 1
    assert filas(limpia, "SELECT count(*) FROM outbox")[0][0] == 1


def test_el_trabajo_id_se_deriva_del_sobre_y_es_estable(limpia):
    """Segunda linea de defensa: aunque mensajes_procesados fallara, el mismo
    comando apunta al mismo agregado y la PK del event store lo frenaria."""
    sembrar_regla(limpia)
    sobre = sobre_crear()
    aplicacion.manejar_crear_trabajo(sobre)

    assert id_de(sobre) == str(uuid.uuid5(aplicacion._NS_TRABAJOS, sobre.id))
    assert filas(limpia, "SELECT count(*) FROM eventos_trabajo WHERE trabajo_id = %s",
                 (id_de(sobre),))[0][0] == 1


def test_dos_comandos_distintos_con_el_mismo_contenido_crean_dos_trabajos(limpia):
    """Y esta bien: son dos siniestros distintos. La idempotencia es por SOBRE,
    no por contenido."""
    sembrar_regla(limpia)
    aplicacion.manejar_crear_trabajo(sobre_crear())
    aplicacion.manejar_crear_trabajo(sobre_crear())
    assert filas(limpia, "SELECT count(*) FROM eventos_trabajo")[0][0] == 2


# ══════════════════════════════════════════ concurrencia optimista ═════════

def test_dos_escritores_sobre_el_mismo_trabajo_chocan_en_la_pk(limpia):
    """EL CONTROL DE CONCURRENCIA OPTIMISTA.

    Los dos leyeron secuencia 1 y los dos intentan escribir la 2. La PK
    compuesta (trabajo_id, secuencia) rechaza al segundo. No hay locks.
    """
    sembrar_regla(limpia)
    sobre = sobre_crear()
    aplicacion.manejar_crear_trabajo(sobre)
    tid = id_de(sobre)

    evento = ev.ProveedorAsignado(trabajo_id=tid, proveedor_id="P1")
    corr = str(uuid.uuid4())

    with limpia.pool().connection() as con, con.cursor() as cur:
        almacen.anexar(cur, tid, [evento], correlation_id=corr, secuencia_actual=1)

    # el segundo escritor cree que la secuencia sigue en 1
    with pytest.raises(almacen.ConflictoDeConcurrencia):
        with limpia.pool().connection() as con, con.cursor() as cur:
            almacen.anexar(cur, tid, [evento], correlation_id=corr,
                           secuencia_actual=1)


def test_el_event_store_es_append_only(limpia):
    """Ningun modulo hace UPDATE ni DELETE sobre eventos_trabajo. Es lo que
    convierte el congelamiento del SLA en una garantia."""
    import pathlib
    raiz = pathlib.Path(almacen.__file__).parent.parent.parent
    sospechosos = []
    for archivo in raiz.rglob("*.py"):
        texto = archivo.read_text(encoding="utf-8").upper()
        for verbo in ("UPDATE EVENTOS_TRABAJO", "DELETE FROM EVENTOS_TRABAJO"):
            if verbo in texto:
                sospechosos.append(f"{archivo.name}: {verbo}")
    assert sospechosos == []


# ═══════════════════════════════════════════════════ ciclo de evt.trabajos ═

def test_un_sobre_propio_en_evt_trabajos_se_descarta(limpia):
    """MITIGACION DEL CICLO.

    Publicamos TrabajoCreado en evt.trabajos y consumimos ese mismo topico para
    enterarnos de TrabajoAsignado. Sin este filtro reaccionariamos a nuestro
    propio eco.
    """
    from orquestacion.infraestructura.mensajeria import consumidores

    vistos = []
    sus = consumidores.Suscripcion(
        topico=c.TOPICO_EVT_TRABAJOS, nombre="prueba",
        tipo=0, manejadores={"TrabajoAsignado": vistos.append})

    class MensajeFalso:
        def __init__(self, crudo): self._crudo = crudo
        def data(self): return self._crudo

    # nuestro propio eco: NO debe llegar al manejador
    propio = c.empaquetar(c.TrabajoAsignado(trabajo_id="t", proveedor_id="P1"))
    assert propio.es_propio()
    consumidores._despachar(sus, MensajeFalso(propio.a_bytes()))
    assert vistos == []

    # el mismo mensaje, de Emparejamiento: SI debe llegar
    ajeno = c.empaquetar(c.TrabajoAsignado(trabajo_id="t", proveedor_id="P1"),
                         service_name="emparejamiento-asignacion")
    consumidores._despachar(sus, MensajeFalso(ajeno.a_bytes()))
    assert len(vistos) == 1


# ═════════════════════════════════════════════ asignacion y reasignacion ═══

def _crear_y_devolver_id(limpia):
    sembrar_regla(limpia)
    sobre = sobre_crear()
    aplicacion.manejar_crear_trabajo(sobre)
    return id_de(sobre)


def sobre_rechazo(tid, proveedor):
    return c.empaquetar(
        c.AsignacionRechazadaPorHabilitacion(
            trabajo_id=tid, proveedor_id=proveedor, estado_real="SUSPENDIDO",
            motivo="LICENCIA_VENCIDA", asignacion_id=str(uuid.uuid4())),
        service_name="acreditacion-habilitacion")


def test_asignar_pone_el_trabajo_en_asignado(limpia):
    tid = _crear_y_devolver_id(limpia)
    aplicacion.manejar_trabajo_asignado(c.empaquetar(
        c.TrabajoAsignado(trabajo_id=tid, proveedor_id="PROV_7",
                          asignacion_id=str(uuid.uuid4())),
        service_name="emparejamiento-asignacion"))

    vista = filas(limpia, "SELECT estado, proveedor_id FROM proyeccion_trabajo "
                          "WHERE trabajo_id = %s", (tid,))
    assert vista == [("ASIGNADO", "PROV_7")]


def test_el_tope_de_tres_intentos_escala(limpia):
    """EL UNICO PUNTO ORQUESTADO, de punta a punta."""
    tid = _crear_y_devolver_id(limpia)

    for proveedor in ("PROV_1", "PROV_2", "PROV_3"):
        aplicacion.manejar_asignacion_rechazada(sobre_rechazo(tid, proveedor))

    vista = filas(limpia, "SELECT estado, intentos, proveedores_excluidos FROM "
                          "proyeccion_trabajo WHERE trabajo_id = %s", (tid,))
    estado, intentos, excluidos = vista[0]
    assert estado == "ESCALADO_MANUAL"
    assert intentos == 3
    assert set(excluidos) == {"PROV_1", "PROV_2", "PROV_3"}

    # Se pidieron DOS reasignaciones, no tres: la tercera escala en vez de
    # reintentar.
    comandos = [c.decodificar(bytes(f[0])) for f in
                filas(limpia, "SELECT payload FROM outbox WHERE topico = %s",
                      (c.TOPICO_CMD_EMPAREJAMIENTO,))]
    assert len(comandos) == 2
    assert comandos[0].data["intento"] == 2
    assert comandos[1].data["intento"] == 3
    assert set(comandos[1].data["excluir_proveedores"]) == {"PROV_1", "PROV_2"}


def sobre_confirmacion(tid, proveedor, asignacion_id="a-ok"):
    return c.empaquetar(
        c.AsignacionConfirmadaPorHabilitacion(
            trabajo_id=tid, proveedor_id=proveedor, estado_real="HABILITADO",
            asignacion_id=asignacion_id,
            verificado_en=datetime.now(timezone.utc)),
        service_name="acreditacion-habilitacion")


def test_camino_feliz_cierra_la_saga_como_completada(limpia):
    """Transaccion larga exitosa: crear -> asignar -> confirmar."""
    tid = _crear_y_devolver_id(limpia)
    aplicacion.manejar_trabajo_asignado(c.empaquetar(
        c.TrabajoAsignado(trabajo_id=tid, proveedor_id="PROV_OK",
                          asignacion_id="asig-ok"),
        service_name="emparejamiento-asignacion"))
    aplicacion.manejar_asignacion_confirmada(sobre_confirmacion(tid, "PROV_OK", "asig-ok"))

    saga = filas(limpia, "SELECT estado, proveedor_id, paso_actual FROM "
                         "saga_asignacion WHERE saga_id = %s", (tid,))
    assert saga == [("COMPLETADA", "PROV_OK", "AsignacionConfirmadaPorHabilitacion")]

    pasos = filas(limpia, "SELECT secuencia, servicio, tipo_mensaje, rol, resultado "
                          "FROM saga_paso WHERE saga_id = %s ORDER BY secuencia", (tid,))
    assert [p[2] for p in pasos] == [
        "TrabajoCreado", "TrabajoAsignado", "AsignacionConfirmadaPorHabilitacion"]
    assert pasos[-1][3:] == ("CIERRE", "CONFIRMADO")
    assert filas(limpia, "SELECT estado FROM proyeccion_trabajo WHERE trabajo_id = %s",
                 (tid,))[0][0] == "ASIGNADO"


def test_rechazo_de_habilitacion_compensa_y_queda_en_el_saga_log(limpia):
    """Fallo que dispara compensacion: la asignacion optimista se deshace."""
    tid = _crear_y_devolver_id(limpia)
    aplicacion.manejar_trabajo_asignado(c.empaquetar(
        c.TrabajoAsignado(trabajo_id=tid, proveedor_id="PROV_MAL",
                          asignacion_id="asig-mal"),
        service_name="emparejamiento-asignacion"))
    aplicacion.manejar_asignacion_rechazada(sobre_rechazo(tid, "PROV_MAL"))

    vista = filas(limpia, "SELECT estado, proveedor_id FROM proyeccion_trabajo "
                          "WHERE trabajo_id = %s", (tid,))
    assert vista == [("CREADO", None)]

    saga = filas(limpia, "SELECT estado, motivo FROM saga_asignacion WHERE saga_id = %s",
                 (tid,))
    assert saga[0][0] == "COMPENSADA"
    assert "LICENCIA_VENCIDA" in saga[0][1]

    roles = [f[0] for f in filas(
        limpia, "SELECT rol FROM saga_paso WHERE saga_id = %s ORDER BY secuencia", (tid,))]
    assert roles.count("COMPENSACION") == 2
    assert "PASO" in roles


def test_los_excluidos_viajan_en_el_comando(limpia):
    """Emparejamiento no puede leer nuestra base: el estado necesario para
    decidir va EN EL MENSAJE."""
    tid = _crear_y_devolver_id(limpia)
    aplicacion.manejar_asignacion_rechazada(sobre_rechazo(tid, "PROV_1"))

    comando = c.decodificar(bytes(filas(
        limpia, "SELECT payload FROM outbox WHERE topico = %s",
        (c.TOPICO_CMD_EMPAREJAMIENTO,))[0][0]))
    assert comando.type == "AsignarProveedor"
    assert comando.data["excluir_proveedores"] == ["PROV_1"]


# ═══════════════════════════════════════════════════════ barrido de SLA ════

def test_el_barrido_escala_lo_vencido(limpia):
    """Los eventos dicen lo que paso, nunca lo que NO paso."""
    sembrar_regla(limpia, sla=120)
    sobre = sobre_crear()
    aplicacion.manejar_crear_trabajo(sobre)
    tid = id_de(sobre)

    # Se ADELANTA EL RELOJ en vez de envejecer los datos. Editar un evento ya
    # ocurrido para que una prueba pase seria contradecir justo lo que el event
    # store garantiza.
    manana = datetime.now(timezone.utc) + timedelta(days=1)
    assert aplicacion.barrer_sla(ahora=manana) == 1
    assert filas(limpia, "SELECT estado FROM proyeccion_trabajo WHERE trabajo_id = %s",
                 (tid,))[0][0] == "ESCALADO_MANUAL"


def test_el_barrido_no_toca_lo_ya_asignado(limpia):
    """ASIGNADO detiene el reloj: el SLA es de respuesta, no de ejecucion."""
    tid = _crear_y_devolver_id(limpia)
    aplicacion.manejar_trabajo_asignado(c.empaquetar(
        c.TrabajoAsignado(trabajo_id=tid, proveedor_id="PROV_7"),
        service_name="emparejamiento-asignacion"))

    assert aplicacion.barrer_sla(ahora=datetime.now(timezone.utc) + timedelta(days=1)) == 0
    assert filas(limpia, "SELECT estado FROM proyeccion_trabajo WHERE trabajo_id = %s",
                 (tid,))[0][0] == "ASIGNADO"
