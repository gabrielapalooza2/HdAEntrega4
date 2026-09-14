from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROHIBIDO = {"pulsar", "sqlalchemy", "psycopg", "fastapi"}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    nombres = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                nombres.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            nombres.add(node.module.split(".")[0])
    return nombres


def test_domain_no_importa_pulsar_ni_sql():
    for path in (ROOT / "dominio").rglob("*.py"):
        hallados = _imports(path) & PROHIBIDO
        assert not hallados, f"{path} importa {hallados}"


def test_application_no_importa_pulsar_ni_sql():
    for path in (ROOT / "aplicacion").rglob("*.py"):
        hallados = _imports(path) & PROHIBIDO
        assert not hallados, f"{path} importa {hallados}"
