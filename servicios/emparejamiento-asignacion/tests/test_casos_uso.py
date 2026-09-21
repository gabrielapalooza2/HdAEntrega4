from __future__ import annotations

from aplicacion.servicios import ServicioAsignacion, ServicioProyecciones
from dominio.modelo import Asignacion, EstadoAsignacion, TrabajoAsignado


class MemRepo:
    def __init__(self):
        self.asignaciones = {}
        self.reglas = {}
        self.habs = {}
        self.procesados = set()
        self.fallidas = []

    def obtener_por_trabajo(self, trabajo_id):
        for a in self.asignaciones.values():
            if a.trabajo_id == trabajo_id:
                return a
        return None

    def obtener_por_id(self, asignacion_id):
        return self.asignaciones.get(asignacion_id)

    def guardar(self, asignacion):
        self.asignaciones[asignacion.asignacion_id] = asignacion

    def upsert_regla(self, regla):
        self.reglas[regla.partner_id] = regla

    def obtener_regla(self, partner_id):
        return self.reglas.get(partner_id)

    def contar_reglas(self):
        return len(self.reglas)

    def upsert_hab(self, h):
        self.habs[h.proveedor_id] = h

    def listar_habs(self):
        return list(self.habs.values())

    def contar_habs(self):
        return len(self.habs)

    def ya_procesado(self, evento_id):
        return evento_id in self.procesados

    def marcar(self, evento_id):
        self.procesados.add(evento_id)

    def guardar_fallida(self, f):
        self.fallidas.append(f)


class MemUoW:
    def __init__(self, mem: MemRepo):
        self._mem = mem
        self.asignaciones = mem
        self.reglas = type("R", (), {
            "upsert": mem.upsert_regla,
            "obtener": mem.obtener_regla,
            "contar": mem.contar_reglas,
        })()
        self.habilitaciones = type("H", (), {
            "upsert": mem.upsert_hab,
            "listar": mem.listar_habs,
            "contar": mem.contar_habs,
        })()
        self.eventos_procesados = type("E", (), {
            "ya_procesado": mem.ya_procesado,
            "marcar": mem.marcar,
        })()
        self.fallidas = type("F", (), {"guardar": mem.guardar_fallida})()

    def commit(self):
        pass

    def rollback(self):
        pass


class RelojFijo:
    def ahora_ms(self):
        return 1_700_000_000_000


class PubMem:
    def __init__(self):
        self.eventos = []

    def publicar(self, evento: TrabajoAsignado):
        self.eventos.append(evento)


def _ce(tipo, data, eid="x", corr="c-1", time_ms=1_700_000_000_000):
    return {
        "id": eid,
        "time": time_ms,
        "ingestion": time_ms,
        "specversion": "v1",
        "type": tipo,
        "datacontenttype": "AVRO",
        "service_name": "test",
        "correlation_id": corr,
        "data": data,
    }


def test_filtra_tipo_trabajo_asignado_sin_publicar():
    mem, pub = MemRepo(), PubMem()
    svc = ServicioAsignacion(lambda: MemUoW(mem), pub, RelojFijo())
    r = svc.on_evento_trabajos(_ce("TrabajoAsignado", {"trabajo_id": "t"}, eid="x"))
    assert r.ignorado
    assert pub.eventos == []


def test_filtra_trabajo_rechazado_sin_publicar():
    mem, pub = MemRepo(), PubMem()
    svc = ServicioAsignacion(lambda: MemUoW(mem), pub, RelojFijo())
    r = svc.on_evento_trabajos(
        _ce("TrabajoRechazado", {"trabajo_id": "t", "motivo": "FUERA_DE_COBERTURA"})
    )
    assert r.ignorado
    assert pub.eventos == []


def test_idempotencia_evento_id():
    mem, pub = MemRepo(), PubMem()
    proy = ServicioProyecciones(lambda: MemUoW(mem))
    svc = ServicioAsignacion(lambda: MemUoW(mem), pub, RelojFijo())
    proy.aplicar_habilitacion(_ce(
        "EstadoDeHabilitacionCambiado",
        {
            "proveedor_id": "prov-a",
            "nombre": "A",
            "estado": "HABILITADO",
            "categorias": ["PLOMERIA"],
            "ciudades": ["Bogota"],
            "motivo": "",
            "vigente_hasta": 0,
        },
        eid="h1",
    ))
    payload = _ce(
        "TrabajoCreado",
        {
            "trabajo_id": "t-1",
            "partner_id": "p-1",
            "mercado_id": "CO",
            "categoria": "PLOMERIA",
            "urgencia": "ALTA",
            "ciudad": "Bogota",
            "sla_minutos": 30,
            "requiere_aprobacion": False,
        },
        eid="creado-1",
        corr="c-1",
    )
    r1 = svc.on_evento_trabajos(payload)
    r2 = svc.on_evento_trabajos(payload)
    assert r1.evento is not None
    assert r1.evento.origen_habilitacion == "PROYECCION_LOCAL"
    assert r1.evento.partner_id == "p-1"
    assert r1.evento.service_name == "emparejamiento-asignacion"
    assert r1.evento.a_dict()["data"]["origen_habilitacion"] == "PROYECCION_LOCAL"
    assert r2.ya_procesado
    assert len(pub.eventos) == 1
    assert len(mem.asignaciones) == 1
    assert mem.asignaciones[r1.asignacion.asignacion_id].verificado_en == 1_700_000_000_000


def test_rechazo_de_regla_partner_marca_y_no_republica():
    mem, pub = MemRepo(), PubMem()
    a = Asignacion(
        asignacion_id="a-1",
        trabajo_id="t-1",
        proveedor_id="prov-a",
        partner_id="p-1",
        correlacion_id="c-1",
        sla_vence_en=1,
        verificado_en=1,
        ocurrido_en=1,
        estado=EstadoAsignacion.ASIGNADO,
    )
    mem.guardar(a)
    svc = ServicioAsignacion(lambda: MemUoW(mem), pub, RelojFijo())
    r = svc.on_rechazo_habilitacion(_ce(
        "AsignacionRechazadaPorReglaPartner",
        {
            "trabajo_id": "t-1",
            "asignacion_id": "a-1",
            "proveedor_id": "prov-a",
            "partner_id": "p-1",
            "regla_version": 1,
            "motivo": "PROVEEDOR_FUERA_DE_RED",
            "verificado_en": 1,
        },
        eid="rej-regla-1",
    ))
    assert r.asignacion.estado == EstadoAsignacion.RECHAZADO
    assert pub.eventos == []


def test_rechazo_marca_y_no_republica():
    mem, pub = MemRepo(), PubMem()
    a = Asignacion(
        asignacion_id="a-1",
        trabajo_id="t-1",
        proveedor_id="prov-a",
        partner_id="p-1",
        correlacion_id="c-1",
        sla_vence_en=1,
        verificado_en=1,
        ocurrido_en=1,
        estado=EstadoAsignacion.ASIGNADO,
    )
    mem.guardar(a)
    svc = ServicioAsignacion(lambda: MemUoW(mem), pub, RelojFijo())
    r = svc.on_rechazo_habilitacion(_ce(
        "AsignacionRechazadaPorHabilitacion",
        {
            "trabajo_id": "t-1",
            "asignacion_id": "a-1",
            "proveedor_id": "prov-a",
            "estado_real": "SUSPENDIDO",
            "motivo": "no",
            "verificado_en": 1,
        },
        eid="rej-1",
    ))
    assert r.asignacion.estado == EstadoAsignacion.RECHAZADO
    assert pub.eventos == []


def test_confirmacion_marca_sin_republicar():
    mem, pub = MemRepo(), PubMem()
    a = Asignacion(
        asignacion_id="a-1",
        trabajo_id="t-1",
        proveedor_id="prov-a",
        partner_id="p-1",
        correlacion_id="c-1",
        sla_vence_en=1,
        verificado_en=1,
        ocurrido_en=1,
        estado=EstadoAsignacion.ASIGNADO,
    )
    mem.guardar(a)
    svc = ServicioAsignacion(lambda: MemUoW(mem), pub, RelojFijo())
    r = svc.on_confirmacion_habilitacion(_ce(
        "AsignacionConfirmadaPorHabilitacion",
        {
            "trabajo_id": "t-1",
            "asignacion_id": "a-1",
            "proveedor_id": "prov-a",
            "estado_real": "HABILITADO",
            "verificado_en": 9,
        },
        eid="ok-1",
    ))
    assert r.asignacion.estado == EstadoAsignacion.CONFIRMADO
    assert r.asignacion.verificado_en == 9
    assert pub.eventos == []
