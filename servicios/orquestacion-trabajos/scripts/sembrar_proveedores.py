#!/usr/bin/env python3
"""Simula al servicio de Acreditacion y Habilitacion, que todavia no existe.

Emparejamiento no puede asignar sin proveedores habilitados, y esos los publica
Acreditacion en evt.proveedores. Hasta que ese servicio exista, la demo los
simula desde aqui.

OJO CON LAS MAYUSCULAS: Emparejamiento compara la ciudad con `in` exacto y no
normaliza, asi que la ciudad de aqui tiene que coincidir LETRA POR LETRA con la
`zona` con que se crean los trabajos. Esta acordado usar mayusculas.
"""
import io
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pulsar
from fastavro import parse_schema, schemaless_writer

from orquestacion.config import CONTRATOS_DIR, broker_url, opciones_cliente
from orquestacion.mensajeria import contratos as c

ESQUEMA = parse_schema(json.loads(
    (CONTRATOS_DIR / "esquemas" / "evt.proveedores" /
     "EstadoDeHabilitacionCambiado.avsc").read_text(encoding="utf-8")))

PROVEEDORES = [
    ("PROV_ALFA",  "HABILITADO", ["PLOMERIA", "ELECTRICIDAD"], ["BOGOTA"]),
    ("PROV_BETA",  "HABILITADO", ["PLOMERIA"],                 ["BOGOTA"]),
    ("PROV_GAMMA", "SUSPENDIDO", ["PLOMERIA"],                 ["BOGOTA"]),
]


def main() -> int:
    ahora = int(time.time() * 1000)
    cliente = pulsar.Client(broker_url(),
                            logger=pulsar.ConsoleLogger(pulsar.LoggerLevel.Warn),
                            **opciones_cliente())
    try:
        productor = cliente.create_producer(f"{c.NAMESPACE}/evt.proveedores",
                                            schema=pulsar.schema.BytesSchema())
        for pid, estado, categorias, ciudades in PROVEEDORES:
            sobre = {
                "id": str(uuid.uuid4()), "time": ahora, "ingestion": ahora,
                "specversion": "v1", "type": "EstadoDeHabilitacionCambiado",
                "datacontenttype": "AVRO",
                # service_name AJENO: firmar como orquestacion-trabajos haria que
                # el filtro anti-ciclo descartara la siembra.
                "service_name": "acreditacion-habilitacion",
                "correlation_id": str(uuid.uuid4()),
                "data": {"proveedor_id": pid, "nombre": pid, "estado": estado,
                         "categorias": categorias, "ciudades": ciudades,
                         "motivo": "" if estado == "HABILITADO" else "licencia vencida",
                         "vigente_hasta": 0},
            }
            buf = io.BytesIO()
            schemaless_writer(buf, ESQUEMA, sobre)
            productor.send(buf.getvalue(), partition_key=pid)
            print(f"  {pid:12s} {estado:11s} {categorias} en {ciudades}")
        productor.flush()
        print(f"\n{len(PROVEEDORES)} proveedores publicados en evt.proveedores")
    finally:
        cliente.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
