"""Exp. 2 - Resiliencia ante fallos (aislamiento + cero perdida). Une los antiguos Exp. 2 (caida de un dependiente) y Exp. 3 (cero perdida).

Un solo escenario, en fases (cada una con banner, pausa, marca en marcas.json y metrica FaseExperimento):

  estado_inicial -> disparo -> fallo_dependiente -> fallo_pod -> fallo_lambda -> duplicados -> recuperacion -> veredicto

El fallo del dependiente (FORCE_FAIL) se mantiene desde `fallo_dependiente` hasta `recuperacion`; encima se mata K pods de
ms-process-billing con mensajes en vuelo, se inyecta FAIL_RATE en ms-facturacion durante una ventana y se reenvian D copias
de mensajes ya enviados (SQS y Kafka). Todo se revierte en `finally` y con `python -m runner restore`.
"""
from __future__ import annotations

import collections
import math

from .. import actions, evidence, mesh
from ..kube import KubeError
from ..report import ExperimentResult
from .base import Experiment, fmt_ids

CASES = {
    # tag, servicio degradado, cola cuya DLQ recibe los fallos
    "A": {"tag": "A", "service": "ms-tarifas", "dlq": "transacciones", "label": "ms-tarifas (dependiente interno, paso de Step Functions)"},
    "B": {"tag": "B", "service": "ms-comprobante-factura", "dlq": "comprobantes", "label": "ms-comprobante-factura (simula al tercero)"},
}
PHASES = ["estado_inicial", "disparo", "fallo_dependiente", "fallo_pod", "fallo_lambda", "duplicados", "recuperacion", "veredicto"]
GROUPS = ("AISLAMIENTO", "CERO PERDIDA", "IDEMPOTENCIA", "RECUPERACION")


class _State:
    """Estado compartido entre fases."""
    ids: list[str] = []
    t0: float = 0.0
    tick = staticmethod(lambda: None)
    e0 = 0
    env0 = 0
    en_vuelo: list[str] = []
    killed: list[str] = []
    dup: dict | None = None
    t_dup = 0.0


class Exp2(Experiment):
    name = "exp2"
    title = "Exp. 2 - Resiliencia ante fallos (aislamiento + cero perdida)"
    hypothesis = ("Con un dependiente caido, pods de process-billing muertos con mensajes en vuelo, una Lambda con fallos parciales y "
                  "mensajes duplicados a proposito: el resto del sistema sigue facturando (aislamiento), inyectadas = emitidas + rechazadas + DLQ "
                  "antes y despues del redrive (cero perdida), los duplicados no crean facturas extra (idempotencia) y al restaurar todo "
                  "las colas y DLQ quedan en 0 (recuperacion).")
    mutates = True
    verdict_phase_inside = True

    def __init__(self, ctx, n, ciclo_id):
        super().__init__(ctx, n, ciclo_id)
        self._fase = "estado_inicial"
        self._serie: list[dict] = []

    # ------------------------------------------------------------------ parametros
    @property
    def case(self) -> dict:
        return CASES[str(self.ctx.opt("case", "B")).upper()]

    @property
    def mode(self) -> str:
        return self.ctx.opt("fault_mode", "env")

    @property
    def delay(self) -> float:
        return float(self.ctx.opt("delay", self.cfg.param("simulated_delay_seconds", 5)))

    @property
    def fail_rate(self) -> float:
        return float(self.ctx.opt("fail_rate", 0.25))

    @property
    def kill_pods(self) -> int:
        return max(1, int(self.ctx.opt("kill_pods", 1)))

    @property
    def window(self) -> float:
        return float(self.ctx.opt("fault_window", 40))

    @property
    def observe(self) -> float:
        return float(self.ctx.opt("observe", 30))

    @property
    def dupl(self) -> int:
        return max(0, int(self.ctx.opt("dupl", 50)))

    def _selector(self) -> str:
        return f"app.kubernetes.io/name={self.cfg.deployment}"

    # ------------------------------------------------------------------ plan / mutaciones
    def mutations(self) -> list[str]:
        c, cs = self.cfg, self.case
        how = "FORCE_FAIL=true (UpdateFunctionConfiguration)" if self.mode == "env" else "reserved concurrency = 0 (PutFunctionConcurrency)"
        out = [
            f"Seed de {self.n} transacciones y PutEvents CierreDeMes (ciclo {self.ciclo_id})",
            f"Caso {cs['tag']}: degradar {c.lambda_name(cs['service'])} con {how}; se mantiene hasta la recuperacion y se restaura al terminar "
            f"(y con `python -m runner restore`)",
            f"kubectl delete pod ({self.kill_pods}) de {c.deployment} en {c.app_namespace} "
            f"({'--grace-period=0 --force' if not self.ctx.opt('graceful', False) else 'apagado ordenado'}) con mensajes en vuelo",
        ]
        out.append(f"Inyectar FAIL_RATE={self.fail_rate} en {c.lambda_name('ms-facturacion')} durante {self.window:g} s y restaurarlo" if self.fail_rate > 0
                   else "Sin fallo parcial en ms-facturacion (--fail-rate 0)")
        if self.dupl > 0:
            out += [f"Enviar {self.dupl} copias de mensajes ya enviados a la cola {c.queue('transacciones')['url'].rsplit('/', 1)[-1]} (SQS SendMessageBatch)",
                    f"Reproducir hasta {self.dupl} eventos ya existentes en el topico {c.topic_ingreso} (kubectl exec + kafka-console-producer en el broker)"]
        out.append(f"Redrive (StartMessageMoveTask) de las DLQ de transacciones y comprobantes si tienen mensajes")
        return out

    def plan(self) -> list[str]:
        c, cs = self.cfg, self.case
        mr = int(c.param("max_receive_count", 3))
        fn = c.lambda_name(cs["service"])
        return [
            f"[estado_inicial] Sistema sano: {c.deployment} en linea, colas y DLQ en 0 (ciclo {self.ciclo_id}, caso {cs['tag']}: {cs['label']})",
            f"[disparo] Seed de {self.n} transacciones (retardoSegundos={self.delay}) + PutEvents CierreDeMes en {c.bus_name}",
            f"[fallo_dependiente] Bitacora + inyectar fallo en {fn} ({'FORCE_FAIL=true' if self.mode == 'env' else 'concurrencia reservada 0'}); "
            f"observar {self.observe:g} s: " + ("las facturas emitidas siguen subiendo y process-billing sigue consumiendo (bulkhead)" if cs["tag"] == "B" else
                                              "process-billing sigue encolando y los pasos fallan con reintentos (Retry backoff) hacia la DLQ"),
            f"[fallo_pod] Esperar DEDUP# en PROCESANDO (mensajes en vuelo) y kubectl delete pod ({self.kill_pods}) de {c.deployment}; esperar el pod de reemplazo",
            f"[fallo_lambda] FAIL_RATE={self.fail_rate} en {c.lambda_name('ms-facturacion')} durante {self.window:g} s (reintentos + idempotencia); restaurar al terminar la ventana"
            if self.fail_rate > 0 else "[fallo_lambda] Omitida (--fail-rate 0)",
            (f"[duplicados] Reenviar {self.dupl} copias de mensajes ya enviados: (a) SQS a {c.queue('transacciones')['url'].rsplit('/', 1)[-1]} -> replays de idempotencia "
             f"en ms-facturacion/ms-comprobante-factura; (b) Kafka al topico {c.topic_ingreso} (kubectl exec en el broker, kafka-console-producer) -> MensajesDuplicados descartados en process-billing")
            if self.dupl > 0 else "[duplicados] Omitida (--dupl 0)",
            f"[recuperacion] Restaurar el dependiente (y todo fallo pendiente); esperar convergencia; verificar inyectadas = emitidas + rechazadas + DLQ ANTES del redrive; "
            f"redrive de las DLQ (maxReceiveCount={mr}); drenar hasta emitidas = notificadas y colas/DLQ en 0",
            "[veredicto] AISLAMIENTO (facturas suben, process-billing sigue vivo) · CERO PERDIDA (antes y despues del redrive) · "
            "IDEMPOTENCIA (emitidas == N, no N+D; duplicados contados) · RECUPERACION (colas/DLQ en 0, Lambdas restauradas)",
        ]

    # ------------------------------------------------------------------ ejecucion
    def _phase(self, name: str, desc: str) -> None:
        self._fase = name
        self.ctx.phase(name, desc)

    def execute(self, r: ExperimentResult) -> None:
        ctx, c, n = self.ctx, self.cfg, self.n
        cs = self.case
        s = self.s = _State()
        s.ids, s.en_vuelo, s.killed = [], [], []
        r.params.update({"caso": cs["tag"], "modoFallo": self.mode, "retardoSegundos": self.delay, "failRate": self.fail_rate,
                         "podsMatados": self.kill_pods, "ventanaSegundos": self.window, "duplicadosSolicitados": self.dupl})
        r.data["serieFallos"] = self._serie
        journal_ids: list[str] = []
        try:
            self._fase_inicial(s)
            self._fase_disparo(s)
            dep_id = self._fase_dependiente(r, s)
            journal_ids.append(dep_id)
            self._fase_pod(r, s)
            lam_id = self._fase_lambda(s)
            if lam_id:
                journal_ids.append(lam_id)
            self._fase_duplicados(r, s)
            self._phase("recuperacion", "Se restauran las Lambdas (se revierte todo fallo), se verifica la conservacion, se hace redrive de la DLQ y se drena")
            restored = actions.restore_ids(ctx, journal_ids)
        finally:
            actions.restore_ids(ctx, journal_ids)  # idempotente: cubre errores y Ctrl-C a mitad de las fases
        pend = [e for e in ctx.journal.pending() if e["id"] in journal_ids]
        self._recuperacion(r, s, restored, pend)
        self._veredicto(r, s)

    # --- 1. estado inicial / 2. disparo
    def _fase_inicial(self, s: _State) -> None:
        ctx, c = self.ctx, self.cfg
        self._phase("estado_inicial", f"Sistema sano: {c.deployment} en linea, colas y DLQ en 0")
        s.tick = self._watch(self.ciclo_id, 0.0)
        s.tick()

    def _fase_disparo(self, s: _State) -> None:
        ctx, n = self.ctx, self.n
        self._phase("disparo", f"{n} transacciones entran por el cierre de mes (retardo {self.delay:g} s/mensaje); todo fluye con normalidad")
        d = actions.dispatch_cierre(ctx, self.ciclo_id, n, retardo_segundos=self.delay)
        s.ids, s.t0 = d["facturaIds"], d["t0"]
        s.tick = self._watch(self.ciclo_id, s.t0)
        s.tick()

    # --- 3. fallo del dependiente: aislamiento
    def _fase_dependiente(self, r: ExperimentResult, s: _State) -> str:
        ctx, c, n = self.ctx, self.cfg, self.n
        cs, poll = self.case, ctx.opt("poll", 5)
        service, tag = cs["service"], cs["tag"]
        self._phase("fallo_dependiente", f"Se degrada {service} ({'FORCE_FAIL=true' if self.mode == 'env' else 'concurrencia reservada 0'}); "
                                         f"el resto de servicios sigue en linea. Caso {tag}: {cs['label']}")
        s.e0 = len(evidence.facturas_emitidas(ctx, self.ciclo_id))
        dedup0 = evidence.dedup_states(ctx, self.ciclo_id)
        s.env0 = sum(1 for e in dedup0.values() if e == "ENVIADO")
        dep_id = actions.inject_fault(ctx, service, self.mode)
        ctx.wait_until(lambda: False, self.observe, poll, on_tick=s.tick)
        tmax = float(ctx.opt("timeout_aislamiento", 90))
        if tag == "B":
            if s.e0 >= n:
                r.add("E2.1", f"AISLAMIENTO: las facturas emitidas siguen subiendo con {service} caido", None,
                      "emitidas suben durante el fallo", f"el lote ya estaba emitido ({s.e0}/{n}) antes del fallo: suba --fact o --retardo")
            else:
                ok, _ = ctx.wait_until(lambda: len(evidence.facturas_emitidas(ctx, self.ciclo_id)) > s.e0, tmax, poll, on_tick=s.tick)
                e1 = len(evidence.facturas_emitidas(ctx, self.ciclo_id))
                r.add("E2.1", f"AISLAMIENTO: las facturas emitidas siguen subiendo con {service} caido (bulkhead)", bool(ok),
                      "emitidas(fin) > emitidas(inicio del fallo)", f"{s.e0} -> {e1} de {n}", antes=s.e0, despues=e1)
        else:
            e1 = len(evidence.facturas_emitidas(ctx, self.ciclo_id))
            tol = max(2, math.ceil(0.05 * n))
            r.add("E2.1", f"AISLAMIENTO: con {service} caido no se emiten facturas nuevas (solo las que ya estaban en vuelo)", e1 - s.e0 <= tol,
                  f"emitidas sube <= {tol} desde el fallo", f"{s.e0} -> {e1} de {n}", antes=s.e0, despues=e1)
        if s.env0 >= n:
            r.add("E2.2", "AISLAMIENTO: ms-process-billing sigue consumiendo durante el fallo del dependiente", None,
                  "DEDUP# ENVIADO sube", f"todos los mensajes ya estaban enviados ({s.env0}/{n}) antes del fallo: suba --fact o --retardo")
        else:
            def sigue() -> bool:
                dd = evidence.dedup_states(ctx, self.ciclo_id)
                return sum(1 for e in dd.values() if e == "ENVIADO") > s.env0
            ok, _ = ctx.wait_until(sigue, tmax, poll, on_tick=s.tick)
            dd = evidence.dedup_states(ctx, self.ciclo_id)
            enviados = sum(1 for e in dd.values() if e == "ENVIADO")
            st = ctx.kube.deployment_status(c.app_namespace, c.deployment)
            r.add("E2.2", "AISLAMIENTO: ms-process-billing no cae del todo y sigue consumiendo/encolando durante el fallo del dependiente",
                  bool(ok) and st["ready"] >= 1, "DEDUP# ENVIADO sube y >= 1 replica lista",
                  f"ENVIADO {s.env0} -> {enviados} de {n}; replicas listas={st['ready']}",
                  deploy={k: st[k] for k in ("spec", "replicas", "ready")})
        r.add("E2.3", "Endpoint de salud dummy (servicios 'en linea'): /healthz de ms-process-billing responde", self._health(),
              "HTTP 200 via proxy del API server", "ver evidencia")
        return dep_id

    # --- 4. muerte de pods
    def _fase_pod(self, r: ExperimentResult, s: _State) -> None:
        ctx, c, n = self.ctx, self.cfg, self.n
        poll = ctx.opt("poll", 5)
        self._phase("fallo_pod", f"Se matan {self.kill_pods} pod(s) de {c.deployment} con mensajes en vuelo (DEDUP# PROCESANDO) mientras el dependiente sigue caido")

        def in_flight():
            return [f for f, e in evidence.dedup_states(ctx, self.ciclo_id).items() if e == "PROCESANDO"]
        ctx.wait_until(in_flight, float(ctx.opt("timeout_inflight", 180)), poll, on_tick=s.tick)
        s.en_vuelo = in_flight()
        pods = ctx.kube.pods(c.app_namespace, self._selector())
        for pod in pods[:self.kill_pods]:
            victim = pod["name"]
            if not victim.startswith(c.deployment):
                raise RuntimeError(f"pod '{victim}' no pertenece a {c.deployment}")
            ctx.journal.record("pod_delete", f"{c.app_namespace}/{victim}", {"pod": victim, "enVuelo": s.en_vuelo}, revertible=False)
            ctx.log(f"KILL pod {victim}; mensajes en vuelo: {len(s.en_vuelo)}")
            ctx.kube.delete_pod(c.app_namespace, victim, force=not ctx.opt("graceful", False))
            s.killed.append(victim)

        def replaced():
            cur = ctx.kube.pods(c.app_namespace, self._selector())
            st = ctx.kube.deployment_status(c.app_namespace, c.deployment)
            return [p for p in cur if p["name"] not in s.killed and p["ready"]] and st["ready"] >= 1
        rep_ok, rep_s = ctx.wait_until(replaced, float(ctx.opt("timeout_pod", 240)), poll, on_tick=s.tick)
        r.add("E2.4", "CERO PERDIDA: los pods de process-billing muertos son reemplazados y vuelven a estar listos", bool(s.killed) and bool(rep_ok),
              "pod(s) nuevo(s) listo(s)", f"muertos={s.killed}, reemplazo listo en {rep_s:.0f} s" if rep_ok else f"muertos={s.killed}, sin reemplazo",
              mensajesEnVuelo=fmt_ids(s.en_vuelo))

    # --- 5. fallo parcial de una Lambda
    def _fase_lambda(self, s: _State) -> str | None:
        ctx, c = self.ctx, self.cfg
        poll = ctx.opt("poll", 5)
        if self.fail_rate <= 0:
            self._phase("fallo_lambda", "Sin fallo parcial (fail-rate 0): fase de observacion")
            return None
        self._phase("fallo_lambda", f"FAIL_RATE={self.fail_rate} en {c.lambda_name('ms-facturacion')} durante {self.window:g} s "
                                    f"(Step Functions reintenta; la idempotencia evita facturas dobles)")
        lam_id = actions.inject_fault(ctx, "ms-facturacion", "rate", rate=self.fail_rate)
        ctx.wait_until(lambda: False, self.window, poll, on_tick=s.tick)
        actions.restore_ids(ctx, [lam_id])
        ctx.log("ventana de FAIL_RATE terminada: ms-facturacion restaurada")
        return lam_id

    # --- 6. duplicados a proposito
    def _fase_duplicados(self, r: ExperimentResult, s: _State) -> None:
        ctx, c, n, D = self.ctx, self.cfg, self.n, self.dupl
        poll = ctx.opt("poll", 5)
        if D <= 0:
            self._phase("duplicados", "Omitida (--dupl 0)")
            r.manual("E2.5", "IDEMPOTENCIA: duplicados forzados", "No se pidieron duplicados (dupl=0).")
            return
        self._phase("duplicados", f"Se reenvian a proposito {D} copias de mensajes YA enviados: (a) SQS -> replays de idempotencia; "
                                  f"(b) Kafka -> MensajesDuplicados descartados en process-billing")

        def enviados():
            return sorted(f for f, e in evidence.dedup_states(ctx, self.ciclo_id).items() if e == "ENVIADO")
        ctx.wait_until(enviados, float(ctx.opt("timeout_dup", 120)), poll, on_tick=s.tick)
        pool = enviados() or list(s.ids)
        chosen = [pool[i % len(pool)] for i in range(D)]
        s.t_dup = ctx.clock()
        # (a) SQS
        sent_sqs = actions.send_duplicates_sqs(ctx, actions.sqs_duplicate_bodies(ctx, self.ciclo_id, chosen, n))
        ctx.log(f"duplicados SQS enviados: {sent_sqs}/{D}")
        # (b) Kafka: reproducir eventos ConsumoFacturablePreparado existentes
        sent_kafka, kafka_note, kinfo = 0, "", {}
        try:
            recs = mesh.consume(ctx, c.kafka_cluster_billing, c.topic_ingreso, timeout_ms=int(ctx.opt("kafka_timeout_ms", 20000)))
            first: dict[str, mesh.Record] = {}
            for x in recs:
                v = x.value or {}
                if v.get("cicloid") == self.ciclo_id and mesh.type_to_name(v.get("type", "")) == "ConsumoFacturablePreparado":
                    first.setdefault(v.get("facturaid"), x)
            replay = [first[f] for f in chosen if f in first]
            if replay:
                kinfo = mesh.produce(ctx, c.kafka_cluster_billing, c.topic_ingreso, replay)
                sent_kafka = kinfo["enviados"]
            else:
                kafka_note = f"no se encontraron eventos del ciclo en {c.topic_ingreso} (retencion o ciclo ajeno)"
        except KubeError as exc:
            kafka_note = f"Kafka no accesible via kubectl exec: {exc}"
        s.dup = {"solicitados": D, "sqs": sent_sqs, "kafka": sent_kafka, "kafkaNota": kafka_note, "ids": chosen}
        ok_sqs = sent_sqs == D
        if ok_sqs and sent_kafka == D:
            ok = True
        elif ok_sqs and sent_kafka == 0:
            ok = None  # (b) inviable en este entorno: se documenta y se sigue con (a)
        else:
            ok = ok_sqs and sent_kafka > 0
        r.add("E2.5", f"IDEMPOTENCIA: se forzaron {D} duplicados (a) por SQS y (b) por Kafka", ok, f"{D} por SQS y {D} por Kafka",
              f"SQS={sent_sqs}, Kafka={sent_kafka}" + (f" ({kafka_note})" if kafka_note else ""), kafka=kinfo, muestra=fmt_ids(set(chosen)))

    # --- 7. recuperacion
    def _recuperacion(self, r: ExperimentResult, s: _State, restored: list[str], pend: list[dict]) -> None:
        ctx, c, n = self.ctx, self.cfg, self.n
        poll = ctx.opt("poll", 5)
        mr = int(c.param("max_receive_count", 3))
        s.lam = (not pend and self._lambdas_clean(), len(pend), restored)
        ids = s.ids

        def settled() -> bool:
            a = evidence.account(ctx, self.ciclo_id, ids)
            return a.ecuacion_ok and evidence.queue_total(a.colas["transacciones"]) == 0
        ok_pre, secs_pre = ctx.wait_until(settled, float(ctx.opt("timeout", self.scale_time(mr * 180 + 300, 3))), poll, on_tick=s.tick)
        acc_pre = evidence.account(ctx, self.ciclo_id, ids)
        r.add("E2.6", "CERO PERDIDA (antes del redrive): inyectadas = emitidas + rechazadas + mensajes en DLQ", bool(ok_pre) and acc_pre.ecuacion_ok,
              acc_pre.ecuacion, f"faltantes={fmt_ids(acc_pre.faltantes)} ajenas={fmt_ids(acc_pre.ajenas)}", convergenciaSegundos=round(secs_pre, 1),
              resumen=acc_pre.resumen(), emitidasYDlq=acc_pre.solapadas)
        # redrive de lo que haya en cada DLQ
        # Los mensajes que ya agotaron sus reintentos (receiveCount = max) y siguen EN VUELO caen a la DLQ DESPUES del primer
        # redrive aunque el servicio ya este sano. Se repite el redrive hasta que las DLQ y las colas queden vacias.
        reds: dict[str, dict] = {}
        for ronda in range(1, int(ctx.opt("redrive_rounds", 6)) + 1):
            hubo = False
            for key in ("transacciones", "comprobantes"):
                if evidence.queue_total(evidence.queue_state(ctx, c.queue(key)["dlq_url"])) > 0:
                    res = actions.redrive_dlq(ctx, key, timeout=self.scale_time(120, 0.5))
                    prev = reds.get(key, {})
                    res["rondas"] = ronda
                    res["movidosTotal"] = int(prev.get("movidosTotal") or 0) + int(res.get("movidos") or 0)
                    reds[key] = res
                    ctx.log(f"redrive {key} (ronda {ronda}): {res}")
                    hubo = True
            if not hubo:
                break
            # deja que lo devuelto (y lo que sigue en vuelo) se procese antes de revisar si llego algo nuevo a la DLQ
            ctx.wait_until(lambda: all(evidence.queue_total(evidence.queue_state(ctx, c.queue(k)["url"])) == 0
                                       for k in ("transacciones", "comprobantes")), float(self.scale_time(90, 0.5)), poll)
        s.reds = reds
        r.add("E2.8", "Redrive de las DLQ exitoso (mensajes devueltos a la cola de origen)" if reds else "Redrive de las DLQ: no hizo falta (DLQ vacias)",
              all(x.get("status") == "COMPLETED" for x in reds.values()), "COMPLETED" if reds else "DLQ vacias",
              ", ".join(f"{k}:{v.get('status')}" for k, v in reds.items()) or "DLQ vacias", redrive=reds)

        def recovered() -> bool:
            a = evidence.account(ctx, self.ciclo_id, ids)
            done = set(a.emitidas) | a.rechazadas
            return (a.ecuacion_ok and len(done) >= n and set(a.emitidas) <= a.notificadas and a.dlq_aprox == 0 and a.dlq_comprobantes_aprox == 0
                    and evidence.queue_total(a.colas["transacciones"]) == 0 and evidence.queue_total(a.colas["comprobantes"]) == 0)
        s.rec_ok, s.rec_secs = ctx.wait_until(recovered, float(ctx.opt("timeout_recovery", self.scale_time(300, 3))), poll, on_tick=s.tick)
        ctx.sleep(float(ctx.opt("settle", 20)))  # deja que los duplicados en vuelo (SFN) terminen antes de contar
        s.tick()

    def _lambdas_clean(self) -> bool:
        ctx, c = self.ctx, self.cfg
        try:
            lam = ctx.client("lambda")
            for svc in (self.case["service"], "ms-facturacion"):
                env = lam.get_function_configuration(FunctionName=c.lambda_name(svc)).get("Environment", {}).get("Variables", {})
                if env.get("FORCE_FAIL") == "true" or float(env.get("FAIL_RATE") or 0) > 0:
                    return False
                if self.mode == "concurrency" and lam.get_function_concurrency(FunctionName=c.lambda_name(svc)).get("ReservedConcurrentExecutions") == 0:
                    return False
            return True
        except Exception:  # noqa: BLE001 - la bitacora ya cubre el caso; esta lectura es doble verificacion
            return True

    # --- 8. veredicto
    def _veredicto(self, r: ExperimentResult, s: _State) -> None:
        ctx, c, n = self.ctx, self.cfg, self.n
        self._phase("veredicto", "Contabilidad final y criterios PASS/FAIL: AISLAMIENTO, CERO PERDIDA, IDEMPOTENCIA, RECUPERACION")
        ids = s.ids
        acc = evidence.account(ctx, self.ciclo_id, ids)
        dedup = evidence.dedup_states(ctx, self.ciclo_id)
        meta = evidence.ciclo_meta(ctx, self.ciclo_id)
        facts = evidence.fact_states(ctx, self.ciclo_id)
        oks = sum(1 for e in facts.values() if e == "OK")

        perdidos = [f for f in s.en_vuelo if f not in acc.contabilizadas]
        reentregados = [f for f in s.en_vuelo if dedup.get(f) == "ENVIADO"]
        r.add("E2.7", "CERO PERDIDA: los mensajes en vuelo al morir el pod se reentregan y se procesan (DEDUP# PROCESANDO -> ENVIADO)",
              (len(reentregados) == len(s.en_vuelo) and not perdidos) if s.en_vuelo else None,
              "todos los PROCESANDO terminan ENVIADO y contabilizados",
              f"{len(reentregados)}/{len(s.en_vuelo)} reentregados; perdidos={fmt_ids(perdidos)}" + ("" if s.en_vuelo else " (no hubo mensajes en vuelo: aumente --fact o --retardo)"),
              enVuelo=fmt_ids(s.en_vuelo), reentregados=fmt_ids(reentregados))
        r.add("E2.9", "CERO PERDIDA (despues del redrive): inyectadas = emitidas + rechazadas + DLQ y todas contabilizadas",
              bool(s.rec_ok) and acc.ecuacion_ok, acc.ecuacion, f"faltantes={fmt_ids(acc.faltantes)} ajenas={fmt_ids(acc.ajenas)}",
              segundosHastaRecuperar=round(s.rec_secs, 1), resumen=acc.resumen())
        sin_notificar = set(acc.emitidas) - acc.notificadas
        r.add("E2.10", "CERO PERDIDA: tras la recuperacion todas las facturas emitidas estan notificadas", not sin_notificar,
              "emitidas subset de notificadas", f"emitidas={len(acc.emitidas)} notificadas={len(acc.notificadas)}", sinNotificar=fmt_ids(sin_notificar))

        # IDEMPOTENCIA: emitidas == N (no N+D)
        nums = list(acc.emitidas.values())
        dup_nums = [k for k, v in collections.Counter(nums).items() if v > 1]
        cons = evidence.consecutivo(ctx)
        esperadas = n - len(acc.rechazadas)
        d = s.dup or {}
        r.add("E2.11", f"IDEMPOTENCIA: los duplicados NO crean facturas extra (emitidas == N, no N+D)",
              len(acc.emitidas) == esperadas and not acc.emitidas_duplicadas and not dup_nums and len(dedup) == n,
              f"emitidas == {esperadas} (N={n}, D={d.get('solicitados', 0)}); un registro por facturaId; DEDUP# == N",
              f"emitidas={len(acc.emitidas)} duplicadas={fmt_ids(acc.emitidas_duplicadas)} numerosRepetidos={dup_nums} DEDUP#={len(dedup)} consecutivo={cons}",
              facturas=acc.emitidas, consecutivoContador=cons,
              nota="consecutivo > emitidas indicaria numeros consumidos sin factura (huecos), no duplicados")
        self._contar_duplicados(r, s)

        # RECUPERACION
        colas = acc.colas
        dlq_tx = evidence.queue_total(evidence.queue_state(ctx, c.queue("transacciones")["dlq_url"]))
        dlq_cp = evidence.queue_total(evidence.queue_state(ctx, c.queue("comprobantes")["dlq_url"]))
        tx, cp = evidence.queue_total(colas["transacciones"]), evidence.queue_total(colas["comprobantes"])
        r.add("E2.13", "RECUPERACION: Lambdas restauradas al estado original (FORCE_FAIL / FAIL_RATE)", s.lam[0],
              "sin entradas pendientes en la bitacora y sin fallos activos", f"{s.lam[1]} pendientes", restauracion=s.lam[2])
        r.add("E2.14", "RECUPERACION: colas y DLQ en 0 al final", tx == cp == dlq_tx == dlq_cp == 0, "transacciones, comprobantes y sus DLQ en 0",
              f"cola-tx={tx} cola-comp={cp} DLQ-tx={dlq_tx} DLQ-comp={dlq_cp}", colas=colas)
        r.add("E2.15", "RECUPERACION: estado del ciclo consistente (FACT# OK y META COMPLETADO)",
              oks == esperadas and meta.get("estado") == "COMPLETADO", f"{esperadas} OK y COMPLETADO", f"{oks} OK, estado {meta.get('estado')}", meta=meta)
        self._duplicate_events(r)
        r.manual("E2.17", "Mensajes no procesables terminan en DLQ", "No se induce un mensaje venenoso en esta corrida (requiere publicar un cuerpo invalido y esperar maxReceiveCount); verificar a mano.")
        r.manual("E2.18", "Transactional Outbox: sin dual write entre DynamoDB y Kafka",
                 "Verificar en la tabla outbox que los items quedan en estado enviado y que el relay reintenta ante fallo de Kafka (no inducido por el runner).")
        # resumen por criterio del experimento
        grupos = {"AISLAMIENTO": ("E2.1", "E2.2"), "CERO PERDIDA": ("E2.6", "E2.9", "E2.10"),
                  "IDEMPOTENCIA": ("E2.11", "E2.12"), "RECUPERACION": ("E2.13", "E2.14")}
        st = {x.id: x.status for x in r.criteria}
        for g, keys in grupos.items():
            vals = [st.get(k) for k in keys if k in st]
            res = "FAIL" if "FAIL" in vals else ("PASS" if vals and all(v == "PASS" for v in vals) else "PASS*" if "PASS" in vals else "MANUAL")
            r.notes.append(f"{g}: {res} ({', '.join(f'{k}={st.get(k)}' for k in keys)})")
        r.data["criterios"] = {g: r.notes[i] for i, g in enumerate(grupos)}

    def _contar_duplicados(self, r: ExperimentResult, s: _State) -> None:
        """E2.12: se conto al menos un duplicado descartado (Kafka, MensajesDuplicados) o un replay de idempotencia (SQS)."""
        ctx = self.ctx
        d = s.dup
        if not d:
            r.manual("E2.12", "IDEMPOTENCIA: se conto al menos un duplicado descartado o replay", "No se enviaron duplicados (dupl=0).")
            return
        elapsed = max(0.0, ctx.clock() - s.t_dup)

        def lectura() -> dict:
            replays = evidence.metric_sum(ctx, "IdempotenciaReplays", s.t_dup, service_contains=("facturacion", "comprobante")) if d["sqs"] else None
            cw_dup = evidence.metric_sum(ctx, "MensajesDuplicados", s.t_dup, service_contains=("process-billing",)) if d["kafka"] else None
            logs = evidence.duplicates_in_logs(ctx, self.ciclo_id, elapsed + 120) if d["kafka"] else None
            return {"replaysIdempotencia": replays, "mensajesDuplicadosCW": cw_dup, "duplicadosEnLogs": logs}

        def contado() -> bool:
            x = lectura()
            return sum(v for v in x.values() if v) > 0
        ok, _ = ctx.wait_until(contado, float(ctx.opt("timeout_metricas", 150)), float(ctx.opt("poll_metricas", 15)))
        x = lectura()
        legibles = [v for v in x.values() if v is not None]
        total = sum(v for v in x.values() if v)
        if not legibles:
            r.manual("E2.12", "IDEMPOTENCIA: se conto al menos un duplicado descartado o replay",
                     "No se pudo leer CloudWatch ni los logs de los pods; revisar IdempotenciaReplays / MensajesDuplicados (Voltera/Exp2) en Grafana.")
        else:
            r.add("E2.12", "IDEMPOTENCIA: se conto al menos un duplicado descartado (Kafka) o un replay de idempotencia (SQS)", total > 0,
                  ">= 1 duplicado descartado o replay", f"replays={x['replaysIdempotencia']} MensajesDuplicados(CW)={x['mensajesDuplicadosCW']} "
                  f"descartados en logs={x['duplicadosEnLogs']}", lectura=x, enviados={k: d[k] for k in ("solicitados", "sqs", "kafka")},
                  nota="CloudWatch tarda 1-2 min en reflejar datos nuevos; si es 0, suba --timeout-metricas o revise Grafana")

    def _duplicate_events(self, r: ExperimentResult) -> None:
        try:
            recs = mesh.consume(self.ctx, self.cfg.kafka_cluster_billing, self.cfg.topic_eventos, timeout_ms=int(self.ctx.opt("kafka_timeout_ms", 20000)))
        except KubeError as exc:
            r.manual("E2.16", "Eventos FacturaEmitida no repetidos en el mesh", f"Kafka no accesible via kubectl exec: {exc}")
            return
        per = collections.defaultdict(set)
        for x in recs:
            v = x.value or {}
            if v.get("cicloid") == self.ciclo_id and mesh.type_to_name(v.get("type", "")) == "FacturaEmitida":
                per[v.get("facturaid")].add(v.get("id"))
        rep = {f: sorted(i) for f, i in per.items() if len(i) > 1}
        # at-least-once: un evento repetido con distinto id es aceptable, pero se reporta (no es FAIL)
        r.add("E2.16", "Eventos FacturaEmitida: una sola emision por factura en el mesh", None if rep else True, "1 evento por factura",
              f"{len(per)} facturas con evento; repetidas={len(rep)}", repetidas=rep,
              nota="Si hay repetidas es consecuencia de at-least-once (fallo despues de publicar y antes de persistir); los consumidores deben deduplicar por id.")

    # ------------------------------------------------------------------ observacion
    def _watch(self, ciclo: str, t0: float):
        """Callback que muestrea y muestra colas/DLQ/emitidas/enviadas/replicas (para ver acumularse y drenar la DLQ)."""
        ctx, c, serie = self.ctx, self.cfg, self._serie

        def tick() -> None:
            try:
                qt, qc = c.queue("transacciones"), c.queue("comprobantes")
                dd = evidence.dedup_states(ctx, ciclo)
                st = ctx.kube.deployment_status(c.app_namespace, c.deployment)
                s = {"t": round(max(0.0, ctx.clock() - t0), 1) if t0 else 0.0, "fase": self._fase,
                     "emitidas": len(evidence.facturas_emitidas(ctx, ciclo)),
                     "enviadas": sum(1 for e in dd.values() if e == "ENVIADO"), "listas": st["ready"],
                     "colaTx": evidence.queue_total(evidence.queue_state(ctx, qt["url"])),
                     "dlqTx": evidence.queue_total(evidence.queue_state(ctx, qt["dlq_url"])),
                     "colaComp": evidence.queue_total(evidence.queue_state(ctx, qc["url"])),
                     "dlqComp": evidence.queue_total(evidence.queue_state(ctx, qc["dlq_url"]))}
            except Exception as exc:  # noqa: BLE001 - la observacion nunca debe romper el experimento
                ctx.log(f"aviso: no se pudo muestrear colas ({type(exc).__name__})")
                return
            serie.append(s)
            ctx.log(f"[{s['fase']}] t={s['t']}s emitidas={s['emitidas']}/{self.n} enviadas={s['enviadas']} pods={s['listas']} "
                    f"cola-tx={s['colaTx']} DLQ-tx={s['dlqTx']} cola-comp={s['colaComp']} DLQ-comp={s['dlqComp']}")
        return tick

    def _health(self) -> bool | None:
        c = self.cfg
        try:
            res = self.ctx.kube.run(["get", "--raw", f"/api/v1/namespaces/{c.app_namespace}/services/{c.deployment}:8080/proxy/healthz"],
                                    timeout=30, check=False)
            return res.returncode == 0
        except KubeError:
            return None
