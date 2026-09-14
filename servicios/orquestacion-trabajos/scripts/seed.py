#!/usr/bin/env python3
"""Siembra reglas de partner para la demo.

PUBLICA en evt.partners; no hace INSERT en la base. Es deliberado: sembrar por
SQL saltaria justamente el camino que hay que demostrar -que la proyeccion se
alimenta de eventos- y ademas dejaria la base y el topico desincronizados, de
modo que un reinicio del servicio perderia la siembra.

Las tres reglas estan elegidas para que cada una demuestre algo:

  SEGUROS_ALFA      cubre PLOMERIA         -> el camino feliz
  SEGUROS_BETA      NO cubre PLOMERIA      -> rechazo por categoria
  ASISTENCIA_GAMMA  SLA de 1 minuto        -> vencimiento y barrido de SLA
  PARTNER_DORMIDO   activo = false         -> rechazo por partner inactivo
"""
import argparse
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pulsar

from orquestacion.config import broker_url
from orquestacion.mensajeria import contratos as c

REGLAS = [
    c.ReglaDePartnerActualizada(
        partner_id="SEGUROS_ALFA", regla_version=1, sla_minutos=120, activo=True,
        categorias_cubiertas=["PLOMERIA", "ELECTRICIDAD", "CERRAJERIA"],
        monto_max=Decimal("500000"), moneda="COP"),

    # La importante para la demo de rechazo: NO cubre PLOMERIA.
    c.ReglaDePartnerActualizada(
        partner_id="SEGUROS_BETA", regla_version=1, sla_minutos=120, activo=True,
        categorias_cubiertas=["ELECTRICIDAD", "CERRAJERIA"],
        monto_max=Decimal("300000"), moneda="COP"),

    # SLA de 1 minuto: con esta se demuestra el barrido sin esperar dos horas.
    c.ReglaDePartnerActualizada(
        partner_id="ASISTENCIA_GAMMA", regla_version=1, sla_minutos=1, activo=True,
        categorias_cubiertas=["PLOMERIA"],
        monto_max=Decimal("100000"), moneda="COP"),

    c.ReglaDePartnerActualizada(
        partner_id="PARTNER_DORMIDO", regla_version=1, sla_minutos=60, activo=False,
        categorias_cubiertas=["PLOMERIA"],
        monto_max=None, moneda="COP"),
]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--solo-mostrar", action="store_true")
    args = p.parse_args()

    cliente = None
    if not args.solo_mostrar:
        cliente = pulsar.Client(broker_url(),
                                logger=pulsar.ConsoleLogger(pulsar.LoggerLevel.Warn))
        productor = cliente.create_producer(c.TOPICO_EVT_PARTNERS,
                                            schema=pulsar.schema.BytesSchema())
    try:
        for regla in REGLAS:
            # service_name AJENO: si firmaramos como orquestacion-trabajos, el
            # filtro anti-ciclo del consumidor descartaria la siembra.
            sobre = c.empaquetar(regla, service_name="motor-reglas-partner")
            estado = "activo" if regla.activo else "INACTIVO"
            print(f"  {regla.partner_id:18s} v{regla.regla_version} "
                  f"sla={regla.sla_minutos:>3}min {estado:8s} "
                  f"cubre={regla.categorias_cubiertas}")
            if cliente:
                # La clave es el partner_id: fija la particion Y es la clave de
                # compactacion, que es lo que deja reconstruir la proyeccion.
                productor.send(sobre.a_bytes(), partition_key=regla.clave_particion())
        if cliente:
            productor.flush()
            print(f"\n{len(REGLAS)} reglas publicadas en {c.TOPICO_EVT_PARTNERS}")
    finally:
        if cliente:
            cliente.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
