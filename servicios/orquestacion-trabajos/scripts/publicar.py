#!/usr/bin/env python3
"""Publica a mano cualquier mensaje de ENTRADA de este servicio.

Existe porque los otros tres microservicios no siempre estan levantados. Sin
esto, probar el consumidor de reglas exigiria tener corriendo el Motor de Reglas
de Partner, y la prueba de concepto dejaria de poder demostrarse por partes.

Ejemplos
--------
  # una regla que cubre PLOMERIA
  python scripts/publicar.py ReglaDePartnerActualizada --partner-id SEGUROS_ANDES

  # crear un trabajo para ese partner
  python scripts/publicar.py CrearTrabajo --partner-id SEGUROS_ANDES --categoria PLOMERIA

  # el MISMO sobre tres veces, para probar idempotencia
  python scripts/publicar.py CrearTrabajo --duplicar 3

  # ver que saldria, sin publicar nada
  python scripts/publicar.py TrabajoAsignado --trabajo-id <uuid> --solo-mostrar
"""
import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pulsar

from orquestacion.config import broker_url, opciones_cliente
from orquestacion.mensajeria import contratos as c

# El service_name simulado NO puede ser el nuestro: el consumidor de
# evt.trabajos descarta todo sobre propio para romper el ciclo, y si firmaramos
# como "orquestacion-trabajos" los mensajes de prueba se irian a la basura sin
# que quede claro por que.
EMISORES = {
    "CrearTrabajo":                       "portal-aseguradora",
    "ReglaDePartnerActualizada":          "motor-reglas-partner",
    "TrabajoAsignado":                    "emparejamiento-asignacion",
    "AsignacionRechazadaPorHabilitacion": "acreditacion-habilitacion",
}


def ejemplos() -> dict:
    """Valores de ejemplo, listos para que el comando mas corto ya funcione."""
    return {
        "CrearTrabajo": c.CrearTrabajo(
            partner_id="SEGUROS_ANDES", mercado_id="BOG", categoria="PLOMERIA",
            urgencia="ALTA", zona="BOGOTA", descripcion="Fuga bajo el lavaplatos",
            monto_estimado=350000, moneda="COP",
        ),
        "ReglaDePartnerActualizada": c.ReglaDePartnerActualizada(
            partner_id="SEGUROS_ANDES", regla_version=1, sla_minutos=120,
            categorias_cubiertas=["PLOMERIA", "ELECTRICIDAD"],
            monto_max=Decimal("500000"), moneda="COP", activo=True,
        ),
        "TrabajoAsignado": c.TrabajoAsignado(
            trabajo_id=str(uuid.uuid4()), asignacion_id=str(uuid.uuid4()),
            proveedor_id="PROV_001", partner_id="SEGUROS_ANDES",
            vence_en=datetime.now(timezone.utc), origen_habilitacion="CACHE_LOCAL",
        ),
        "AsignacionRechazadaPorHabilitacion": c.AsignacionRechazadaPorHabilitacion(
            trabajo_id=str(uuid.uuid4()), asignacion_id=str(uuid.uuid4()),
            proveedor_id="PROV_001", estado_real="SUSPENDIDO",
            motivo="LICENCIA_VENCIDA", verificado_en=datetime.now(timezone.utc),
        ),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("tipo", choices=sorted(EMISORES))
    p.add_argument("--partner-id")
    p.add_argument("--trabajo-id")
    p.add_argument("--proveedor-id")
    p.add_argument("--categoria")
    p.add_argument("--zona")
    p.add_argument("--sla-minutos", type=int)
    p.add_argument("--regla-version", type=int)
    p.add_argument("--categorias", help="separadas por coma: PLOMERIA,ELECTRICIDAD")
    p.add_argument("--activo", choices=["si", "no"])
    p.add_argument("--monto-estimado", type=int)
    p.add_argument("--correlation-id")
    p.add_argument("--duplicar", type=int, default=1, metavar="N",
                   help="reenvia N veces el MISMO sobre (mismo id) para probar idempotencia")
    p.add_argument("--solo-mostrar", action="store_true",
                   help="imprime el sobre y no publica nada")
    args = p.parse_args()

    mensaje = ejemplos()[args.tipo]

    # Sobreescritura campo a campo. Solo se aplica lo que el mensaje tenga.
    posibles = {
        "partner_id": args.partner_id,
        "trabajo_id": args.trabajo_id,
        "proveedor_id": args.proveedor_id,
        "categoria": args.categoria,
        "zona": args.zona,
        "sla_minutos": args.sla_minutos,
        "regla_version": args.regla_version,
        "monto_estimado": args.monto_estimado,
        "categorias_cubiertas": args.categorias.split(",") if args.categorias else None,
        "activo": None if args.activo is None else (args.activo == "si"),
    }
    for campo, valor in posibles.items():
        if valor is not None and hasattr(mensaje, campo):
            setattr(mensaje, campo, valor)

    sobre = c.empaquetar(mensaje, correlation_id=args.correlation_id,
                         service_name=EMISORES[args.tipo])
    crudo = sobre.a_bytes()
    clave = mensaje.clave_particion()

    print(f"topico  {mensaje.TOPICO}")
    print(f"clave   {clave}")
    print(f"emisor  {sobre.service_name}")
    print(json.dumps(sobre.a_dict(), indent=2, ensure_ascii=False, default=str))

    if args.solo_mostrar:
        return 0

    # Warn y no Info: por defecto el cliente nativo escupe ~30 lineas por
    # conexion y sepulta la salida util.
    cliente = pulsar.Client(broker_url(),
                            logger=pulsar.ConsoleLogger(pulsar.LoggerLevel.Warn),
                            **opciones_cliente())
    try:
        productor = cliente.create_producer(mensaje.TOPICO, schema=pulsar.schema.BytesSchema())
        for i in range(args.duplicar):
            # El MISMO sobre, con el MISMO id, N veces: es exactamente lo que
            # hace Pulsar al reentregar, y lo que mensajes_procesados atrapa.
            productor.send(crudo, partition_key=clave)
            print(f"  -> publicado {i + 1}/{args.duplicar}  id={sobre.id}")
        productor.flush()
    finally:
        cliente.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
