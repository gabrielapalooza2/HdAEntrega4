import datetime
import os
import time

EPOCH = datetime.datetime(1970, 1, 1)


def time_millis() -> int:
    return int(time.time() * 1000)


def millis_a_datetime(millis: int) -> datetime.datetime:
    return datetime.datetime.utcfromtimestamp(millis / 1000.0)


def datetime_a_millis(dt: datetime.datetime) -> int:
    return int((dt - EPOCH).total_seconds() * 1000)


def broker_host() -> str:
    return os.getenv("PULSAR_ADDRESS", default="localhost")


def broker_url() -> str:
    return f"pulsar://{broker_host()}:6650"


def service_name() -> str:
    return os.getenv("SERVICE_NAME", default="motor-reglas-partner")
