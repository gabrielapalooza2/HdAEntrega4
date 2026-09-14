from __future__ import annotations

import json
import logging
import time

import httpx

log = logging.getLogger("emparejamiento.pulsar_admin")

TENANT = "hda"
NAMESPACE = "hda/poc"
CLUSTER = "standalone"


def esperar_admin(admin_url: str, intentos: int = 60, pausa: float = 2.0) -> None:
    url = admin_url.rstrip("/") + "/admin/v2/brokers/health"
    ultimo = None
    for _ in range(intentos):
        try:
            r = httpx.get(url, timeout=5.0)
            if r.status_code < 500:
                log.info("Pulsar admin listo (%s)", r.status_code)
                return
            ultimo = r.status_code
        except Exception as exc:
            ultimo = exc
        time.sleep(pausa)
    raise RuntimeError(f"Pulsar admin no respondió: {ultimo}")


def bootstrap_pulsar(admin_url: str) -> None:
    base = admin_url.rstrip("/")
    with httpx.Client(base_url=base, timeout=20.0) as c:
        r = c.put(
            f"/admin/v2/tenants/{TENANT}",
            json={"adminRoles": ["admin"], "allowedClusters": [CLUSTER]},
        )
        log.info("tenant %s -> %s", TENANT, r.status_code)

        r = c.put(f"/admin/v2/namespaces/{NAMESPACE}")
        log.info("namespace %s -> %s", NAMESPACE, r.status_code)

        r = c.post(
            f"/admin/v2/namespaces/{NAMESPACE}/retention",
            json={"retentionTimeInMinutes": -1, "retentionSizeInMB": -1},
        )
        log.info("retention -> %s", r.status_code)

        r = c.put(
            f"/admin/v2/namespaces/{NAMESPACE}/compactionThreshold",
            content=str(10 * 1024 * 1024),
            headers={"Content-Type": "application/json"},
        )
        log.info("compactionThreshold -> %s", r.status_code)

        r = c.put(
            f"/admin/v2/namespaces/{NAMESPACE}/schemaCompatibilityStrategy",
            content=json.dumps("BACKWARD"),
            headers={"Content-Type": "application/json"},
        )
        log.info("schemaCompatibility BACKWARD -> %s", r.status_code)

        r = c.post(
            f"/admin/v2/namespaces/{NAMESPACE}/isAllowAutoUpdateSchema",
            content="true",
            headers={"Content-Type": "application/json"},
        )
        log.info("isAllowAutoUpdateSchema -> %s", r.status_code)

        for topic, partitions in (
            ("persistent://hda/poc/cmd.trabajos", 3),
            ("persistent://hda/poc/cmd.partners", 1),
            ("persistent://hda/poc/cmd.proveedores", 1),
            ("persistent://hda/poc/cmd.emparejamiento", 3),
            ("persistent://hda/poc/evt.trabajos", 3),
            ("persistent://hda/poc/evt.asignaciones", 3),
        ):
            tenant_ns_topic = topic.replace("persistent://", "")
            r = c.put(
                f"/admin/v2/persistent/{tenant_ns_topic}/partitions",
                content=str(partitions),
                headers={"Content-Type": "application/json"},
            )
            log.info("partitioned %s p=%s -> %s", topic, partitions, r.status_code)

        for topic in (
            "persistent://hda/poc/evt.partners",
            "persistent://hda/poc/evt.proveedores",
        ):
            tenant_ns_topic = topic.replace("persistent://", "")
            r = c.put(f"/admin/v2/persistent/{tenant_ns_topic}")
            log.info("topic %s -> %s", topic, r.status_code)


def registrar_esquema(admin_url: str, topic: str, avsc: dict) -> None:
    tenant_ns_topic = topic.replace("persistent://", "")
    body = {"type": "AVRO", "schema": json.dumps(avsc), "properties": {}}
    url = f"{admin_url.rstrip('/')}/admin/v2/schemas/{tenant_ns_topic}/schema"
    try:
        r = httpx.post(url, json=body, timeout=15.0)
        log.info("schema %s -> %s %s", topic, r.status_code, r.text[:200])
    except Exception as exc:
        log.warning("no se pudo registrar schema de %s: %s", topic, exc)
