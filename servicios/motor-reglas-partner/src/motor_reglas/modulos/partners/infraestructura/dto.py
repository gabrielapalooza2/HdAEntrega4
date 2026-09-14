"""DTOs: el modelo ANÉMICO que toca la base de datos.

Están separados de las entidades de dominio a propósito. Si el agregado fuera
directamente la tabla, cualquier cambio del esquema de base de datos sería un
cambio del modelo de dominio, y al revés. El mapeador es el precio que se paga
por poder cambiar uno sin tocar el otro.
"""

from motor_reglas.config.db import db


class Partner(db.Model):
    __tablename__ = "partners"

    id = db.Column(db.String(40), primary_key=True)
    nombre = db.Column(db.String(200), nullable=False)
    tipo = db.Column(db.String(20), nullable=False)
    activo = db.Column(db.Boolean, nullable=False, default=True)

    # --- Convenio (entidad interna de la agregación) ---
    convenio_id = db.Column(db.String(40), nullable=False)
    convenio_numero = db.Column(db.String(60), nullable=False)
    vigencia_desde = db.Column(db.DateTime, nullable=False)
    vigencia_hasta = db.Column(db.DateTime, nullable=True)
    tarifa_comision = db.Column(db.Float, nullable=True)
    tarifa_moneda = db.Column(db.String(3), nullable=True)

    # --- ReglaDePartner (entidad interna de la agregación) ---
    regla_id = db.Column(db.String(40), nullable=True)
    regla_version = db.Column(db.Integer, nullable=False, default=0)
    sla_minutos = db.Column(db.Integer, nullable=True)
    monto_maximo_monto = db.Column(db.BigInteger, nullable=True)
    monto_maximo_moneda = db.Column(db.String(3), nullable=True)
    # JSON y no tablas hijas: siempre se leen completos y nunca se consultan por dentro
    cobertura = db.Column(db.JSON, nullable=False, default=list)
    pasos_aprobacion = db.Column(db.JSON, nullable=False, default=list)
    red_homologada = db.Column(db.JSON, nullable=False, default=list)

    fecha_creacion = db.Column(db.DateTime, nullable=False)
    fecha_actualizacion = db.Column(db.DateTime, nullable=False)


class Outbox(db.Model):
    """PATRÓN OUTBOX.

    El problema que resuelve: guardar en la base de datos y publicar en Pulsar son
    dos sistemas distintos y no hay transacción que abarque a los dos. Si se publica
    antes del commit, un rollback deja un evento mintiendo; si se publica después,
    una caída entre el commit y el publish pierde el evento para siempre.

    La solución: el evento se INSERTA en esta tabla dentro de la MISMA transacción
    que el cambio de dominio. Un relay aparte lo lee y lo publica. Si el relay se
    cae, el evento sigue ahí y se publica al reiniciar. Es lo que convierte
    "publicamos eventos" en "no perdemos eventos".
    """

    __tablename__ = "outbox"

    id = db.Column(db.String(40), primary_key=True)
    tipo = db.Column(db.String(80), nullable=False)
    topico = db.Column(db.String(120), nullable=False)
    clave = db.Column(db.String(80), nullable=False)   # clave de partición y compactación
    payload = db.Column(db.JSON, nullable=False)
    correlation_id = db.Column(db.String(40), nullable=False)
    publicado = db.Column(db.Boolean, nullable=False, default=False, index=True)
    fecha_creacion = db.Column(db.DateTime, nullable=False)
    fecha_publicacion = db.Column(db.DateTime, nullable=True)


class MensajeProcesado(db.Model):
    """IDEMPOTENCIA.

    Pulsar entrega AL MENOS UNA VEZ: un consumidor puede recibir el mismo mensaje
    dos veces si se cae antes de confirmarlo. Este registro se inserta en la misma
    transacción que el efecto de dominio; si el id ya está, el mensaje se confirma
    y se descarta sin repetir el efecto.
    """

    __tablename__ = "mensajes_procesados"

    mensaje_id = db.Column(db.String(40), primary_key=True)
    procesado_en = db.Column(db.DateTime, nullable=False)
