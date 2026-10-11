"""Exp. 1 - Absorcion del pico de fin de mes (KEDA 1..n, Queue-Based Load Leveling)."""
from __future__ import annotations

from .. import actions, evidence, mesh
from ..kube import KubeError
from ..report import ExperimentResult
from .base import Experiment, fmt_ids


class Exp1(Experiment):
    name = "exp1"
    title = "Exp. 1 - Absorcion del pico de fin de mes (auto-escalado)"
    hypothesis = ("Con N transacciones inyectadas y un retardo simulado por mensaje, KEDA escala ms-process-billing segun el lag, "
                  "drena el backlog dentro del SLA y vuelve al minimo de replicas, sin perdidas.")

    # parametros efectivos
    @property
    def delay(self) -> float:
        return float(self.ctx.opt("delay", self.cfg.param("simulated_delay_seconds", 5)))

    @property
    def sla(self) -> float:
        """SLA del lote: --sla explicito > --sla-per-msg (s por mensaje) > proporcional a N (--sla-scale, modo demo) > base del plan."""
        opt = self.ctx.opt
        if opt("sla") is not None:
            return float(opt("sla"))
        base = float(self.cfg.param("batch_sla_seconds", 120))
        if opt("sla_per_msg") is not None:
            return max(base, self.n * float(opt("sla_per_msg")))
        if opt("sla_scale", False):
            mx = max(1, int(self.cfg.param("process_billing_max", 5)))
            return max(base, self.n * self.delay / mx * float(opt("sla_factor", 1.5)) + 60)
        return base

    def plan(self) -> list[str]:
        c = self.cfg
        return [
            f"Leer replicas base: kubectl get deploy {c.deployment} -n {c.app_namespace} (min esperado {c.param('process_billing_min', 1)})",
            f"Seed de {self.n} transacciones en {c.table('transacciones')} (ciclo {self.ciclo_id}) con retardoSegundos={self.delay} por mensaje (fuerza backlog)",
            f"PutEvents voltera.runner/CierreDeMes -> bus {c.bus_name} {{cicloId, nSolicitudes={self.n}}}",
            f"Muestrear cada 5 s: replicas (deploy), desiredReplicas (hpa keda-hpa-{c.scaledobject}), lag del grupo en Kafka ({c.kafka_cluster_billing}), "
            f"FACT# terminados en {c.table('process-billing')}, tamano de DLQ",
            f"Medir tiempo del lote (PutEvents -> {self.n} FACT# terminales) vs SLA {self.sla:.0f} s",
            f"Esperar hasta {int(self.ctx.opt('scaledown_timeout', 420))} s a que las replicas bajen al minimo",
            "Contabilidad: inyectadas = emitidas + rechazadas + DLQ (cero perdidas); DLQ vacia",
            "Reporte PASS/FAIL por criterio (no modifica infraestructura; solo escribe el seed y el evento del cierre)",
        ]

    def _group(self, dep_raw: dict) -> str | None:
        for c in dep_raw.get("spec", {}).get("template", {}).get("spec", {}).get("containers", []):
            for e in c.get("env", []):
                if e.get("name") == "KAFKA_CONSUMER_GROUP":
                    return e.get("value")
        return None

    def execute(self, r: ExperimentResult) -> None:
        ctx, c = self.ctx, self.cfg
        mn, mx = int(c.param("process_billing_min", 1)), int(c.param("process_billing_max", 5))
        ctx.phase("estado_inicial", f"Replicas base de {c.deployment} (esperado {mn}), lag 0, DLQ vacia")
        r.params.update({"retardoSegundos": self.delay, "slaSegundos": self.sla, "replicasMin": mn, "replicasMax": mx})
        base = ctx.kube.deployment_status(c.app_namespace, c.deployment)
        group = self._group(base["raw"])
        r.data["replicasIniciales"] = {k: base[k] for k in ("spec", "replicas", "ready")}

        ctx.phase("disparo", f"Seed de {self.n} transacciones + evento CierreDeMes (retardo {self.delay} s/mensaje, SLA {self.sla:.0f} s)")
        d = actions.dispatch_cierre(ctx, self.ciclo_id, self.n, retardo_segundos=self.delay)
        t0, ids = d["t0"], d["facturaIds"]
        series: list[dict] = []

        def sample() -> dict:
            st = ctx.kube.deployment_status(c.app_namespace, c.deployment)
            try:
                desired = ctx.kube.hpa_desired(c.app_namespace, c.scaledobject)
            except KubeError:
                desired = None
            lag = mesh.consumer_lag(ctx, c.kafka_cluster_billing, group) if group else None
            facts = evidence.fact_states(ctx, self.ciclo_id)
            dlq = evidence.queue_total(evidence.queue_state(ctx, c.queue("transacciones")["dlq_url"]))
            s = {"t": round(ctx.clock() - t0, 1), "replicas": st["replicas"], "ready": st["ready"], "desired": desired,
                 "lag": lag, "terminadas": len(facts), "dlq": dlq}
            series.append(s)
            ctx.log(f"t={s['t']}s replicas={s['replicas']} desired={desired} lag={lag} terminadas={s['terminadas']}/{self.n} dlq={dlq}")
            return s

        def done() -> bool:
            s = sample()
            return s["terminadas"] >= self.n or s["dlq"] > 0 and s["terminadas"] + s["dlq"] >= self.n

        timeout = float(ctx.opt("timeout", max(self.sla * 3, 300)))
        ctx.phase("absorcion", "KEDA escala segun el lag; se drena el backlog. Observe replicas, lag y facturas terminadas")
        ok, _ = ctx.wait_until(done, timeout, ctx.opt("poll", 5))
        t_batch = ctx.clock() - t0 if ok else None

        acc = evidence.account(ctx, self.ciclo_id, ids)
        peak = max([max(s["replicas"] or 0, s["desired"] or 0) for s in series] or [0])

        # --- bajada de replicas
        if not ctx.opt("skip_scaledown", False):
            ctx.phase("recuperacion", "Backlog drenado: las replicas deben volver al minimo sin intervencion manual")

            def down() -> bool:
                st = ctx.kube.deployment_status(c.app_namespace, c.deployment)
                series.append({"t": round(ctx.clock() - t0, 1), "replicas": st["replicas"], "ready": st["ready"], "desired": None,
                               "lag": None, "terminadas": self.n, "dlq": 0, "fase": "scale-down"})
                return st["replicas"] <= mn and st["ready"] <= mn
            scaled_down, _ = ctx.wait_until(down, float(ctx.opt("scaledown_timeout", 420)), ctx.opt("poll", 5))
        else:
            scaled_down = None
        r.data["serie"] = series
        r.data["slaSegundos"] = self.sla

        r.add("E1.1", "El lote completo termina (todas las facturas llegan a estado terminal)", bool(ok) and len(acc.faltantes) == 0,
              f"{self.n} FACT# terminales", f"{len(evidence.fact_states(ctx, self.ciclo_id))} terminales; faltantes={fmt_ids(acc.faltantes)}",
              resumen=acc.resumen())
        r.add("E1.2", f"Tiempo del lote <= SLA ({self.sla:.0f} s)", t_batch is not None and t_batch <= self.sla,
              f"<= {self.sla:.0f} s", "no termino" if t_batch is None else f"{t_batch:.1f} s", tiempoLoteSegundos=t_batch)
        r.add("E1.3", "KEDA escala hacia arriba (replicas > minimo) mientras hay backlog", peak > mn,
              f"> {mn} replicas", f"pico {peak} replicas", pico=peak)
        r.add("E1.4", "No se supera el maximo de replicas", peak <= mx, f"<= {mx}", f"pico {peak}")
        lags = [s["lag"] for s in series if s.get("lag") is not None]
        if lags:
            r.add("E1.5", "El lag crece y se drena hasta 0", max(lags) > 0 and lags[-1] == 0, "lag pico > 0 y lag final 0",
                  f"pico {max(lags)}, final {lags[-1]}", lagPico=max(lags), lagFinal=lags[-1])
        else:
            r.manual("E1.5", "El lag crece y se drena hasta 0", "No se pudo leer el lag (kafka-consumer-groups via kubectl exec); revisar en Grafana/KEDA")
        if scaled_down is None:
            r.manual("E1.6", "Las replicas vuelven al minimo al drenar", "omitido por --skip-scaledown")
        else:
            r.add("E1.6", "Las replicas vuelven al minimo al drenar (sin intervencion manual)", bool(scaled_down), f"{mn} replica(s)",
                  f"{series[-1]['replicas']} replicas", cooldownEsperadoSegundos=ctx.opt("scaledown_timeout", 420))
        r.add("E1.7", "Cero transacciones perdidas por saturacion (inyectadas = emitidas + rechazadas + DLQ) y DLQ vacia",
              acc.ecuacion_ok and not acc.dlq and acc.dlq_aprox == 0, acc.ecuacion, f"faltantes={fmt_ids(acc.faltantes)} dlq={acc.dlq_aprox}",
              resumen=acc.resumen())
        r.notes.append("La escala validada es <=10 solicitudes: comportamiento, no capacidad. El backlog se fuerza con retardoSegundos por mensaje.")
        r.manual("E1.8", "(Opcional) concurrencia de Lambdas/Step Functions para ubicar el cuello de botella",
                 "Revisar metricas ConcurrentExecutions de CloudWatch y el dashboard; el runner no las consulta.")
