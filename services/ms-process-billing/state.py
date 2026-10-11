"""Estado del ciclo (item META) a partir de los eventos del mesh; emite ProcesoDeFacturacionCompletado/Fallido.

Items en la tabla process-billing (PK cicloId, SK sk):
  META             totalUnidades, iniciadoEn(epoch), estado EN_CURSO|COMPLETADO|FALLIDO, emitidas, rechazadas, fallidas
  FACT#<facturaId> estado terminal de la factura: OK | RECHAZADA | FALLIDA (unicidad => idempotente ante eventos repetidos)
"""
from __future__ import annotations

import time
import uuid

from botocore.exceptions import ClientError

from config import Settings
from consumer import PoisonMessage
from voltera_common import CICLO_SENTINEL, DomainEventPublisher, make_event, parse_cloudevent

TERMINAL_OK = {"FacturaNotificada"}
TERMINAL_RECHAZO = {"TarifaRechazada", "CalculoDeCargoRechazado", "EmisionDeFacturaRechazada"}
COUNTER = {"OK": "emitidas", "RECHAZADA": "rechazadas", "FALLIDA": "fallidas"}
_NS = uuid.UUID("0b3b1e1e-7d1c-4f43-8f0b-5b9a1c2d3e4f")


def _is_cancelled(exc: ClientError) -> bool:
    return exc.response["Error"]["Code"] in ("TransactionCanceledException", "ConditionalCheckFailedException")


class CycleState:
    def __init__(self, settings: Settings, table, publisher: DomainEventPublisher, clock=time.time, logger=None, metrics=None):
        self.s, self.table, self.pub, self.clock, self.logger = settings, table, publisher, clock, logger
        self.metrics = metrics
        self.known: set[str] = set()

    def _m(self, name: str, value: float = 1, unit: str = "Count") -> None:
        if self.metrics is not None:
            self.metrics.add(name, value, unit)

    def _log(self, msg: str, **fields) -> None:
        if self.logger is not None:
            self.logger.info(msg, extra=fields)

    # ---- entrada
    def handle(self, value: bytes) -> None:
        try:
            ev = parse_cloudevent(value)
        except ValueError as exc:
            raise PoisonMessage(str(exc)) from exc
        name, ciclo, factura = ev.name, ev.cicloid, ev.facturaid
        if name == "CicloDeFacturacionIniciado":
            self._iniciado(ciclo, int(ev.data["totalUnidades"]))
        elif name in TERMINAL_OK:
            self._terminal(ciclo, factura, "OK")
        elif name in TERMINAL_RECHAZO:
            self._terminal(ciclo, factura, "RECHAZADA")
        elif name == "NotificacionFallida" and ev.data.get("definitivo"):
            self._terminal(ciclo, factura, "FALLIDA")
        else:
            return
        self.known.add(ciclo)
        self._log("evento de estado aplicado", cicloId=ciclo, facturaId=factura, tipo=name)
        self.evaluate(ciclo)

    def _meta_key(self, ciclo: str) -> dict:
        return {"cicloId": ciclo, "sk": "META"}

    def _iniciado(self, ciclo: str, total: int) -> None:
        self.table.update_item(
            Key=self._meta_key(ciclo),
            UpdateExpression="SET totalUnidades = :t, iniciadoEn = if_not_exists(iniciadoEn, :now), "
                             "estado = if_not_exists(estado, :en), #ttl = :ttl",
            ExpressionAttributeNames={"#ttl": self.s.ttl_attr},
            ExpressionAttributeValues={":t": total, ":now": int(self.clock()), ":en": "EN_CURSO",
                                       ":ttl": int(self.clock()) + self.s.dedup_ttl_seconds},
        )

    def _terminal(self, ciclo: str, factura: str, estado: str) -> None:
        fact_key = {"cicloId": ciclo, "sk": f"FACT#{factura}"}
        client = self.table.meta.client
        try:
            client.transact_write_items(TransactItems=[
                {"Put": {"TableName": self.table.name, "Item": {**fact_key, "estado": estado, self.s.ttl_attr: int(self.clock()) + self.s.dedup_ttl_seconds},
                         "ConditionExpression": "attribute_not_exists(sk)"}},
                {"Update": {"TableName": self.table.name, "Key": self._meta_key(ciclo),
                            "UpdateExpression": f"ADD {COUNTER[estado]} :uno",
                            "ExpressionAttributeValues": {":uno": 1}}},
            ])
            return
        except ClientError as exc:
            if not _is_cancelled(exc):
                raise
        # Ya existia un terminal para esta factura: solo se acepta la recuperacion FALLIDA -> OK (redrive de la DLQ).
        if estado == "OK":
            try:
                client.transact_write_items(TransactItems=[
                    {"Update": {"TableName": self.table.name, "Key": fact_key, "UpdateExpression": "SET estado = :ok",
                                "ConditionExpression": "estado = :f", "ExpressionAttributeValues": {":ok": "OK", ":f": "FALLIDA"}}},
                    {"Update": {"TableName": self.table.name, "Key": self._meta_key(ciclo),
                                "UpdateExpression": "ADD fallidas :menos, emitidas :uno",
                                "ExpressionAttributeValues": {":menos": -1, ":uno": 1}}},
                ])
            except ClientError as exc:
                if not _is_cancelled(exc):
                    raise

    # ---- evaluacion
    def evaluate(self, ciclo: str) -> str | None:
        meta = self.table.get_item(Key=self._meta_key(ciclo), ConsistentRead=True).get("Item")
        if not meta or "totalUnidades" not in meta:
            return None
        total = int(meta["totalUnidades"])
        ok, rech, fall = (int(meta.get(k, 0)) for k in ("emitidas", "rechazadas", "fallidas"))
        estado = meta.get("estado", "EN_CURSO")
        if ok + rech + fall < total:
            return None
        counters = {"emitidas": ok, "rechazadas": rech, "fallidas": fall, "totalUnidades": total}
        if fall == 0 and estado != "COMPLETADO":
            ev = make_event("ProcesoDeFacturacionCompletado", self.s.service, ciclo, CICLO_SENTINEL,
                            event_id=str(uuid.uuid5(_NS, f"{ciclo}|completado")), **counters)
            self.pub.publish_event(ev)  # estricto: si falla, se reintenta el mensaje
            self._set_estado(ciclo, "COMPLETADO")
            self._m("CiclosCompletados")
            if "iniciadoEn" in meta:
                self._m("CicloDuracionSegundos", max(0.0, self.clock() - float(meta["iniciadoEn"])), "Seconds")
            self._log("ciclo completado", cicloId=ciclo, **counters)
            return "COMPLETADO"
        if fall > 0 and estado not in ("FALLIDO", "COMPLETADO"):
            ev = make_event("ProcesoDeFacturacionFallido", self.s.service, ciclo, CICLO_SENTINEL,
                            event_id=str(uuid.uuid5(_NS, f"{ciclo}|fallido|{fall}")), motivo=f"NOTIFICACIONES_FALLIDAS:{fall}", **counters)
            self.pub.publish_event(ev)
            self._set_estado(ciclo, "FALLIDO")
            self._m("CiclosFallidos")
            self._log("ciclo fallido", cicloId=ciclo, motivo="NOTIFICACIONES_FALLIDAS", **counters)
            return "FALLIDO"
        return None

    def _set_estado(self, ciclo: str, estado: str) -> None:
        self.table.update_item(Key=self._meta_key(ciclo), UpdateExpression="SET estado = :e",
                               ExpressionAttributeValues={":e": estado})

    def sweep_timeouts(self) -> list[str]:
        """Ciclos EN_CURSO que superaron CICLO_TIMEOUT_SECONDS -> ProcesoDeFacturacionFallido (p. ej. mensajes en DLQ)."""
        out = []
        for ciclo in list(self.known):
            meta = self.table.get_item(Key=self._meta_key(ciclo), ConsistentRead=True).get("Item")
            if not meta or meta.get("estado") != "EN_CURSO" or "iniciadoEn" not in meta:
                continue
            if self.clock() - float(meta["iniciadoEn"]) < self.s.ciclo_timeout_seconds:
                continue
            counters = {k: int(meta.get(k, 0)) for k in ("emitidas", "rechazadas", "fallidas")}
            ev = make_event("ProcesoDeFacturacionFallido", self.s.service, ciclo, CICLO_SENTINEL,
                            event_id=str(uuid.uuid5(_NS, f"{ciclo}|timeout")), motivo="TIMEOUT_CICLO",
                            totalUnidades=int(meta.get("totalUnidades", 0)), **counters)
            try:
                self.table.update_item(Key=self._meta_key(ciclo), UpdateExpression="SET estado = :f",
                                       ConditionExpression="estado = :en", ExpressionAttributeValues={":f": "FALLIDO", ":en": "EN_CURSO"})
            except ClientError as exc:
                if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                    continue  # otra replica ya lo marco
                raise
            self.pub.publish_event(ev)
            self._m("CiclosFallidos")
            self._log("ciclo fallido", cicloId=ciclo, motivo="TIMEOUT_CICLO", **counters)
            out.append(ciclo)
        return out
