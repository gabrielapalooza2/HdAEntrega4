#!/usr/bin/env python3
"""Genera los .avsc a partir de los Records de Pulsar.

UNA SOLA FUENTE DE VERDAD: el esquema que se registra en el broker es el que
pulsar-client deriva de la clase Python. Los .avsc son un artefacto GENERADO, no
un documento que alguien mantiene a mano en paralelo -eso garantizaría que se
desincronizara-. Se versionan en el repo para poder revisar en un pull request
qué cambió en el contrato.

    python scripts/generar_avsc.py
    git diff contratos/   # el diff del contrato, revisable
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pulsar.schema import AvroSchema

from motor_reglas.modulos.partners.infraestructura.schema.v1.comandos import (
    ComandoActualizarReglaDePartner,
    ComandoRegistrarPartner,
)
from motor_reglas.modulos.partners.infraestructura.schema.v1.eventos import (
    EventoReglaDePartnerActualizada,
)

DESTINO = os.path.join(os.path.dirname(__file__), "..", "contratos")

CLASES = {
    "eventos-partner/ReglaDePartnerActualizada.avsc": EventoReglaDePartnerActualizada,
    "comandos-partner/RegistrarPartner.avsc": ComandoRegistrarPartner,
    "comandos-partner/ActualizarReglaDePartner.avsc": ComandoActualizarReglaDePartner,
}

for ruta, clase in CLASES.items():
    destino = os.path.join(DESTINO, ruta)
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    esquema = json.loads(AvroSchema(clase).schema_info().schema())
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(esquema, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"generado {ruta}")
