import os

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

DB_USERNAME = os.getenv("DB_USERNAME", default="partners")
DB_PASSWORD = os.getenv("DB_PASSWORD", default="partners")
DB_HOSTNAME = os.getenv("DB_HOSTNAME", default="localhost")
DB_PORT = os.getenv("DB_PORT", default="5432")
DB_NAME = os.getenv("DB_NAME", default="partners")


def database_connection(config: dict) -> str:
    if config.get("TESTING", False):
        return "sqlite:///:memory:"
    return (
        f"postgresql+psycopg2://{DB_USERNAME}:{DB_PASSWORD}"
        f"@{DB_HOSTNAME}:{DB_PORT}/{DB_NAME}"
    )


def init_db(app):
    if "sqlalchemy" not in app.extensions:
        db.init_app(app)
