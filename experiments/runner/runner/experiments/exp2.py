"""Exp. 2 - Caida de un dependiente sin detener el negocio (Bulkhead, DLQ, Retry con backoff)."""
from __future__ import annotations

from .. import actions, evidence
from ..kube import KubeError
from ..report import ExperimentResult
from .base import Experiment, fmt_ids

CASES = [
    # tag, servicio degradado, cola cuya DLQ recibe los fallos
    {"tag": "A", "service": "ms-tarifas", "dlq": "transacciones", "label": "ms-tarifas (dependiente interno, paso de Step Functions)"},
    {"tag": "B", "service": "ms-comprobante-factura", "dlq": "comprobantes", "label": "ms-comprobante-factura (simula al tercero)"},
]


class Exp2(Experiment):
    name = "exp2"
    title = "Exp. 2 - Caida de un dependiente sin detener el negocio (aislamiento)"
    hypothesis = ("Si se degrada un dependiente, las transacciones afectadas se reintentan y caen a la DLQ; Kafka/process-billing siguen "
                  "encolando; al restaurar el servicio y reprocesar la DLQ todo se recupera.")
    mutates = True

    @property
    def mode(self) -> str:
        return self.ctx.opt("fault_mode", "env")

    def _cases(self):
        sel = self.ctx.opt("case")
        return [c for c in CASES if not sel or c["tag"] == sel.upper()]

    def _vis(self) -> int:
        try:
            return evidence.queue_state(self.ctx, self.cfg.queue("comprobantes")["url"])["visibilityTimeout"]
        except Exception:  # noqa: BLE001
            return 180

    def mutations(self) -> list[str]:
        out = []
        for cs in self._cases():
            fn = self.cfg.lambda_name(cs["service"])
            how = "FORCE_FAIL=true (UpdateFunctionConfiguration)" if self.mode == "env" else "reserved concurrency = 0 (PutFunctionConcurrency)"
            out.append(f"Caso {cs['tag']}: degradar {fn} con {how}; se restaura al terminar (y con `python -m runner restore`)")
            out.append(f"Caso {cs['tag']}: escribir seed + CierreDeMes y redrive de la DLQ '{cs['dlq']}'")
        return out

    def plan(self) -> list[str]:
        c, steps = self.cfg, []
        mr = int(c.param("max_receive_count", 3))
        for cs in self._cases():
            fn, ciclo = c.lambda_name(cs["service"]), f"{self.ciclo_id}-{cs['tag']}"
            dlq = c.queue(cs["dlq"])["dlq_url"]
            steps += [
                f"[{cs['tag']}] Caso {cs['label']}: ciclo {ciclo}",
                f"[{cs['tag']}] Bitacora + inyectar fallo en {fn} ({'FORCE_FAIL=true' if self.mode == 'env' else 'concurrencia reservada 0'}); restaurar en finally",
                f"[{cs['tag']}] Seed de {self.n} transacciones + PutEvents CierreDeMes en {c.bus_name}",
            ]
            if cs["tag"] == "A":
                steps += [
                    f"[A] Verificar reintentos: ejecuciones FALLIDAS de Step Functions con >= 1+{c.param('sfn_retry', {}).get('max_attempts', 3)} intentos por paso (Retry backoff)",
                    f"[A] Esperar {self.n} mensajes en la DLQ {dlq}; verificar emitidas=0 y que process-billing siguio encolando (DEDUP# ENVIADO={self.n}, deploy listo)",
                ]
            else:
                steps += [
                    f"[B] Verificar flujo principal intacto (bulkhead): {self.n} facturas emitidas pese a la caida del comprobante",
                    f"[B] Esperar {self.n} mensajes en la DLQ {dlq} (maxReceiveCount={mr} x visibilityTimeout, minutos)",
                ]
            steps += [
                f"[{cs['tag']}] Restaurar {fn} al estado original y verificar la restauracion",
                f"[{cs['tag']}] Redrive de la DLQ (SQS StartMessageMoveTask) y esperar la recuperacion total (DLQ vacia, FACT# OK={self.n}, META COMPLETADO)",
            ]
        steps.append("Reporte PASS/FAIL por criterio")
        return steps

    # ------------------------------------------------------------------ ejecucion
    def execute(self, r: ExperimentResult) -> None:
        r.params.update({"modoFallo": self.mode})
        for cs in self._cases():
            self._run_case(r, cs)

    def _run_case(self, r: ExperimentResult, cs: dict) -> None:
        ctx, c, n = self.ctx, self.cfg, self.n
        tag, service = cs["tag"], cs["service"]
        ciclo = f"{self.ciclo_id}-{tag}"
        ids: list[str] = []
        journal_ids: list[str] = []
        mr = int(c.param("max_receive_count", 3))
        timeout = float(ctx.opt("timeout", self.scale_time(300 if tag == "A" else mr * self._vis() + 240)))
        poll = ctx.opt("poll", 5)
        pre = f"E2.{tag}"
        serie: list[dict] = []
        r.data[f"serie{tag}"] = serie
        try:
            ctx.phase("estado_inicial", f"Caso {tag} ({cs['label']}): todo sano, colas y DLQ en 0")
            self._watch(serie, ciclo, 0.0, tag)()
            ctx.phase("fallo_inyectado", f"Se degrada {service} ({'FORCE_FAIL=true' if self.mode == 'env' else 'concurrencia reservada 0'}); el resto de servicios sigue en linea")
            journal_ids.append(actions.inject_fault(ctx, service, self.mode))
            ctx.phase("disparo", f"{n} transacciones entran por el cierre de mes con {service} caido")
            d = actions.dispatch_cierre(ctx, ciclo, n)
            ids, t0 = d["facturaIds"], d["t0"]
            tick = self._watch(serie, ciclo, t0, tag)
            ctx.phase("acumulacion", "Los mensajes afectados se reintentan y se acumulan en la DLQ; el flujo restante sigue. Observe cola/DLQ" )

            if tag == "A":
                def in_dlq_a() -> bool:
                    i, a, _ = evidence.dlq_factura_ids(ctx, "transacciones", ciclo, n)
                    return evidence.dlq_covers(ids, i, a)
                dlq_ok, _ = ctx.wait_until(in_dlq_a, timeout, poll, on_tick=tick)
                dlq_ids, dlq_aprox, muestra = evidence.dlq_factura_ids(ctx, "transacciones", ciclo, n)
                r.add(f"{pre}.1", f"Con {service} caido, las {n} transacciones afectadas llegan a la DLQ de transacciones",
                      evidence.dlq_covers(ids, dlq_ids, dlq_aprox), f"{n} en DLQ", f"{len(dlq_ids)} en DLQ ({dlq_aprox} aprox. total)", dlq=fmt_ids(dlq_ids), muestra=muestra)
                # reintentos con backoff (Step Functions)
                try:
                    sfn = evidence.sfn_failed_attempts(ctx, t0 - 5)
                    esperado = 1 + int(c.param("sfn_retry", {}).get("max_attempts", 3))
                    por_ej = [e["intentosFallidos"] for e in sfn["ejecuciones"]]
                    r.add(f"{pre}.2", "Hubo reintentos antes de caer a la DLQ (Retry de Step Functions)",
                          bool(por_ej) and all(x >= esperado for x in por_ej), f">= {esperado} intentos fallidos por ejecucion",
                          f"{por_ej}", ejecuciones=sfn["ejecuciones"])
                except Exception as exc:  # noqa: BLE001
                    r.manual(f"{pre}.2", "Hubo reintentos antes de caer a la DLQ (Retry de Step Functions)",
                             f"No se pudo leer el historial de Step Functions ({type(exc).__name__}); revisar la consola/CloudWatch Logs")
                acc = evidence.account(ctx, ciclo, ids)
                r.add(f"{pre}.3", "El resto del flujo no avanza a facturas con el dependiente caido (sin emisiones parciales erroneas)",
                      len(acc.emitidas) == 0, "0 emitidas mientras tarifas esta caido", f"{len(acc.emitidas)} emitidas")
            else:
                ok, _ = ctx.wait_until(lambda: len(evidence.facturas_emitidas(ctx, ciclo)) >= n, timeout, poll, on_tick=tick)
                acc = evidence.account(ctx, ciclo, ids)
                r.add(f"{pre}.1", "Flujo principal intacto (bulkhead): las facturas se emiten aunque el comprobante este caido",
                      len(acc.emitidas) == n, f"{n} emitidas", f"{len(acc.emitidas)} emitidas", emitidas=fmt_ids(acc.emitidas))
                def in_dlq_b() -> bool:
                    i, a, _ = evidence.dlq_factura_ids(ctx, "comprobantes", ciclo, n)
                    return evidence.dlq_covers(ids, i, a)
                dlq_ok, _ = ctx.wait_until(in_dlq_b, timeout, poll, on_tick=tick)
                dlq_ids, dlq_aprox, muestra = evidence.dlq_factura_ids(ctx, "comprobantes", ciclo, n)
                r.add(f"{pre}.2", f"Tras {mr} entregas fallidas, los {n} comprobantes caen a la DLQ de comprobantes",
                      evidence.dlq_covers(ids, dlq_ids, dlq_aprox), f"{n} en DLQ", f"{len(dlq_ids)} en DLQ ({dlq_aprox} aprox.)", dlq=fmt_ids(dlq_ids), muestra=muestra,
                      visibilityTimeout=self._vis(), maxReceiveCount=mr)
                fallidas = {f for f, e in evidence.fact_states(ctx, ciclo).items() if e == "FALLIDA"}
                r.add(f"{pre}.3", "process-billing registra las notificaciones definitivamente fallidas (FACT# FALLIDA)",
                      len(fallidas) == n, f"{n} FALLIDA", f"{len(fallidas)} FALLIDA", fallidas=fmt_ids(fallidas))

            # Kafka / process-billing siguen encolando durante la caida
            dedup = evidence.dedup_states(ctx, ciclo)
            enviados = sum(1 for e in dedup.values() if e == "ENVIADO")
            st = ctx.kube.deployment_status(c.app_namespace, c.deployment)
            r.add(f"{pre}.4", "Kafka/process-billing siguen encolando durante la caida (DEDUP# ENVIADO) y el deployment sigue en linea",
                  enviados == n and st["ready"] >= 1, f"{n} ENVIADO, >=1 replica lista", f"{enviados} ENVIADO, {st['ready']} listas",
                  deploy={k: st[k] for k in ("spec", "replicas", "ready")})
            r.add(f"{pre}.5", "Endpoint de salud dummy (servicios 'en linea'): /healthz de ms-process-billing responde", self._health(),
                  "HTTP 200 via proxy del API server", "ver evidencia")
            ctx.phase("recuperacion", f"Se restaura {service} (se revierte el fallo) y se reprocesa la DLQ (redrive); observe como drena")
        finally:
            restored = actions.restore_ids(ctx, journal_ids)
        pending = [e for e in ctx.journal.pending() if e["id"] in journal_ids]
        r.add(f"{pre}.6", f"{service} restaurado al estado original", not pending, "sin entradas pendientes en la bitacora",
              f"{len(pending)} pendientes", restauracion=restored)
        if not ids:
            return

        # recuperacion: redrive de la DLQ
        red = actions.redrive_dlq(ctx, cs["dlq"], timeout=self.scale_time(120, 0.5))
        ctx.log(f"redrive {cs['dlq']}: {red}")

        def recovered() -> bool:
            a = evidence.account(ctx, ciclo, ids)
            return (len(a.emitidas) + len(a.rechazadas) >= n and len(a.notificadas) >= len(a.emitidas)
                    and a.dlq_aprox == 0 and a.dlq_comprobantes_aprox == 0)
        ok, secs = ctx.wait_until(recovered, float(ctx.opt("timeout_recovery", self.scale_time(300, 3))), poll, on_tick=tick)
        acc = evidence.account(ctx, ciclo, ids)
        meta = evidence.ciclo_meta(ctx, ciclo)
        facts = evidence.fact_states(ctx, ciclo)
        oks = sum(1 for e in facts.values() if e == "OK")
        r.add(f"{pre}.7", "Redrive de la DLQ exitoso (mensajes devueltos a la cola de origen)", red.get("status") == "COMPLETED",
              "COMPLETED", str(red.get("status")), redrive=red)
        r.add(f"{pre}.8", "Recuperacion total tras restaurar y reprocesar: DLQ vacia y ecuacion de conservacion cumplida",
              bool(ok) and acc.ecuacion_ok and acc.dlq_aprox == 0 and acc.dlq_comprobantes_aprox == 0, acc.ecuacion,
              f"emitidas={len(acc.emitidas)} notificadas={len(acc.notificadas)} dlq={acc.dlq_aprox}/{acc.dlq_comprobantes_aprox}",
              segundosHastaRecuperar=round(secs, 1), resumen=acc.resumen())
        r.add(f"{pre}.9", "Estado del ciclo consistente tras la recuperacion (FACT# OK y META COMPLETADO)",
              oks == n and meta.get("estado") == "COMPLETADO", f"{n} OK y COMPLETADO", f"{oks} OK, estado {meta.get('estado')}", meta=meta,
              duplicadas=acc.emitidas_duplicadas)

    def _watch(self, serie: list[dict], ciclo: str, t0: float, tag: str):
        """Devuelve un callback que muestrea y muestra colas/DLQ/emitidas (para ver la DLQ acumularse y drenar)."""
        ctx, c = self.ctx, self.cfg

        def tick() -> None:
            try:
                qt, qc = c.queue("transacciones"), c.queue("comprobantes")
                s = {"t": round(max(0.0, ctx.clock() - t0), 1) if t0 else 0.0,
                     "emitidas": len(evidence.facturas_emitidas(ctx, ciclo)),
                     "colaTx": evidence.queue_total(evidence.queue_state(ctx, qt["url"])),
                     "dlqTx": evidence.queue_total(evidence.queue_state(ctx, qt["dlq_url"])),
                     "colaComp": evidence.queue_total(evidence.queue_state(ctx, qc["url"])),
                     "dlqComp": evidence.queue_total(evidence.queue_state(ctx, qc["dlq_url"]))}
            except Exception as exc:  # noqa: BLE001 - la observacion nunca debe romper el experimento
                ctx.log(f"aviso: no se pudo muestrear colas ({type(exc).__name__})")
                return
            serie.append(s)
            ctx.log(f"[{tag}] t={s['t']}s emitidas={s['emitidas']}/{self.n} cola-tx={s['colaTx']} DLQ-tx={s['dlqTx']} "
                    f"cola-comp={s['colaComp']} DLQ-comp={s['dlqComp']}")
        return tick

    def _health(self) -> bool | None:
        c = self.cfg
        try:
            res = self.ctx.kube.run(["get", "--raw", f"/api/v1/namespaces/{c.app_namespace}/services/{c.deployment}:8080/proxy/healthz"],
                                    timeout=30, check=False)
            return res.returncode == 0
        except KubeError:
            return None
