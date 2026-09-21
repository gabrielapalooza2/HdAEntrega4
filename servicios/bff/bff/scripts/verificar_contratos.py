#!/usr/bin/env python3
"""Comprueba que el BFF puede hablar el contrato del equipo.

El BFF no COPIA los contratos: los lee de `contratos/esquemas/`. Eso elimina el
riesgo de una copia desactualizada, pero introduce otro: que un .avsc cambie de
forma y el BFF se entere en produccion. Este script lo verifica antes.

Tres comprobaciones:

  1. Existe el .avsc de cada uno de los 14 tipos que el BFF produce o consume.
  2. Los ocho campos del sobre CloudEvents son identicos y estan en el mismo
     orden en todos. Si no, el truco del prefijo posicional deja de funcionar y
     el BFF no podria saber que tipo trae un mensaje antes de decodificarlo.
  3. Cada tipo sobrevive un ida y vuelta: se codifica y se vuelve a leer.

    python scripts/verificar_contratos.py

Salida 0 = todo bien. Salida 1 = hay un problema, y dice cual.
"""

import json
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "src"))
os.environ.setdefault(
    "CONTRATOS_DIR", os.path.normpath(os.path.join(AQUI, "..", "..", "..", "contratos"))
)

from bff.esquemas import avro                              # noqa: E402

SOBRE_ESPERADO = ["id", "time", "ingestion", "specversion", "type",
                  "datacontenttype", "service_name", "correlation_id"]


def main() -> int:
    print(f"contratos en: {avro.CONTRATOS_DIR}\n")
    fallos = 0

    for tipo in avro.CARPETA_DE_TIPO:
        ruta = avro.ruta_de(tipo)
        if not ruta.is_file():
            print(f"FALTA        {tipo}  ({ruta})")
            fallos += 1
            continue

        crudo = json.loads(ruta.read_text(encoding="utf-8"))
        nombres = [c["name"] for c in crudo["fields"]]

        if nombres[:8] != SOBRE_ESPERADO:
            print(f"SOBRE MALO   {tipo}")
            print(f"               esperaba {SOBRE_ESPERADO}")
            print(f"               encontro {nombres[:8]}")
            fallos += 1
            continue

        if nombres[8:] != ["data"]:
            print(f"FORMA RARA   {tipo}: despues del sobre hay {nombres[8:]}, no solo 'data'")
            fallos += 1
            continue

        try:
            sobre = {
                "id": "x", "time": 0, "ingestion": 0, "specversion": "v1",
                "type": tipo, "datacontenttype": "AVRO", "service_name": "bff",
                "correlation_id": "x", "data": avro.completar(tipo, {}),
            }
            vuelta = avro.decodificar(avro.codificar(sobre))
            if not vuelta or vuelta.get("type") != tipo:
                raise ValueError("el ida y vuelta no devolvio el mismo tipo")
        except Exception as e:                             # noqa: BLE001
            print(f"NO CODIFICA  {tipo}: {e}")
            fallos += 1
            continue

        print(f"OK           {tipo}")

    print()
    if fallos:
        print(f"{fallos} problema(s). El BFF no puede hablar con el bus asi.")
        return 1
    print(f"Los {len(avro.CARPETA_DE_TIPO)} contratos del BFF estan bien.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
