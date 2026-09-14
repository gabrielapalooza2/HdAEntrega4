"""Punto de entrada para desarrollo local: `python -m motor_reglas.main`."""

from motor_reglas import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
