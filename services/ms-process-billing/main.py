"""Punto de entrada de ms-process-billing (contenedor en EKS, escalado por KEDA sobre el lag del grupo base)."""
from __future__ import annotations

import os
import signal
import threading

import boto3
from aws_lambda_powertools import Logger

from config import Settings
from consumer import run_consumer
from health import make_server, serve_in_thread
from ingest import IngestProcessor
from state import CycleState
from botocore.config import Config

from ingest import report_timing
from lag import lag_reporter
from voltera_common import DomainEventPublisher, KafkaBackend, aggregator_from_env, log_json

logger = Logger(service="ms-process-billing")


def build_consumer(settings: Settings, group: str, topic: str):
    from confluent_kafka import Consumer

    c = Consumer({
        "bootstrap.servers": settings.kafka_bootstrap,
        "group.id": group,                      # estable entre replicas/reinicios (requisito de KEDA)
        "enable.auto.commit": False,            # commit manual DESPUES de publicar en SQS
        "auto.offset.reset": "earliest",
        "partition.assignment.strategy": "cooperative-sticky",
        "max.poll.interval.ms": 300000,
        "session.timeout.ms": 30000,
    })
    def on_assign(cons, parts):
        log_json("INFO", "particiones asignadas", settings.service, grupo=group, particiones=[p.partition for p in parts])

    def on_revoke(cons, parts):
        log_json("INFO", "particiones revocadas", settings.service, grupo=group, particiones=[p.partition for p in parts])

    c.subscribe([topic], on_assign=on_assign, on_revoke=on_revoke)
    return c


def main() -> None:
    s = Settings.from_env()
    metrics = aggregator_from_env(s.service)  # METRICS_BACKEND=emf|cloudwatch, METRICS_FLUSH_SECONDS
    stop = threading.Event()
    cfg = Config(max_pool_connections=10, connect_timeout=3, read_timeout=10, retries={"max_attempts": 3, "mode": "standard"})
    table = boto3.resource("dynamodb", config=cfg).Table(s.table)
    sqs = boto3.client("sqs", config=cfg)
    publisher = DomainEventPublisher(s.service, KafkaBackend(s.kafka_bootstrap, client_id=s.service), topic=s.topic_eventos, best_effort=False)

    ingest = IngestProcessor(s, table, sqs, stop=stop, metrics=metrics, logger=logger)
    state = CycleState(s, table, publisher, logger=logger, metrics=metrics)

    pod = os.environ.get("HOSTNAME", "local")
    ingreso_consumer = build_consumer(s, s.consumer_group, s.topic_ingreso)
    lag_hook = lag_reporter(ingreso_consumer, metrics, s.service, s.topic_ingreso, pod)

    def on_done(poll_ms: float, handle_ms: float, commit_ms: float) -> None:
        report_timing(ingest, metrics, logger, poll_ms, handle_ms, commit_ms)

    threads = [
        threading.Thread(target=run_consumer, name="ingreso", args=(ingreso_consumer, ingest.handle, stop, s.poll_timeout),
                         kwargs={"on_done": on_done}),
        threading.Thread(target=run_consumer, name="estado", args=(build_consumer(s, s.group_eventos, s.topic_eventos), state.handle, stop, s.poll_timeout, state.sweep_timeouts)),
    ]

    def check() -> dict:
        alive = {t.name: t.is_alive() for t in threads}
        return {"ok": all(alive.values()) and not stop.is_set(), "hilos": alive, **ingest.counters,
                "metricasFallidas": getattr(metrics.sink, "failures", 0)}

    # OBS-6: HealthCheckOk (1/0) en cada volcado = referencia de "servicio en linea".
    def pre_flush() -> None:
        metrics.add("HealthCheckOk", 1 if check()["ok"] else 0, dims={"pod": pod})
        lag_hook()  # KafkaConsumerLag (service+topic) de las particiones asignadas a este pod

    metrics.pre_flush = pre_flush
    metrics.start()  # OBS-1: volcado EMF periodico durante la corrida, no solo al apagar

    server = make_server(s.health_port, check)
    serve_in_thread(server)

    def on_term(signum, frame):
        logger.info("senal de apagado: terminando el mensaje en curso y cerrando consumidores")
        stop.set()

    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGINT, on_term)
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    server.shutdown()
    metrics.stop()
    logger.info("apagado limpio", extra=ingest.counters)


if __name__ == "__main__":
    main()
