#!/usr/bin/env python3
"""ESCENARIO DE ESCALABILIDAD: rampa de CREACION DE TRABAJOS.

QUE SE MIDE Y QUE NO
--------------------
El volumen del negocio son TRABAJOS, no partners. Hoy son 12.000 trabajos/dia,
la proyeccion son 36.000, y el caso describe picos de 4x en 48 horas cuando hay
un evento climatico. Incorporar un partner, en cambio, ocurre unas treinta veces
en la historia de la empresa: inyectar partners a 200 por segundo no mide nada
del negocio y seria la "mala experimentacion" contra la que advierte el enunciado.

Por eso este script publica el comando CrearTrabajo en `comandos-trabajos`, que es
la entrada del servicio Orquestacion de trabajos.

QUE PAPEL JUEGA MOTOR REGLAS PARTNER EN ESTE ESCENARIO
------------------------------------------------------
Ninguno en el camino critico, Y ESO ES LA DECISION DE DISENO. Como publica eventos
con CARGA DE ESTADO y los consumidores guardan una proyeccion local, este servicio
NO aparece en el flujo de los 36.000 trabajos diarios. Si en lugar de eso
Orquestacion tuviera que consultarlo por cada trabajo, seria el cuello de botella
del sistema entero. La medida de este escenario incluye comprobar precisamente eso:
el backlog de `comandos-partner` permanece en cero mientras `comandos-trabajos`
absorbe el pico.

USO
---
    python scripts/semilla_partners.py --cantidad 30     # una sola vez
    python scripts/carga_escalabilidad.py --rps 10 50 200 --segundos 30
    docker exec broker bin/pulsar-admin topics stats persistent://hda/poc/comandos-trabajos
"""
import argparse
import os
import random
import sys
import time
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pulsar
from pulsar.schema import AvroSchema, Array, Integer, Long, Record, String

from motor_reglas.seedwork.infraestructura.utils import broker_url, time_millis

TOPICO_TRABAJOS = "persistent://hda/poc/comandos-trabajos"
TOPICO_PARTNERS = "persistent://hda/poc/comandos-partner"

CATEGORIAS = ["PLOMERIA", "ELECTRICIDAD", "CARPINTERIA", "PINTURA", "CERRAJERIA"]
URGENCIAS = ["PROGRAMADA", "ALTA", "EMERGENCIA"]
CIUDADES = ["Bogota", "Medellin", "Cali", "Cartagena", "Barranquilla"]


# El esquema del comando lo posee Orquestacion de trabajos; aqui se replica
# unicamente para poder generar carga. La fuente de verdad es contratos/cmd.trabajos/.
class CrearTrabajoPayload(Record):
    partner_id = String()
    mercado_id = String()
    categoria = String()
    urgencia = String()
    ciudad = String()
    descripcion = String()
    monto_estimado = Long(default=0)
    moneda = String(default="COP")


class ComandoCrearTrabajo(Record):
    id = String()
    time = Long()
    ingestion = Long()
    specversion = String(default="v1")
    type = String(default="CrearTrabajo")
    datacontenttype = String(default="AVRO")
    service_name = String(default="generador-carga")
    correlation_id = String()
    data = CrearTrabajoPayload()


def trabajo_sintetico(partner_ids: list[str]) -> ComandoCrearTrabajo:
    """Un trabajo de un partner QUE YA EXISTE.

    La semilla de partners corre antes y una sola vez, igual que en la realidad:
    los convenios se firman en el area comercial, no en el pico de demanda.
    """
    correlacion = str(uuid.uuid4())
    return ComandoCrearTrabajo(
        id=str(uuid.uuid4()),
        time=time_millis(),
        ingestion=time_millis(),
        specversion="v1",
        type="CrearTrabajo",
        datacontenttype="AVRO",
        service_name="generador-carga",
        correlation_id=correlacion,
        data=CrearTrabajoPayload(
            partner_id=random.choice(partner_ids),
            mercado_id="CO",
            categoria=random.choice(CATEGORIAS),
            urgencia=random.choice(URGENCIAS),
            ciudad=random.choice(CIUDADES),
            descripcion="Fuga en el bano principal",
            monto_estimado=random.randint(50_000_00, 3_000_000_00),
            moneda="COP",
        ),
    )


def leer_partners(api: str) -> list[str]:
    import json
    import urllib.request

    with urllib.request.urlopen(f"{api}/partners?activos=true", timeout=5) as r:
        partners = json.loads(r.read())
    if not partners:
        raise SystemExit(
            "No hay partners registrados. Corra primero:\n"
            "    python scripts/semilla_partners.py --cantidad 30"
        )
    return [p["id"] for p in partners]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--rps", type=int, nargs="+", default=[10, 50, 200],
                   help="rampa de trabajos por segundo")
    p.add_argument("--segundos", type=int, default=30)
    p.add_argument("--api", default=os.getenv("API", "http://localhost:5000"))
    args = p.parse_args()

    partner_ids = leer_partners(args.api)
    print(f"Generando trabajos repartidos entre {len(partner_ids)} partners ya registrados.\n")

    cliente = pulsar.Client(broker_url())
    productor = cliente.create_producer(
        TOPICO_TRABAJOS,
        schema=AvroSchema(ComandoCrearTrabajo),
        batching_enabled=True,
        batching_max_publish_delay_ms=10,
        # Si el broker se satura, BLOQUEA al productor en vez de descartar mensajes.
        # Perder trabajos en silencio invalidaria la medicion entera.
        block_if_queue_full=True,
    )

    total = 0
    for rps in args.rps:
        print(f"== Rampa a {rps} trabajos/segundo durante {args.segundos}s ==")
        intervalo = 1.0 / rps
        inicio = time.time()
        latencias = []
        while time.time() - inicio < args.segundos:
            t0 = time.perf_counter()
            productor.send(trabajo_sintetico(partner_ids))
            latencias.append((time.perf_counter() - t0) * 1000)
            total += 1
            dormir = intervalo - (time.perf_counter() - t0)
            if dormir > 0:
                time.sleep(dormir)
        latencias.sort()
        print(f"   trabajos acumulados : {total}")
        print(f"   latencia p95 publish: {latencias[int(len(latencias) * 0.95)]:.2f} ms")
        print(f"   throughput real     : {len(latencias) / args.segundos:.1f} trabajos/s")
        print(f"   equivalente diario  : {int(len(latencias) / args.segundos * 86400):,} trabajos/dia\n")

    cliente.close()

    print("Mediciones a tomar ahora:")
    print(f"  1. backlog y consumo del flujo de trabajos:")
    print(f"     docker exec broker bin/pulsar-admin topics stats {TOPICO_TRABAJOS}")
    print(f"  2. el flujo administrativo NO se movio -esa es la decision de diseno-:")
    print(f"     docker exec broker bin/pulsar-admin topics stats {TOPICO_PARTNERS}")
    print(f"  3. drenar el backlog agregando replicas del consumidor:")
    print(f"     docker compose up -d --scale orquestacion-trabajos=3")


if __name__ == "__main__":
    main()
