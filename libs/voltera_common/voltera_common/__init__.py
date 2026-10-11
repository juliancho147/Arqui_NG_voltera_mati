"""voltera_common: contratos de eventos (CloudEvents), publicador al mesh, correlacion y fallos inyectados."""
from .correlation import CICLO_SENTINEL, Correlation, correlation_from, new_event_id
from .events import (
    EVENT_DATA_MODELS,
    EVENT_TYPES,
    CloudEvent,
    event_name_from_type,
    make_event,
    parse_cloudevent,
)
from .faults import InjectedFault, maybe_fail
from .observability import CloudWatchSink, EmfAggregator, aggregator_from_env, emit_metric, log_json
from .publisher import (
    DomainEventPublisher,
    InMemoryBackend,
    KafkaBackend,
    MeshBackend,
    NoopBackend,
    PublishError,
    backend_from_env,
    publisher_from_env,
)

__all__ = [
    "CloudWatchSink", "EmfAggregator", "aggregator_from_env", "emit_metric", "log_json",
    "CICLO_SENTINEL", "Correlation", "correlation_from", "new_event_id",
    "EVENT_DATA_MODELS", "EVENT_TYPES", "CloudEvent", "event_name_from_type", "make_event", "parse_cloudevent",
    "InjectedFault", "maybe_fail",
    "DomainEventPublisher", "InMemoryBackend", "KafkaBackend", "MeshBackend", "NoopBackend",
    "PublishError", "backend_from_env", "publisher_from_env",
]
