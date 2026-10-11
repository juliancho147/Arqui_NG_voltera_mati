"""Observabilidad sin dependencias: metricas EMF y logs JSON por stdout (Lambda y contenedor).

Namespace Voltera/Exp2 (POWERTOOLS_METRICS_NAMESPACE), dimension `service`.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from typing import Callable

DEFAULT_NAMESPACE = "Voltera/Exp2"


def namespace() -> str:
    return os.environ.get("POWERTOOLS_METRICS_NAMESPACE", DEFAULT_NAMESPACE)


def log_json(level: str, message: str, service: str = "", **fields) -> None:
    rec = {"level": level, "message": message, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    if service:
        rec["service"] = service
    rec.update(fields)
    sys.stdout.write(json.dumps(rec, default=str) + "\n")
    sys.stdout.flush()


def emf_line(service: str, metrics: list[tuple[str, float, str]], extra_dims: dict[str, str] | None = None, ns: str | None = None) -> str:
    dims = {"service": service, **(extra_dims or {})}
    doc = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [{
                "Namespace": ns or namespace(),
                "Dimensions": [list(dims)],
                "Metrics": [{"Name": n, "Unit": u} for n, _, u in metrics],
            }],
        },
        **dims,
        **{n: v for n, v, _ in metrics},
    }
    return json.dumps(doc)


def emit_metric(service: str, name: str, value: float = 1, unit: str = "Count", extra_dims: dict[str, str] | None = None) -> None:
    """Emite una metrica EMF inmediatamente (una linea por stdout)."""
    sys.stdout.write(emf_line(service, [(name, value, unit)], extra_dims) + "\n")
    sys.stdout.flush()


MAX_METRICS_PER_CALL = 1000  # limite de put_metric_data


class CloudWatchSink:
    """Publica directo con cloudwatch.put_metric_data (METRICS_BACKEND=cloudwatch). Nunca lanza: loguea y cuenta fallos."""

    def __init__(self, namespace_: str | None = None, client=None, region: str | None = None, max_per_call: int = MAX_METRICS_PER_CALL):
        self.namespace = namespace_ or os.environ.get("CLOUDWATCH_NAMESPACE") or namespace()
        self.max_per_call = max_per_call
        self.failures = 0
        self.calls = 0
        self._client = client
        self._region = region

    @property
    def client(self):
        if self._client is None:
            import boto3
            from botocore.config import Config

            self._client = boto3.client(
                "cloudwatch", region_name=self._region,
                config=Config(connect_timeout=3, read_timeout=5, retries={"max_attempts": 2, "mode": "standard"}),
            )
        return self._client

    @staticmethod
    def _datum(service: str, e: dict, ts) -> dict:
        dims = [{"Name": "service", "Value": service}] + [{"Name": k, "Value": str(v)} for k, v in e["dims"]]
        d = {"MetricName": e["name"], "Dimensions": dims, "Unit": e["unit"], "Timestamp": ts}
        if e["unit"] == "Count":
            d["Value"] = e["sum"]
        else:
            d["StatisticValues"] = {"SampleCount": e["count"], "Sum": e["sum"], "Minimum": e["min"], "Maximum": e["max"]}
        return d

    def send(self, service: str, entries: list[dict]) -> bool:
        import datetime as _dt

        ts = _dt.datetime.now(_dt.timezone.utc)
        data = [self._datum(service, e, ts) for e in entries]
        ok = True
        for i in range(0, len(data), self.max_per_call):
            chunk = data[i:i + self.max_per_call]
            try:
                self.client.put_metric_data(Namespace=self.namespace, MetricData=chunk)
                self.calls += 1
            except Exception as exc:  # no bloquear el consumo
                ok = False
                self.failures += 1
                log_json("ERROR", "fallo put_metric_data", service, error=str(exc), metricas=len(chunk), fallosAcumulados=self.failures)
        return ok


class EmfAggregator:
    """Acumula metricas (suma/conteo/min/max por nombre+dimensiones) y las vuelca periodicamente (OBS-1).

    Sin sink: lineas EMF por stdout (Lambda / Container Insights). Con sink (CloudWatchSink): put_metric_data directo.
    """

    def __init__(self, service: str, interval: float = 10.0, writer: Callable[[str], None] | None = None, sink: CloudWatchSink | None = None):
        self.service, self.interval, self.sink = service, interval, sink
        self._writer = writer or (lambda line: (sys.stdout.write(line + "\n"), sys.stdout.flush()))
        self._lock = threading.Lock()
        self._acc: dict[tuple, list] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.pre_flush: Callable[[], None] | None = None  # hook (HealthCheckOk, KafkaConsumerLag...)

    def add(self, name: str, value: float = 1, unit: str = "Count", dims: dict[str, str] | None = None) -> None:
        key = (name, unit, tuple(sorted((dims or {}).items())))
        with self._lock:
            slot = self._acc.get(key)
            if slot is None:
                self._acc[key] = [value, 1, value, value]
            else:
                slot[0] += value
                slot[1] += 1
                slot[2] = min(slot[2], value)
                slot[3] = max(slot[3], value)

    def flush(self) -> int:
        if self.pre_flush:
            try:
                self.pre_flush()
            except Exception as exc:
                log_json("ERROR", "pre_flush fallo", self.service, error=str(exc))
        with self._lock:
            acc, self._acc = self._acc, {}
        if not acc:
            return 0
        if self.sink is not None:
            entries = [{"name": n, "unit": u, "dims": d, "sum": v[0], "count": v[1], "min": v[2], "max": v[3]} for (n, u, d), v in acc.items()]
            try:
                self.sink.send(self.service, entries)
            except Exception as exc:
                log_json("ERROR", "fallo volcando metricas", self.service, error=str(exc))
            return len(acc)
        groups: dict[tuple, list] = {}
        for (name, unit, dims), (total, count, _mn, _mx) in acc.items():
            groups.setdefault(dims, []).append((name, total if unit == "Count" else total / count, unit))
        for dims, ms in groups.items():
            self._writer(emf_line(self.service, ms, dict(dims)))
        return len(acc)

    def start(self) -> None:
        def loop():
            while not self._stop.wait(self.interval):
                self.flush()
        self._thread = threading.Thread(target=loop, name="emf-flush", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self.flush()


def aggregator_from_env(service: str, interval: float | None = None) -> EmfAggregator:
    """METRICS_BACKEND=emf (defecto, stdout) | cloudwatch (put_metric_data; CLOUDWATCH_NAMESPACE, defecto Voltera/Exp2)."""
    interval = interval if interval is not None else float(os.environ.get("METRICS_FLUSH_SECONDS", "10"))
    sink = CloudWatchSink() if os.environ.get("METRICS_BACKEND", "emf").lower() == "cloudwatch" else None
    return EmfAggregator(service, interval=interval, sink=sink)
