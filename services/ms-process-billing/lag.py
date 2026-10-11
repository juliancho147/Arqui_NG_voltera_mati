"""Lag del consumidor calculado en la app (KafkaConsumerLag), solo de las particiones ASIGNADAS a este pod.

lag = high watermark - offset confirmado (committed), igual que mide KEDA/Kafka. Si aun no hay commit (-1001)
se usa la posicion y, si tampoco, el low watermark. Cada pod reporta lo suyo; el dashboard suma (Sum) entre pods.
"""
from __future__ import annotations

from voltera_common import log_json


def compute_lag(consumer, timeout: float = 2.0) -> tuple[int, int]:
    """Devuelve (lag_total, particiones_asignadas). (0, 0) si no tiene particiones."""
    assignment = consumer.assignment()
    if not assignment:
        return 0, 0
    total = 0
    committed = {(c.topic, c.partition): c.offset for c in consumer.committed(assignment, timeout=timeout)}
    for tp in assignment:
        low, high = consumer.get_watermark_offsets(tp, timeout=timeout)
        off = committed.get((tp.topic, tp.partition), -1001)
        if off is None or off < 0:
            pos = consumer.position([tp])[0].offset
            off = pos if pos is not None and pos >= 0 else low
        total += max(0, high - off)
    return total, len(assignment)


def lag_reporter(consumer, metrics, service: str, topic: str, pod: str):
    """Hook para EmfAggregator.pre_flush: emite KafkaConsumerLag (service+topic) y ParticionesAsignadas (service+pod)."""
    def report() -> None:
        try:
            lag, parts = compute_lag(consumer)
        except Exception as exc:
            log_json("ERROR", "no se pudo calcular el lag", service, error=str(exc))
            return
        metrics.add("KafkaConsumerLag", lag, "Count", dims={"topic": topic})
        metrics.add("ParticionesAsignadas", parts, "Count", dims={"pod": pod})
    return report
