"""Mundo simulado para los tests: reloj falso + comportamiento del sistema escrito en moto (DynamoDB/SQS) y un kubectl falso.

El mundo lee la configuracion REAL de las Lambdas en moto (FORCE_FAIL), asi que la inyeccion/restauracion de fallos del
runner afecta de verdad al comportamiento simulado.
"""
from __future__ import annotations

import json
import math
import time
from decimal import Decimal

from runner.kube import Kube, KubeResult

KEBAB = {"CicloDeFacturacionIniciado": "ciclo-de-facturacion-iniciado", "TarifaValidada": "tarifa-validada",
         "CargoEnergeticoCalculado": "cargo-energetico-calculado", "FacturaEmitida": "factura-emitida",
         "NotificacionRegistrada": "notificacion-registrada", "FacturaNotificada": "factura-notificada",
         "ProcesoDeFacturacionCompletado": "proceso-de-facturacion-completado"}


class World:
    def __init__(self, ctx_factory, cfg, session, *, claim_every=2.0, proc_time=5.0, dlq_after=20.0, restart_time=10.0,
                 drop_event: str | None = None, duplicate_invoice: bool = False):
        self.cfg, self.session = cfg, session
        self.t = 1000.0
        self.claim_every, self.proc_time, self.dlq_after, self.restart_time = claim_every, proc_time, dlq_after, restart_time
        self.drop_event, self.duplicate_invoice = drop_event, duplicate_invoice
        self.f: dict[tuple[str, str], dict] = {}
        self.ddb = session.resource("dynamodb")
        self.sqs = session.client("sqs")
        self.lam = session.client("lambda")
        self.events: list[dict] = []  # {p, o, key, value}
        self.offsets: dict[int, int] = {}
        self.consec = 0
        self.paused_until = 0.0
        self.pod = "ms-process-billing-aaa"
        self.pod_seq = 0
        self.replicas, self.peak, self.done_at = 1, 1, None
        self.deleted: list[str] = []
        self.kube = Kube(runner=self._kubectl)
        self.stepping = False
        self.total: dict[str, int] = {}

    # --- reloj
    def clock(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.t += s
        self.step()

    # --- utilidades
    def _failing(self, service: str) -> bool:
        fn = self.cfg.lambda_name(service)
        c = self.lam.get_function_configuration(FunctionName=fn)
        env = c.get("Environment", {}).get("Variables", {})
        try:
            conc = self.lam.get_function_concurrency(FunctionName=fn).get("ReservedConcurrentExecutions")
        except Exception:  # noqa: BLE001
            conc = None
        return env.get("FORCE_FAIL") == "true" or conc == 0

    def _emit(self, name: str, ciclo: str, factura: str, **data) -> None:
        if name == self.drop_event and factura != "CICLO":
            return
        part = sum(map(ord, factura)) % 3
        off = self.offsets.get(part, 0)
        self.offsets[part] = off + 1
        ev = {"specversion": "1.0", "id": f"{ciclo}|{factura}|{name}|{len(self.events)}", "source": "/voltera/test",
              "type": f"com.voltera.facturacion.{KEBAB[name]}.v1", "subject": factura,
              "time": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(self.t)), "datacontenttype": "application/json",
              "cicloid": ciclo, "facturaid": factura, "data": {"cicloId": ciclo, "facturaId": factura, **data}}
        self.events.append({"p": part, "o": off, "key": factura, "value": ev})

    def _put(self, table_key, item):
        self.ddb.Table(self.cfg.table(table_key)).put_item(Item=item)

    def _fact(self, ciclo, factura, estado):
        pb = self.ddb.Table(self.cfg.table("process-billing"))
        old = pb.get_item(Key={"cicloId": ciclo, "sk": f"FACT#{factura}"}).get("Item")
        pb.put_item(Item={"cicloId": ciclo, "sk": f"FACT#{factura}", "estado": estado})
        meta = pb.get_item(Key={"cicloId": ciclo, "sk": "META"}).get("Item", {"cicloId": ciclo, "sk": "META", "totalUnidades": self.total[ciclo], "estado": "EN_CURSO"})
        cnt = {"OK": "emitidas", "RECHAZADA": "rechazadas", "FALLIDA": "fallidas"}
        if old:
            meta[cnt[old["estado"]]] = Decimal(int(meta.get(cnt[old["estado"]], 0)) - 1)
        meta[cnt[estado]] = Decimal(int(meta.get(cnt[estado], 0)) + 1)
        done = sum(int(meta.get(k, 0)) for k in cnt.values())
        if done >= int(meta["totalUnidades"]) and int(meta.get("fallidas", 0)) == 0 and meta["estado"] != "COMPLETADO":
            meta["estado"] = "COMPLETADO"
            self._emit("ProcesoDeFacturacionCompletado", ciclo, "CICLO", emitidas=int(meta.get("emitidas", 0)))
            self.done_at = self.t
        pb.put_item(Item=meta)

    # --- paso del sistema
    def step(self) -> None:
        if self.stepping:
            return
        self.stepping = True
        try:
            self._step()
        finally:
            self.stepping = False

    def _step(self) -> None:
        tx = self.ddb.Table(self.cfg.table("transacciones")).scan()["Items"]
        for it in sorted(tx, key=lambda i: i["facturaId"]):
            key = (it["cicloId"], it["facturaId"])
            if key not in self.f:
                idx = sum(1 for k in self.f if k[0] == it["cicloId"])
                self.total[it["cicloId"]] = sum(1 for i in tx if i["cicloId"] == it["cicloId"])
                self.f[key] = {"stage": "new", "t": self.t + idx * self.claim_every, "idx": idx, "ts": self.t}
                if idx == 0:
                    self._emit("CicloDeFacturacionIniciado", it["cicloId"], "CICLO", totalUnidades=self.total[it["cicloId"]])
        # redrive: mensajes que reaparecen en las colas de origen
        for qkey, stage in (("transacciones", "queued"), ("comprobantes", "notify")):
            q = self.cfg.queue(qkey)
            while True:
                m = self.sqs.receive_message(QueueUrl=q["url"], MaxNumberOfMessages=10).get("Messages", [])
                if not m:
                    break
                for x in m:
                    b = json.loads(x["Body"])
                    st = self.f.get((b["cicloId"], b["facturaId"]))
                    if st:
                        st.update(stage=stage, t=self.t, since=self.t)
                    self.sqs.delete_message(QueueUrl=q["url"], ReceiptHandle=x["ReceiptHandle"])
        for (ciclo, fid), st in self.f.items():
            if self.t < self.paused_until or self.t < st["t"]:
                continue
            body = json.dumps({"cicloId": ciclo, "facturaId": fid})
            pb = self.ddb.Table(self.cfg.table("process-billing"))
            s = st["stage"]
            if s == "new":
                pb.put_item(Item={"cicloId": ciclo, "sk": f"DEDUP#{fid}", "estado": "PROCESANDO"})
                st.update(stage="claimed", t=self.t + self.proc_time)
            elif s == "claimed":
                pb.put_item(Item={"cicloId": ciclo, "sk": f"DEDUP#{fid}", "estado": "ENVIADO"})
                st.update(stage="queued", t=self.t + 1)
            elif s == "queued":
                if self._failing("ms-tarifas"):
                    self.sqs.send_message(QueueUrl=self.cfg.queue("transacciones")["dlq_url"], MessageBody=body)
                    st.update(stage="dlq", t=self.t)
                else:
                    self._emit("TarifaValidada", ciclo, fid)
                    self._emit("CargoEnergeticoCalculado", ciclo, fid)
                    self.consec += 1
                    num = f"FV-{self.consec:06d}"
                    data = {"aprobado": True, "estado": "EMITIDA", "facturaId": fid, "cicloId": ciclo, "numeroFactura": num}
                    self._put("idem-facturacion", {"facturaId": f"ms-facturacion.run#{fid}", "status": "COMPLETED", "data": json.dumps(data)})
                    if self.duplicate_invoice:
                        self._put("idem-facturacion", {"facturaId": f"ms-facturacion.run#dup-{fid}", "status": "COMPLETED", "data": json.dumps(data)})
                    self._put("idem-facturacion", {"facturaId": "__CONSECUTIVO__", "consecutivo": self.consec})
                    self._emit("FacturaEmitida", ciclo, fid, numeroFactura=num)
                    st.update(stage="notify", t=self.t, since=self.t)
            elif s == "notify":
                if self._failing("ms-comprobante-factura"):
                    if self.t - st.get("since", self.t) >= self.dlq_after:
                        self.sqs.send_message(QueueUrl=self.cfg.queue("comprobantes")["dlq_url"], MessageBody=body)
                        self._fact(ciclo, fid, "FALLIDA")
                        st.update(stage="cdlq")
                else:
                    self._emit("NotificacionRegistrada", ciclo, fid)
                    self._put("idem-comprobante", {"facturaId": f"ms-comprobante.run#{fid}", "status": "COMPLETED",
                                                   "data": json.dumps({"facturaId": fid, "estado": "NOTIFICADA"})})
                    self._emit("FacturaNotificada", ciclo, fid)
                    self._fact(ciclo, fid, "OK")
                    st.update(stage="done")
        # replicas (KEDA simulado)
        pend = sum(1 for s in self.f.values() if s["stage"] in ("new",))
        if pend:
            self.replicas = min(5, max(self.replicas, math.ceil(pend / 2) + 0))
            self.peak = max(self.peak, self.replicas)
        elif all(s["stage"] != "new" for s in self.f.values()) and self.f and self.done_at and self.t - self.done_at > 30:
            self.replicas = 1
        elif self.f and not pend and self.done_at is None and all(s["stage"] in ("done", "cdlq", "dlq") for s in self.f.values()):
            self.done_at = self.t

    # --- kubectl falso
    def _pods(self):
        return [{"metadata": {"name": self.pod, "uid": self.pod}, "status": {"phase": "Running", "containerStatuses": [{"ready": self.t >= self.paused_until}]}}]

    def _kubectl(self, args: list[str], timeout: float) -> KubeResult:
        a = [x for x in args if x != "--context"]
        j = lambda o: KubeResult(0, json.dumps(o))  # noqa: E731
        if a[:2] == ["get", "deploy"]:
            ready = self.replicas if self.t >= self.paused_until else 0
            return j({"spec": {"replicas": self.replicas, "template": {"spec": {"containers": [{"env": [{"name": "KAFKA_CONSUMER_GROUP", "value": "pb-group"}]}]}}},
                      "status": {"replicas": self.replicas, "readyReplicas": ready, "availableReplicas": ready}})
        if a[:2] == ["get", "hpa"]:
            return j({"status": {"desiredReplicas": self.replicas}})
        if a[:2] == ["get", "pods"] and "jsonpath" in " ".join(a):
            return KubeResult(0, "dominios-dominios-nodes-0" if "cluster=dominios" in " ".join(a) else "billing-billing-nodes-0")
        if a[:2] == ["get", "pods"]:
            return j({"items": self._pods()})
        if a[:2] == ["get", "--raw"]:
            return KubeResult(0, "ok")
        if a[:2] == ["delete", "pod"]:
            self.deleted.append(a[2])
            self.pod_seq += 1
            self.pod = f"ms-process-billing-new{self.pod_seq}"
            self.paused_until = self.t + self.restart_time
            return KubeResult(0, f'pod "{a[2]}" deleted')
        if a[0] == "exec":
            cmd = " ".join(a)
            if "kafka-consumer-groups" in cmd:
                pend = sum(1 for s in self.f.values() if s["stage"] == "new")
                return KubeResult(0, f"GROUP TOPIC PARTITION CURRENT-OFFSET LOG-END-OFFSET LAG CONSUMER-ID HOST CLIENT-ID\npb-group t 0 1 2 {pend} - - -\n")
            if "kafka-console-consumer" in cmd:
                evs = self.events
                if "--partition" in a:
                    p = int(a[a.index("--partition") + 1])
                    off = int(a[a.index("--offset") + 1])
                    mx = int(a[a.index("--max-messages") + 1]) if "--max-messages" in a else 10**9
                    evs = [e for e in evs if e["p"] == p and e["o"] >= off][:mx]
                lines = [f"Partition:{e['p']}\tOffset:{e['o']}\tcicloId:{e['value']['cicloid']},facturaId:{e['value']['facturaid']}\t{e['key']}\t{json.dumps(e['value'])}"
                         for e in evs]
                return KubeResult(0, "\n".join(lines) + "\n")
            if "curl" in cmd:
                return KubeResult(7, "", "curl: (7) no route")
        return KubeResult(1, "", f"comando no simulado: {args}")
