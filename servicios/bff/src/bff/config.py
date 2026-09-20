import os

PULSAR_URL = os.getenv("PULSAR_URL", "pulsar://broker:6650")
TENANT = os.getenv("PULSAR_TENANT", "hda")
NAMESPACE = os.getenv("PULSAR_NAMESPACE", "poc")

SERVICE_NAME = os.getenv("SERVICE_NAME", "bff")
CONTRATOS_DIR = os.getenv("CONTRATOS_DIR", "/app/contratos")
PUERTO = int(os.getenv("PORT", "8080"))


ESPERA_BROKER_SEGUNDOS = int(os.getenv("ESPERA_BROKER_SEGUNDOS", "60"))


CONECTAR_A_PULSAR = os.getenv("CONECTAR_A_PULSAR", "true").lower() == "true"


def topico(nombre: str) -> str:
    """`cmd.trabajos` -> `persistent://hda/poc/cmd.trabajos`."""
    return f"persistent://{TENANT}/{NAMESPACE}/{nombre}"



CMD_PARTNERS = topico("cmd.partners")
CMD_PROVEEDORES = topico("cmd.proveedores")
CMD_TRABAJOS = topico("cmd.trabajos")


EVT_PARTNERS = topico("evt.partners")
EVT_PROVEEDORES = topico("evt.proveedores")
EVT_TRABAJOS = topico("evt.trabajos")
EVT_ASIGNACIONES = topico("evt.asignaciones")
