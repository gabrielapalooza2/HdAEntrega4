#!/usr/bin/env python3
"""Mirilla sobre cualquier topico del namespace. Imprime y sigue.

Hace falta sobre todo para evt.trabajos: ahi publicamos TrabajoCreado y
TrabajoRechazado, y no los consumimos (el consumidor real descarta los sobres
propios). Sin esta herramienta no habria forma de VER que lo que publicamos es
lo que el contrato dice.

  python scripts/escuchar.py evt.trabajos
  python scripts/escuchar.py cmd.emparejamiento --desde-el-inicio
  python scripts/escuchar.py evt.trabajos --maximo 2 --desde-el-inicio
"""
import argparse
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import _pulsar
import pulsar

from orquestacion.config import broker_url, opciones_cliente
from orquestacion.mensajeria import contratos as c


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("topico", help="nombre corto (evt.trabajos) o completo")
    p.add_argument("--desde-el-inicio", action="store_true",
                   help="lee el topico desde el primer mensaje retenido")
    # Con --maximo la mirilla termina sola. Sirve para guiones de demo y para
    # las pruebas: sin esto solo se puede usar a mano, con Ctrl-C.
    p.add_argument("--maximo", type=int, metavar="N",
                   help="sale despues de N mensajes en vez de quedarse")
    p.add_argument("--espera-segundos", type=float, default=15.0,
                   help="con --maximo, cuanto esperar sin recibir nada antes de rendirse")
    args = p.parse_args()

    topico = args.topico if "://" in args.topico else f"{c.NAMESPACE}/{args.topico}"

    cliente = pulsar.Client(broker_url(),
                            logger=pulsar.ConsoleLogger(pulsar.LoggerLevel.Warn),
                            **opciones_cliente())
    try:
        consumidor = cliente.subscribe(
            topico,
            # Nombre ALEATORIO y suscripcion Exclusive: una mirilla no debe
            # robarle mensajes al consumidor real del servicio. Si compartiera
            # el nombre de suscripcion, Pulsar repartiria los mensajes entre los
            # dos y el servicio dejaria de ver la mitad.
            subscription_name=f"mirilla-{uuid.uuid4().hex[:8]}",
            consumer_type=_pulsar.ConsumerType.Exclusive,
            schema=pulsar.schema.BytesSchema(),
            initial_position=(_pulsar.InitialPosition.Earliest if args.desde_el_inicio
                              else _pulsar.InitialPosition.Latest),
        )
        print(f"escuchando {topico}  (Ctrl-C para salir)\n", flush=True)

        vistos = 0
        while True:
            if args.maximo is None:
                mensaje = consumidor.receive()
            else:
                try:
                    mensaje = consumidor.receive(
                        timeout_millis=int(args.espera_segundos * 1000))
                except Exception:
                    print(f"nada mas en {args.espera_segundos}s; salgo con {vistos}",
                          flush=True)
                    break
            crudo = mensaje.data()
            sobre = c.decodificar(crudo)
            if sobre is None:
                print(f"[?] {len(crudo)} bytes que esta costura no sabe leer "
                      f"(tipo de otro equipo, o basura)", flush=True)
            else:
                marca = " (ECO PROPIO)" if sobre.es_propio() else ""
                print(f"[{sobre.type}]{marca}  de={sobre.service_name}  "
                      f"clave={mensaje.partition_key()}  corr={sobre.correlation_id}")
                print(json.dumps(sobre.data, indent=2, ensure_ascii=False, default=str))
                print(flush=True)
            consumidor.acknowledge(mensaje)

            vistos += 1
            if args.maximo is not None and vistos >= args.maximo:
                break
    except KeyboardInterrupt:
        print("\nchau")
    finally:
        cliente.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
