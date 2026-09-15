#!/usr/bin/env python3
"""Semilla: registra los partners existentes. Se corre UNA VEZ, antes de cualquier demo.

Es el equivalente a la realidad del negocio: los convenios se firman en el area
comercial a lo largo de anios, no durante un pico de demanda. Separar la semilla de
la carga es lo que evita confundir un acto administrativo con el volumen operativo.
"""
import argparse
import json
import random
import urllib.error
import urllib.request

CATEGORIAS = ["PLOMERIA", "ELECTRICIDAD", "CARPINTERIA", "PINTURA", "CERRAJERIA"]
TIPOS = ["ASEGURADORA", "BANCO", "COMERCIO"]


def registrar(api: str, i: int) -> str | None:
    cuerpo = {
        "nombre": f"Partner {i:03d}",
        "tipo_partner": random.choice(TIPOS),
        "convenio_numero": f"CONV-2026-{i:03d}",
        "vigencia_desde": "2026-01-01T00:00:00Z",
        "porcentaje_comision": round(random.uniform(8, 18), 1),
        "moneda_tarifa": "COP",
        "regla": {
            "cobertura_contratada": random.sample(CATEGORIAS, k=random.randint(1, 4)),
            "sla_minutos": random.choice([60, 90, 120, 240]),
            "monto_maximo_sin_aprobacion": {
                "monto": random.choice([20_000_00, 50_000_00, 100_000_00]), "moneda": "COP"},
            "pasos_de_aprobacion": random.choice([[], ["ANALISTA_SINIESTROS"]]),
            "red_homologada": [],
        },
    }
    req = urllib.request.Request(
        f"{api}/partners", data=json.dumps(cuerpo).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())["id"]
    except urllib.error.HTTPError as e:
        print(f"   error registrando partner {i}: {e.read().decode()[:120]}")
        return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cantidad", type=int, default=30)
    p.add_argument("--api", default="http://localhost:5002")
    args = p.parse_args()

    creados = [pid for i in range(1, args.cantidad + 1) if (pid := registrar(args.api, i))]
    print(f"\n{len(creados)} partners registrados.")
    print("Cada uno publico un ReglaDePartnerActualizada con carga de estado.")
    print("Los consumidores ya tienen la regla en su proyeccion ANTES de que llegue")
    print("el primer trabajo. Esa precondicion es lo que hace que el flujo de trabajos")
    print("nunca tenga que consultar a Motor reglas partner.")


if __name__ == "__main__":
    main()
