from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_no_consume_asignar_proveedor():
    texto = (ROOT / "infraestructura" / "mensajeria" / "pulsar_io.py").read_text(encoding="utf-8")
    assert "cmd.emparejamiento" not in texto
    assert "AsignarProveedor" not in texto
    servicios = (ROOT / "aplicacion" / "servicios.py").read_text(encoding="utf-8")
    assert "AsignarProveedor" not in servicios
