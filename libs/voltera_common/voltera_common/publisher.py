"""Publicador de eventos de dominio al Event Mesh (Kafka) con backend intercambiable.

Kafka: topico voltera.eventos, clave = facturaId, headers cicloId/facturaId. Backend en memoria para tests.
"""
from __future__ import annotations

import logging
import os
import time
import threading
from dataclasses import dataclass, field
from typing import Any, Protocol

from .events import CloudEvent, make_event, parse_cloudevent
from .observability import emit_metric, log_json

log = logging.getLogger("voltera.publisher")

DEFAULT_TOPIC_EVENTOS = "voltera.eventos"


class PublishError(RuntimeError):
    pass


class MeshBackend(Protocol):
    def send(self, topic: str, key: str, value: bytes, headers: dict[str, str]) -> None: ...
    def flush(self, timeout: float = 5.0) -> None: ...


@dataclass
class SentMessage:
    topic: str
    key: str
    value: bytes
    headers: dict[str, str]

    def event(self) -> CloudEvent:
        return parse_cloudevent(self.value)


@dataclass
class InMemoryBackend:
    """Backend de tests: guarda lo publicado."""
    messages: list[SentMessage] = field(default_factory=list)
    fail: bool = False

    def send(self, topic: str, key: str, value: bytes, headers: dict[str, str]) -> None:
        if self.fail:
            raise PublishError("backend en memoria configurado para fallar")
        self.messages.append(SentMessage(topic, key, value, dict(headers)))

    def flush(self, timeout: float = 5.0) -> None:
        return None

    def events(self, topic: str | None = None) -> list[CloudEvent]:
        return [m.event() for m in self.messages if topic is None or m.topic == topic]

    def names(self, topic: str | None = None) -> list[str]:
        return [e.name or e.type for e in self.events(topic)]


class NoopBackend:
    """Sin Kafka configurado: descarta (con log). Util en Lambdas sin KAFKA_BOOTSTRAP_SERVERS."""

    def send(self, topic: str, key: str, value: bytes, headers: dict[str, str]) -> None:
        log.warning("mesh sin configurar (KAFKA_BOOTSTRAP_SERVERS vacio): evento descartado key=%s", key)

    def flush(self, timeout: float = 5.0) -> None:
        return None


class KafkaBackend:
    """Productor confluent-kafka (idempotente, acks=all). Import perezoso para no exigir la lib en tests."""

    def __init__(self, bootstrap_servers: str, client_id: str = "voltera", extra: dict[str, Any] | None = None, producer: Any = None):
        if producer is None:
            from confluent_kafka import Producer  # import perezoso

            conf = {
                "bootstrap.servers": bootstrap_servers,
                "client.id": client_id,
                "acks": "all",
                "enable.idempotence": True,
                "linger.ms": 5,
                "message.timeout.ms": int(os.environ.get("KAFKA_MESSAGE_TIMEOUT_MS", "10000")),
                "socket.timeout.ms": 5000,
            }
            conf.update(extra or {})
            producer = Producer(conf)
        self._producer = producer
        self._errors: list[str] = []
        self._lock = threading.Lock()

    def _on_delivery(self, err: Any, msg: Any) -> None:
        if err is not None:
            with self._lock:
                self._errors.append(str(err))

    def send(self, topic: str, key: str, value: bytes, headers: dict[str, str]) -> None:
        try:
            self._producer.produce(
                topic,
                key=key.encode("utf-8"),
                value=value,
                headers=[(k, v.encode("utf-8")) for k, v in headers.items()],
                on_delivery=self._on_delivery,
            )
            self._producer.poll(0)
        except Exception as exc:
            raise PublishError(f"no se pudo encolar en Kafka: {exc}") from exc

    def flush(self, timeout: float = 5.0) -> None:
        remaining = self._producer.flush(timeout)
        with self._lock:
            errors, self._errors = self._errors, []
        if errors:
            raise PublishError(f"entrega fallida: {errors[0]}")
        if remaining:
            raise PublishError(f"{remaining} mensajes sin confirmar tras {timeout}s")


def backend_from_env(client_id: str = "voltera") -> MeshBackend:
    """MESH_BACKEND=memory|noop|kafka; por defecto kafka si hay KAFKA_BOOTSTRAP_SERVERS, si no noop."""
    kind = os.environ.get("MESH_BACKEND", "").lower()
    servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "").strip()
    if kind == "memory":
        return InMemoryBackend()
    if kind == "noop" or (not kind and not servers):
        return NoopBackend()
    if not servers:
        raise PublishError("MESH_BACKEND=kafka requiere KAFKA_BOOTSTRAP_SERVERS")
    return KafkaBackend(servers, client_id=client_id)


class DomainEventPublisher:
    """Publica eventos de dominio de un servicio al mesh.

    best_effort=True: un fallo del mesh se registra y se cuenta, pero no interrumpe el paso de negocio
    (Step Functions no debe reintentar/fallar por un problema de observabilidad). Con False, lanza PublishError.
    """

    def __init__(self, service: str, backend: MeshBackend, topic: str | None = None, best_effort: bool = True, flush_timeout: float = 5.0,
                 attempts: int | None = None, retry_delay: float = 0.3):
        self.service = service
        self.backend = backend
        self.topic = topic or os.environ.get("KAFKA_TOPIC_EVENTOS", DEFAULT_TOPIC_EVENTOS)
        self.best_effort = best_effort
        self.flush_timeout = flush_timeout
        self.failures = 0
        # Reintentos ante fallo transitorio del mesh. Seguro: el eventId es determinista y los consumidores son idempotentes.
        self.attempts = max(1, attempts if attempts is not None else int(os.environ.get("MESH_PUBLISH_ATTEMPTS", "3")))
        self.retry_delay = retry_delay

    def publish_event(self, event: CloudEvent, topic: str | None = None) -> bool:
        try:
            for intento in range(1, self.attempts + 1):
                try:
                    self.backend.send(topic or self.topic, event.facturaid, event.to_bytes(), event.headers())
                    self.backend.flush(self.flush_timeout)
                    break
                except Exception as exc:
                    if intento == self.attempts:
                        raise
                    log.warning("publicacion de %s fallo (intento %d/%d): %s", event.type, intento, self.attempts, exc)
                    time.sleep(self.retry_delay * intento)
            log_json("INFO", "evento publicado", self.service, tipo=event.name or event.type,
                     cicloId=event.cicloid, facturaId=event.facturaid, eventId=event.id)
            return True
        except Exception as exc:
            self.failures += 1
            log.error("fallo publicando %s al mesh: %s", event.type, exc)
            log_json("ERROR", "fallo publicando evento al mesh", self.service, tipo=event.name or event.type,
                     cicloId=event.cicloid, facturaId=event.facturaid, error=str(exc))
            emit_metric(self.service, "MeshPublishFailures")
            if self.best_effort:
                return False
            raise

    def publish(self, name: str, cicloId: str, facturaId: str, **data: Any) -> bool:
        ev = make_event(name, self.service, cicloId, facturaId, **data)
        return self.publish_event(ev)


def publisher_from_env(service: str, best_effort: bool = True) -> DomainEventPublisher:
    return DomainEventPublisher(service, backend_from_env(client_id=service), best_effort=best_effort)
