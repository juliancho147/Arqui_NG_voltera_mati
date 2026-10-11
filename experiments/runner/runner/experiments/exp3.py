"""Exp. 3 - Cero perdida de solicitudes ante fallos (Durable Messaging, At-least-once, Idempotencia, Outbox)."""
from __future__ import annotations

import collections

from .. import actions, evidence, mesh
from ..kube import KubeError
from ..report import ExperimentResult
from .base import Experiment, fmt_ids


class Exp3(Experiment):
    name = "exp3"
    title = "Exp. 3 - Cero perdida de solicitudes ante fallos"
    hypothesis = ("Si un consumidor muere a mitad de procesamiento, los mensajes no confirmados se reentregan; la deduplicacion y la "
                  "idempotencia evitan facturas duplicadas y se cumple inyectadas = emitidas + (rechazadas) + DLQ.")
    mutates = True

    def _selector(self) -> str:
        return f"app.kubernetes.io/name={self.cfg.deployment}"

    @property
    def delay(self) -> float:
        return float(self.ctx.opt("delay", self.cfg.param("simulated_delay_seconds", 5)))

    def mutations(self) -> list[str]:
        c = self.cfg
        return [
            f"kubectl delete pod de {c.deployment} en el namespace {c.app_namespace} "
            f"({'--grace-period=0 --force' if not self.ctx.opt('graceful', False) else 'apagado ordenado'}) con mensajes en vuelo",
            f"Inyectar FORCE_FAIL=true en {c.lambda_name('ms-comprobante-factura')} a mitad del lote y restaurarlo (finally)",
            f"Seed de {self.n} transacciones y PutEvents CierreDeMes (ciclo {self.ciclo_id})",
        ]

    def plan(self) -> list[str]:
        c, mr = self.cfg, int(self.cfg.param("max_receive_count", 3))
        return [
            f"Seed de {self.n} transacciones (ciclo {self.ciclo_id}, retardoSegundos={self.delay}) + PutEvents CierreDeMes en {c.bus_name}",
            f"Esperar a que haya DEDUP# en PROCESANDO en {c.table('process-billing')} (mensajes en vuelo) y guardar la lista",
            f"kubectl delete pod -n {c.app_namespace} -l {self._selector()} (un pod; registrado en la bitacora)",
            "Esperar el pod de reemplazo (deployment listo) y verificar que los mensajes en vuelo se reentregan (DEDUP# -> ENVIADO)",
            f"Cuando haya >= {max(1, self.n // 2)} facturas emitidas: inyectar FORCE_FAIL en {c.lambda_name('ms-comprobante-factura')}, "
            f"mantener {int(self.ctx.opt('fault_window', 40))} s y restaurar (finally)",
            f"Esperar la convergencia (reentrega SQS: hasta {mr} x visibilityTimeout) y contabilizar",
            "Ecuacion: inyectadas = emitidas + rechazadas + mensajes en DLQ (sin faltantes ni ajenos)",
            "Duplicados: un registro de idempotencia COMPLETED por facturaId, numeroFactura unico, DEDUP# == N, eventos FacturaEmitida repetidos (Kafka, si accesible)",
            "Comprobantes: todas las facturas emitidas terminan notificadas tras el fallo (reentrega)",
        ]

    def execute(self, r: ExperimentResult) -> None:
        ctx, c, n = self.ctx, self.cfg, self.n
        poll = ctx.opt("poll", 5)
        mr = int(c.param("max_receive_count", 3))
        journal_ids: list[str] = []
        r.params.update({"retardoSegundos": self.delay})
        try:
            d = actions.dispatch_cierre(ctx, self.ciclo_id, n, retardo_segundos=self.delay)
            ids = d["facturaIds"]

            # 1) esperar mensajes en vuelo y matar el pod
            def in_flight():
                return [f for f, e in evidence.dedup_states(ctx, self.ciclo_id).items() if e == "PROCESANDO"]
            en_vuelo, _ = ctx.wait_until(in_flight, float(ctx.opt("timeout_inflight", 180)), poll)
            en_vuelo = in_flight()
            pods = ctx.kube.pods(c.app_namespace, self._selector())
            killed = None
            if pods:
                victim = pods[0]["name"]
                if not victim.startswith(c.deployment):
                    raise RuntimeError(f"pod '{victim}' no pertenece a {c.deployment}")
                ctx.journal.record("pod_delete", f"{c.app_namespace}/{victim}", {"pod": victim, "enVuelo": en_vuelo}, revertible=False)
                ctx.log(f"KILL pod {victim}; mensajes en vuelo: {len(en_vuelo)}")
                ctx.kube.delete_pod(c.app_namespace, victim, force=not ctx.opt("graceful", False))
                killed = victim

            def replaced():
                cur = ctx.kube.pods(c.app_namespace, self._selector())
                st = ctx.kube.deployment_status(c.app_namespace, c.deployment)
                return [p for p in cur if p["name"] != killed and p["ready"]] and st["ready"] >= 1
            rep_ok, rep_s = ctx.wait_until(replaced, float(ctx.opt("timeout_pod", 240)), poll)
            r.add("E3.1", "El pod de process-billing muerto es reemplazado y vuelve a estar listo", bool(killed) and bool(rep_ok),
                  "pod nuevo listo", f"muerto={killed}, reemplazo listo en {rep_s:.0f} s" if rep_ok else f"muerto={killed}, sin reemplazo",
                  mensajesEnVuelo=fmt_ids(en_vuelo))

            # 2) fallo del comprobante a mitad del lote
            mitad = max(1, n // 2)
            ctx.wait_until(lambda: len(evidence.facturas_emitidas(ctx, self.ciclo_id)) >= mitad, float(ctx.opt("timeout_mid", 240)), poll)
            journal_ids.append(actions.inject_fault(ctx, "ms-comprobante-factura", ctx.opt("fault_mode", "env")))
            ctx.sleep(float(ctx.opt("fault_window", 40)))
        finally:
            restored = actions.restore_ids(ctx, journal_ids)
        pend = [e for e in ctx.journal.pending() if e["id"] in journal_ids]
        r.add("E3.2", "ms-comprobante-factura restaurado tras el fallo a mitad del lote", not pend, "sin pendientes en bitacora",
              f"{len(pend)} pendientes", restauracion=restored)

        # 3) convergencia
        def converged() -> bool:
            a = evidence.account(ctx, self.ciclo_id, ids)
            q = a.colas
            quiet = evidence.queue_total(q["transacciones"]) == 0 and evidence.queue_total(q["comprobantes"]) == 0
            return a.ecuacion_ok and quiet and set(a.emitidas) <= (a.notificadas | a.dlq_comprobantes)
        ok, secs = ctx.wait_until(converged, float(ctx.opt("timeout", mr * 180 + 300)), poll)
        acc = evidence.account(ctx, self.ciclo_id, ids)
        dedup = evidence.dedup_states(ctx, self.ciclo_id)

        perdidos_en_vuelo = [f for f in en_vuelo if f not in acc.contabilizadas]
        reentregados = [f for f in en_vuelo if dedup.get(f) == "ENVIADO"]
        r.add("E3.3", "Los mensajes en vuelo al morir el pod se reentregan y se procesan (DEDUP# PROCESANDO -> ENVIADO)",
              (len(reentregados) == len(en_vuelo) and not perdidos_en_vuelo) if en_vuelo else None,
              "todos los PROCESANDO terminan ENVIADO y contabilizados",
              f"{len(reentregados)}/{len(en_vuelo)} reentregados; perdidos={fmt_ids(perdidos_en_vuelo)}" + ("" if en_vuelo else " (no hubo mensajes en vuelo: aumente --delay o --n)"),
              enVuelo=fmt_ids(en_vuelo), reentregados=fmt_ids(reentregados))
        r.add("E3.4", "Ecuacion de conservacion: inyectadas = facturas emitidas + rechazadas + mensajes en DLQ", bool(ok) and acc.ecuacion_ok,
              acc.ecuacion, f"faltantes={fmt_ids(acc.faltantes)} ajenas={fmt_ids(acc.ajenas)}", convergenciaSegundos=round(secs, 1),
              resumen=acc.resumen(), emitidasYDlq=acc.solapadas)
        nums = list(acc.emitidas.values())
        dup_nums = [k for k, v in collections.Counter(nums).items() if v > 1]
        cons = evidence.consecutivo(ctx)
        r.add("E3.5", "Cero facturas duplicadas (idempotencia): un registro por facturaId, numeroFactura unico, DEDUP# == N",
              not acc.emitidas_duplicadas and not dup_nums and len(dedup) == n, "0 duplicados; DEDUP# == N",
              f"duplicadas={fmt_ids(acc.emitidas_duplicadas)} numerosRepetidos={dup_nums} DEDUP#={len(dedup)} consecutivo={cons} emitidas={len(acc.emitidas)}",
              facturas=acc.emitidas, consecutivoContador=cons,
              nota="consecutivo > emitidas indicaria numeros consumidos sin factura (huecos), no duplicados")
        r.add("E3.6", "Comprobantes: toda factura emitida termina notificada (reentrega tras el fallo del tercero)",
              set(acc.emitidas) <= acc.notificadas | acc.dlq_comprobantes, "emitidas subset de notificadas (o en DLQ de comprobantes)",
              f"notificadas={len(acc.notificadas)} dlqComprobantes={len(acc.dlq_comprobantes)}",
              sinNotificar=fmt_ids(set(acc.emitidas) - acc.notificadas - acc.dlq_comprobantes))
        self._duplicate_events(r, acc)
        r.manual("E3.7", "Mensajes no procesables terminan en DLQ", "No se induce un mensaje venenoso en esta corrida (requiere publicar un cuerpo invalido en la cola y esperar maxReceiveCount); verificar a mano.")
        r.manual("E3.8", "Transactional Outbox: sin dual write entre DynamoDB y Kafka",
                 "Verificar en la tabla outbox que los items quedan en estado enviado y que el relay reintenta ante fallo de Kafka (no inducido por el runner).")

    def _duplicate_events(self, r: ExperimentResult, acc) -> None:
        try:
            recs = mesh.consume(self.ctx, self.cfg.kafka_cluster_billing, self.cfg.topic_eventos, timeout_ms=int(self.ctx.opt("kafka_timeout_ms", 20000)))
        except KubeError as exc:
            r.manual("E3.9", "Eventos FacturaEmitida no repetidos en el mesh", f"Kafka no accesible via kubectl exec: {exc}")
            return
        per = collections.defaultdict(set)
        for x in recs:
            v = x.value or {}
            if v.get("cicloid") == self.ciclo_id and mesh.type_to_name(v.get("type", "")) == "FacturaEmitida":
                per[v.get("facturaid")].add(v.get("id"))
        rep = {f: sorted(i) for f, i in per.items() if len(i) > 1}
        # at-least-once: un evento repetido con distinto id es aceptable, pero se reporta (no es FAIL)
        r.add("E3.9", "Eventos FacturaEmitida: una sola emision por factura en el mesh", None if rep else True, "1 evento por factura",
              f"{len(per)} facturas con evento; repetidas={len(rep)}", repetidas=rep,
              nota="Si hay repetidas es consecuencia de at-least-once (fallo despues de publicar y antes de persistir); los consumidores deben deduplicar por id.")
