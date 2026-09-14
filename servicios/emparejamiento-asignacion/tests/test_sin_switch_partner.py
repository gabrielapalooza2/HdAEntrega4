from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = "partnerId" + " =="


def test_cero_condicionales_partnerId():
    hits = []
    for path in ROOT.rglob("*.py"):
        if ".venv" in path.parts or "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        if FORBIDDEN in text:
            hits.append(str(path.relative_to(ROOT)))
    assert hits == [], hits
