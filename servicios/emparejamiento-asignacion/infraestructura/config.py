from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _default_contratos() -> Path:
    env = os.environ.get("CONTRATOS_DIR")
    if env:
        return Path(env)
    modulo = Path(__file__).resolve().parents[1]
    candidatos = [
        modulo / "contratos",
        Path("/contratos"),
        Path("/app/contratos"),
    ]
    for c in candidatos:
        if c.is_dir():
            return c
    return modulo / "contratos"


@dataclass(frozen=True)
class Settings:
    pulsar_url: str
    pulsar_admin_url: str
    database_dsn: str
    contratos_dir: Path
    http_host: str
    http_port: int
    service_name: str

    @staticmethod
    def load() -> "Settings":
        return Settings(
            pulsar_url=os.environ.get("PULSAR_URL", "pulsar://localhost:6650"),
            pulsar_admin_url=os.environ.get("PULSAR_ADMIN_URL", "http://localhost:8080"),
            database_dsn=os.environ.get(
                "DATABASE_DSN",
                "postgresql+psycopg://emparejamiento:emparejamiento@localhost:5432/emparejamiento",
            ),
            contratos_dir=_default_contratos(),
            http_host=os.environ.get("HTTP_HOST", "0.0.0.0"),
            http_port=int(os.environ.get("HTTP_PORT", "8000")),
            service_name="emparejamiento-asignacion",
        )
