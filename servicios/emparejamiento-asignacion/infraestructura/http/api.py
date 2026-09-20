from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

import pulsar
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse

from infraestructura.http.demo import DemoBus, montar_demo
from infraestructura.mensajeria.avro_codec import cargar_avsc
from infraestructura.mensajeria.pulsar_io import (
    TOPIC_PARTNERS,
    TOPIC_PROVEEDORES,
    ConsumidoresPulsar,
    PublicadorTrabajoAsignadoPulsar,
)
from infraestructura.persistencia.uow import SqlAlchemyUoW
from aplicacion.servicios import ServicioAsignacion, ServicioProyecciones
from infraestructura.config import Settings
from infraestructura.db import crear_engine, crear_session_factory, crear_tablas, esperar_db
from infraestructura.pulsar_admin import bootstrap_pulsar, esperar_admin, registrar_esquema

log = logging.getLogger("emparejamiento")


class RelojSistema:
    def ahora_ms(self) -> int:
        return int(time.time() * 1000)


def crear_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.load()
    estado: dict = {
        "settings": settings,
        "listo": False,
        "client": None,
        "consumidores": None,
    }

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
        engine = crear_engine(settings.database_dsn)
        esperar_db(engine)
        crear_tablas(engine)
        session_factory = crear_session_factory(engine)

        def fabrica_uow():
            return SqlAlchemyUoW(session_factory)

        esperar_admin(settings.pulsar_admin_url)
        bootstrap_pulsar(settings.pulsar_admin_url)

        contratos = settings.contratos_dir
        avsc_asignado = cargar_avsc(contratos, "evt.trabajos", "TrabajoAsignado")
        registrar_esquema(
            settings.pulsar_admin_url,
            TOPIC_PARTNERS,
            cargar_avsc(contratos, "evt.partners", "ReglaDePartnerActualizada"),
        )
        registrar_esquema(
            settings.pulsar_admin_url,
            TOPIC_PROVEEDORES,
            cargar_avsc(contratos, "evt.proveedores", "EstadoDeHabilitacionCambiado"),
        )
        # evt.trabajos y evt.asignaciones son multi-tipo: no se fija un único Avro.

        client = pulsar.Client(settings.pulsar_url)
        publicador = PublicadorTrabajoAsignadoPulsar(client, avsc_asignado)
        proyecciones = ServicioProyecciones(fabrica_uow)
        asignacion = ServicioAsignacion(fabrica_uow, publicador, RelojSistema())

        consumidores = ConsumidoresPulsar(
            client,
            contratos,
            on_regla=proyecciones.aplicar_regla_partner,
            on_habilitacion=proyecciones.aplicar_habilitacion,
            on_trabajos=asignacion.on_evento_trabajos,
            on_rechazo=asignacion.on_rechazo_habilitacion,
            on_confirmacion=asignacion.on_confirmacion_habilitacion,
        )
        consumidores.arrancar()
        estado.update(
            {
                "listo": True,
                "client": client,
                "consumidores": consumidores,
                "asignacion": asignacion,
                "fabrica_uow": fabrica_uow,
                "engine": engine,
                "demo_bus": DemoBus(client, contratos),
            }
        )
        log.info("emparejamiento-asignacion listo")
        try:
            yield
        finally:
            estado["listo"] = False
            if consumidores:
                consumidores.detener()
            client.close()
            engine.dispose()

    app = FastAPI(title="emparejamiento-asignacion", lifespan=lifespan)

    @app.get("/health")
    def health():
        if not estado.get("listo"):
            return JSONResponse({"status": "starting"}, status_code=503)
        uow = estado["fabrica_uow"]()
        try:
            reglas = uow.reglas.contar()
            habs = uow.habilitaciones.contar()
        finally:
            uow.rollback()
        return {"status": "ok", "proyecciones": {"reglas": reglas, "habilitaciones": habs}}

    @app.get("/health/ok", response_class=PlainTextResponse)
    def health_ok():
        if not estado.get("listo"):
            return PlainTextResponse("starting", status_code=503)
        return "ok"

    @app.get("/asignaciones/{trabajo_id}")
    def get_asignacion(trabajo_id: str):
        servicio: ServicioAsignacion = estado["asignacion"]
        asignacion = servicio.consultar(trabajo_id)
        if asignacion is None:
            raise HTTPException(status_code=404, detail="asignacion no encontrada")
        return {
            "asignacion_id": asignacion.asignacion_id,
            "trabajo_id": asignacion.trabajo_id,
            "proveedor_id": asignacion.proveedor_id,
            "partner_id": asignacion.partner_id,
            "estado": asignacion.estado.value,
            "sla_vence_en": asignacion.sla_vence_en,
            "origen_habilitacion": asignacion.origen_habilitacion,
            "verificado_en": asignacion.verificado_en,
            "correlation_id": asignacion.correlacion_id,
            "time": asignacion.ocurrido_en,
        }

    app.include_router(montar_demo(estado))
    return app


app = crear_app()
