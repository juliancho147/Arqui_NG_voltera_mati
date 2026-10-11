"""Ingreso: ConsumoFacturablePreparado (Kafka) -> dedup en DynamoDB -> transaccion armada en SQS.

Dedup: PutItem condicional DEDUP#<facturaId> en estado PROCESANDO; tras publicar en SQS pasa a ENVIADO.
Si el pod muere entre ambos pasos, la reentrega ve PROCESANDO y vuelve a publicar (SQS at-least-once; ms-facturacion
es idempotente), asi no se pierde ninguna solicitud. ENVIADO = duplicado real: se descarta.
"""
from __future__ import annotations

import json
import os
import threading
import time
from time import perf_counter

from botocore.exceptions import ClientError

from config import Settings
from consumer import PoisonMessage
from voltera_common import parse_cloudevent


class IngestProcessor:
    def __init__(self, settings: Settings, table, sqs, stop: threading.Event | None = None, metrics=None, logger=None):
        self.s, self.table, self.sqs = settings, table, sqs
        self.stop = stop or threading.Event()
        self.metrics, self.logger = metrics, logger
        self.counters = {"enviados": 0, "duplicados": 0, "reenviados": 0}
        self.last_timings: dict = {}

    def _metric(self, name: str) -> None:
        if self.metrics is not None:
            self.metrics.add(name, 1)

    def _log(self, msg: str, **fields) -> None:
        if self.logger is not None:
            self.logger.info(msg, extra=fields)

    def _claim(self, ciclo: str, factura: str) -> str:
        """Devuelve 'NUEVO', 'REENVIAR' o 'DUPLICADO'."""
        key = {"cicloId": ciclo, "sk": f"DEDUP#{factura}"}
        try:
            self.table.put_item(
                Item={**key, "estado": "PROCESANDO", "recibidoEn": int(time.time()),
                      self.s.ttl_attr: int(time.time()) + self.s.dedup_ttl_seconds},
                ConditionExpression="attribute_not_exists(sk)",
            )
            return "NUEVO"
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
        item = self.table.get_item(Key=key, ConsistentRead=True).get("Item", {})
        return "DUPLICADO" if item.get("estado") == "ENVIADO" else "REENVIAR"

    def handle(self, value: bytes) -> str:
        try:
            ev = parse_cloudevent(value)
        except ValueError as exc:
            raise PoisonMessage(str(exc)) from exc
        if ev.name != "ConsumoFacturablePreparado":
            raise PoisonMessage(f"tipo inesperado en el topico de ingreso: {ev.type}")
        ciclo, factura = ev.cicloid, ev.facturaid
        t = {"claimMs": 0.0, "delayMs": 0.0, "sqsMs": 0.0, "updateMs": 0.0}
        self.last_timings = {"cicloId": ciclo, "facturaId": factura, **t}

        t0 = perf_counter()
        verdict = self._claim(ciclo, factura)
        t["claimMs"] = (perf_counter() - t0) * 1000
        self.last_timings.update(t, veredicto=verdict)
        if verdict == "DUPLICADO":
            self.counters["duplicados"] += 1
            self._metric("MensajesDuplicados")
            self._log("mensaje duplicado descartado", cicloId=ciclo, facturaId=factura)
            return verdict

        # Retardo simulado por mensaje (Exp. 1): data.retardoSegundos tiene prioridad sobre la variable de entorno.
        delay = float(ev.data.get("retardoSegundos", self.s.simulated_delay_seconds) or 0)
        t0 = perf_counter()
        if delay > 0 and self.stop.wait(delay):
            raise InterruptedError("apagado durante el retardo simulado: sin commit, se reentrega")
        t["delayMs"] = (perf_counter() - t0) * 1000 if delay > 0 else 0.0

        d = ev.data
        tx = {k: d[k] for k in ("cicloId", "facturaId", "clienteId", "tipoTarifa", "periodo", "ordinal", "totalUnidades") if d.get(k) is not None}
        tx["eventId"] = ev.id
        t0 = perf_counter()
        self.sqs.send_message(QueueUrl=self.s.sqs_queue_url, MessageBody=json.dumps(tx))
        t["sqsMs"] = (perf_counter() - t0) * 1000
        t0 = perf_counter()
        self.table.update_item(
            Key={"cicloId": ciclo, "sk": f"DEDUP#{factura}"},
            UpdateExpression="SET estado = :e, enviadoEn = :t",
            ExpressionAttributeValues={":e": "ENVIADO", ":t": int(time.time())},
        )
        t["updateMs"] = (perf_counter() - t0) * 1000
        self.last_timings.update(t)
        key = "reenviados" if verdict == "REENVIAR" else "enviados"
        self.counters[key] += 1
        self._metric("TransaccionesEnviadasASqs")
        if verdict == "REENVIAR":
            self._metric("MensajesReenviados")
        if self.metrics is not None:  # OBS-4: reparto por replica (dimension pod, <= max replicas valores)
            self.metrics.add("MensajesProcesadosPorPod", 1, dims={"pod": os.environ.get("HOSTNAME", "local")})
        self._log("transaccion enviada a SQS", cicloId=ciclo, facturaId=factura, veredicto=verdict, ordinal=d.get("ordinal"))
        return verdict


def report_timing(ingest: "IngestProcessor", metrics, logger, poll_ms: float, handle_ms: float, commit_ms: float) -> dict:
    """Log JSON por mensaje y metricas MensajeTotalMs / MensajeSobrecostoMs (total - retardo simulado)."""
    t = dict(ingest.last_timings)
    total = handle_ms + commit_ms
    sobrecosto = max(0.0, total - t.get("delayMs", 0.0))
    rec = {**t, "pollMs": round(poll_ms, 1), "handleMs": round(handle_ms, 1), "commitMs": round(commit_ms, 1),
           "totalMs": round(total, 1), "sobrecostoMs": round(sobrecosto, 1)}
    rec = {k: (round(v, 1) if isinstance(v, float) else v) for k, v in rec.items()}
    if logger is not None:
        logger.info("mensaje procesado", extra=rec)
    if metrics is not None:
        metrics.add("MensajeTotalMs", total, "Milliseconds")
        metrics.add("MensajeSobrecostoMs", sobrecosto, "Milliseconds")
    return rec
