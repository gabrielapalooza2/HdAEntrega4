"""Configuracion, toda por variables de entorno.

NADA de esto esta escrito en el codigo a proposito: es lo que permite que el
mismo artefacto corra en Docker Compose local y en GCP sin recompilar. Quien
despliega cambia variables, no fuentes.
"""

import os

PULSAR_URL = os.getenv("PULSAR_URL", "pulsar://broker:6650")
TENANT = os.getenv("PULSAR_TENANT", "hda")
NAMESPACE = os.getenv("PULSAR_NAMESPACE", "poc")

SERVICE_NAME = os.getenv("SERVICE_NAME", "bff")
CONTRATOS_DIR = os.getenv("CONTRATOS_DIR", "/app/contratos")
PUERTO = int(os.getenv("PORT", "8080"))

# Cuantos segundos espera el arranque a que el broker este disponible antes de
# rendirse. En GCP el broker puede tardar mas que en local.
ESPERA_BROKER_SEGUNDOS = int(os.getenv("ESPERA_BROKER_SEGUNDOS", "60"))

# Si es "false", la aplicacion arranca sin productores ni consumidores. Lo usan
# las pruebas, que no necesitan un broker vivo.
CONECTAR_A_PULSAR = os.getenv("CONECTAR_A_PULSAR", "true").lower() == "true"


def topico(nombre: str) -> str:
    """`cmd.trabajos` -> `persistent://hda/poc/cmd.trabajos`."""
    return f"persistent://{TENANT}/{NAMESPACE}/{nombre}"


# ── Tópicos que el BFF USA ───────────────────────────────────────────────────
# Publica comandos. NUNCA publica eventos: los eventos los emite el servicio
# dueño de la agregación correspondiente, no la capa de entrada.
CMD_PARTNERS = topico("cmd.partners")
CMD_PROVEEDORES = topico("cmd.proveedores")
CMD_TRABAJOS = topico("cmd.trabajos")

# `cmd.emparejamiento` existe en el contrato pero NADIE lo consume: Emparejamiento
# reacciona a `TrabajoCreado` en `evt.trabajos`. El BFF no publica ahi a proposito.

# Consume eventos para mantener su proyeccion de lectura.
EVT_PARTNERS = topico("evt.partners")
EVT_PROVEEDORES = topico("evt.proveedores")
EVT_TRABAJOS = topico("evt.trabajos")
EVT_ASIGNACIONES = topico("evt.asignaciones")
