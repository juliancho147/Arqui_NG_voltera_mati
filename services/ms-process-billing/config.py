"""Configuracion por variables de entorno (contrato con k8s/apps/ms-process-billing.yaml.tftpl)."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Settings:
    kafka_bootstrap: str = ""
    topic_ingreso: str = "voltera.consumo-facturable-preparado"
    topic_eventos: str = "voltera.eventos"
    consumer_group: str = "ms-process-billing"
    sqs_queue_url: str = ""
    table: str = ""
    simulated_delay_seconds: float = 0.0
    health_port: int = 8080
    ciclo_timeout_seconds: int = 600
    dedup_ttl_seconds: int = 3 * 24 * 3600
    ttl_attr: str = "expiresAt"
    poll_timeout: float = 1.0
    service: str = "ms-process-billing"
    table_reconciliacion: str = ""   # idem-comprobante (solo lectura); vacio = reconciliacion desactivada
    reconcile_after_seconds: int = 45
    consumer_concurrency: int = 1

    @property
    def group_eventos(self) -> str:
        # Grupo propio para el estado del ciclo: no interfiere con el lag que mide KEDA sobre el grupo base.
        return f"{self.consumer_group}-eventos"

    @classmethod
    def from_env(cls) -> "Settings":
        e = os.environ
        return cls(
            kafka_bootstrap=e.get("KAFKA_BOOTSTRAP_SERVERS", ""),
            topic_ingreso=e.get("KAFKA_TOPIC_INGRESO", cls.topic_ingreso),
            topic_eventos=e.get("KAFKA_TOPIC_EVENTOS", cls.topic_eventos),
            consumer_group=e.get("KAFKA_CONSUMER_GROUP", cls.consumer_group),
            sqs_queue_url=e.get("SQS_QUEUE_URL", ""),
            table=e.get("TABLE_PROCESS_BILLING", ""),
            simulated_delay_seconds=float(e.get("SIMULATED_DELAY_SECONDS", "0") or 0),
            health_port=int(e.get("HEALTH_PORT", "8080")),
            ciclo_timeout_seconds=int(e.get("CICLO_TIMEOUT_SECONDS", "600")),
            ttl_attr=e.get("IDEMPOTENCY_TTL_ATTR", "expiresAt"),
            table_reconciliacion=e.get("TABLE_RECONCILIACION", ""),
            reconcile_after_seconds=int(e.get("RECONCILE_AFTER_SECONDS", "45") or 45),
            consumer_concurrency=max(1, int(e.get("CONSUMER_CONCURRENCY", "1") or 1)),
        )
