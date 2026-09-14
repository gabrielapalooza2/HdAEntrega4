#!/usr/bin/env python3
"""Envia UN comando CrearTrabajo. Es la fase operativa del escenario 6.

Ojo con la distincion que este script hace explicita: registrar un partner y crear
un trabajo son dos actos distintos, con actores distintos y frecuencias distintas.
Este script solo hace el segundo, y usa un partner que YA existe.

El comando va al topico de Orquestacion de trabajos; el esquema lo posee ese
servicio y aqui se replica solo para poder emitirlo.
"""
import argparse
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pulsar
from pulsar.schema import AvroSchema

from motor_reglas.seedwork.infraestructura.utils import broker_url, time_millis

from carga_escalabilidad import ComandoCrearTrabajo, CrearTrabajoPayload, TOPICO_TRABAJOS


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--partner-id", required=True, help="un partner que YA existe")
    p.add_argument("--categoria", default="PLOMERIA")
    p.add_argument("--urgencia", default="ALTA")
    p.add_argument("--ciudad", default="Bogota")
    p.add_argument("--monto", type=int, default=150_000_00)
    args = p.parse_args()

    correlacion = str(uuid.uuid4())
    cliente = pulsar.Client(broker_url())
    productor = cliente.create_producer(TOPICO_TRABAJOS, schema=AvroSchema(ComandoCrearTrabajo))
    productor.send(ComandoCrearTrabajo(
        id=str(uuid.uuid4()), time=time_millis(), ingestion=time_millis(),
        specversion="v1", type="CrearTrabajo", datacontenttype="AVRO",
        service_name="demo", correlation_id=correlacion,
        data=CrearTrabajoPayload(
            partner_id=args.partner_id, mercado_id="CO",
            categoria=args.categoria, urgencia=args.urgencia, ciudad=args.ciudad,
            descripcion="Fuga en el bano principal",
            monto_estimado=args.monto, moneda="COP"),
    ))
    cliente.close()
    print(f"   CrearTrabajo enviado | partner={args.partner_id} categoria={args.categoria}")
    print(f"   correlacion={correlacion}  <- sigalo por los cuatro servicios")


if __name__ == "__main__":
    main()
