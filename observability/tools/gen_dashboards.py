#!/usr/bin/env python3
"""Genera los dashboards JSON de Grafana (observability/dashboards/*.json).

Uso:  python3 tools/gen_dashboards.py [--prefix voltera-exp2] [--cluster voltera-exp2-eph] [--namespace voltera]
Solo usa metricas/campos que existen en el codigo (services/, libs/) o en AWS; lo que no existe se marca
como panel "PENDIENTE DE METRICA" y esta registrado como incidencia en ORQUESTACION.md.
"""
import argparse
import json
import os

ap = argparse.ArgumentParser()
ap.add_argument("--prefix", default="voltera-exp2")
ap.add_argument("--cluster", default="voltera-exp2-eph")
ap.add_argument("--namespace", default="voltera", help="namespace K8s de ms-process-billing")
ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "dashboards"))
A = ap.parse_args()
P, CL, KNS = A.prefix, A.cluster, A.namespace

CW = {"type": "cloudwatch", "uid": "cloudwatch"}
XR = {"type": "grafana-x-ray-datasource", "uid": "xray"}
NS = "Voltera/Exp2"
CI = "ContainerInsights"

Q_TX, Q_TX_DLQ = f"{P}-transacciones", f"{P}-transacciones-dlq"
Q_CO, Q_CO_DLQ = f"{P}-comprobantes", f"{P}-comprobantes-dlq"
LAMBDAS = ["ms-orchestrator-billing", "outbox-relay", "ms-tarifas", "ms-calculo-consumo-neto", "ms-facturacion", "ms-comprobante-factura"]
LG = {s: f"/aws/lambda/{P}-{s}" for s in LAMBDAS}
LG_SFN = f"/aws/vendedlogs/states/{P}-facturacion"
LG_STEPS = [LG[s] for s in ("ms-tarifas", "ms-calculo-consumo-neto", "ms-facturacion", "ms-comprobante-factura")]
LG_PB = f"/aws/containerinsights/{CL}/application"  # logs JSON de ms-process-billing (stdout via Fluent Bit)
LG_ALL_LAMBDA = [LG[s] for s in LAMBDAS]



# Etiquetas del eje Y (significado y unidad). El eje X de los timeseries es siempre el tiempo (hora local del navegador).
_YLABELS = [
    ("lag", "Mensajes pendientes (lag)"), ("replicas", "Réplicas (pods)"), ("tiempo por mensaje", "Segundos por mensaje"),
    ("throughput", "Facturas por minuto"), ("avance", "Facturas acumuladas"), ("cola de transacciones", "Mensajes en cola"),
    ("backlog", "Mensajes en cola"), ("dlq: visibles", "Mensajes (DLQ visibles vs. movidos)"), ("dlq", "Mensajes en la DLQ"),
    ("redrive", "Facturas"), ("ejecuciones step", "Ejecuciones por minuto"), ("errores del relay", "Errores por minuto"),
    ("errores", "Errores por minuto"), ("throttles", "Throttles por minuto"), ("concurrencia", "Ejecuciones concurrentes"),
    ("duracion p95", "Milisegundos (p95)"), ("fallos de notificacion", "Fallos por minuto"), ("healthcheck", "Salud (1 = OK, 0 = caído)"),
    ("saldo", "Saldo: inyectadas - emitidas - rechazos - DLQ"), ("reentregas kafka", "Mensajes reentregados"),
    ("reentregas", "Mensajes reentregados"), ("duplicados", "Mensajes duplicados"), ("replays", "Replays de idempotencia"),
    ("outbox", "Eventos publicados"), ("facturas emitidas", "Facturas"), ("eventos esperados", "Eventos acumulados"),
    ("meshpublishfailures", "Fallos de publicación al mesh"), ("fallos de publicacion", "Fallos de publicación al mesh"),
]


def y_label(title, unit):
    t = title.lower()
    for key, label in _YLABELS:
        if key in t:
            return label
    return {"ms": "Milisegundos", "s": "Segundos", "percent": "Porcentaje"}.get(unit, "Cantidad")

# ------------------------------------------------------------------ consultas
def m(refid, ns, metric, dims, stat="Sum", period=60, label=None, mid=None, hide=False):
    q = {"datasource": CW, "refId": refid, "queryMode": "Metrics", "metricQueryType": 0, "metricEditorMode": 0,
         "namespace": ns, "metricName": metric, "dimensions": dims, "statistic": stat, "period": str(period),
         "region": "default", "matchExact": True, "id": mid or "", "expression": "", "label": label or metric, "hide": hide}
    return q


def expr(refid, expression, label=None, period=60, mid="", hide=False):
    return {"datasource": CW, "refId": refid, "queryMode": "Metrics", "metricQueryType": 0, "metricEditorMode": 1,
            "expression": expression, "id": mid, "period": str(period), "region": "default", "label": label or "", "hide": hide,
            "namespace": "", "metricName": "", "dimensions": {}, "statistic": "Average", "matchExact": True}


def search(refid, namespace, dimkeys, metric, stat, text=P, period=60, label="${PROP('Dim.FunctionName')}"):
    e = f"SEARCH('{{{namespace},{dimkeys}}} MetricName=\"{metric}\" {text}', '{stat}', {period})"
    return expr(refid, e, label=label, period=period)


def logs(refid, query, groups):
    return {"datasource": CW, "refId": refid, "queryMode": "Logs", "region": "default", "id": "", "expression": query,
            "logGroupNames": groups, "logGroups": [], "statsGroups": []}


def xr(refid, qtype, **kw):
    return {"datasource": XR, "refId": refid, "queryType": qtype, "region": "default", **kw}


# ------------------------------------------------------------------ paneles
class Board:
    def __init__(self, uid, title, desc, tags, extra_vars=()):
        self.uid, self.title, self.desc, self.tags = uid, title, desc, tags
        self.panels, self.x, self.y, self.rowh, self.nid = [], 0, 0, 0, 1
        self.extra_vars = list(extra_vars)

    def _place(self, w, h):
        if self.x + w > 24:
            self.x, self.y, self.rowh = 0, self.y + self.rowh, 0
        pos = {"h": h, "w": w, "x": self.x, "y": self.y}
        self.x += w
        self.rowh = max(self.rowh, h)
        return pos

    def row(self, title):
        self.x, self.y, self.rowh = 0, self.y + self.rowh, 0
        self.panels.append({"id": self._id(), "type": "row", "title": title, "collapsed": False,
                            "gridPos": {"h": 1, "w": 24, "x": 0, "y": self.y}, "panels": []})
        self.y += 1

    def _id(self):
        i = self.nid
        self.nid += 1
        return i

    def add(self, ptype, title, targets, w=12, h=8, desc="", ds=CW, defaults=None, overrides=None, options=None, transformations=None):
        p = {"id": self._id(), "type": ptype, "title": title, "description": desc, "datasource": ds,
             "gridPos": self._place(w, h), "targets": targets,
             "fieldConfig": {"defaults": defaults or {}, "overrides": overrides or []}, "options": options or {}}
        if transformations:
            p["transformations"] = transformations
        self.panels.append(p)
        return p

    def ts(self, title, targets, unit="short", stack=False, w=12, h=8, desc="", min_=None, thresholds=None, ds=CW):
        ylab = y_label(title, unit)
        title = f"{title}  (eje X: hora)"
        desc = (desc + " " if desc else "") + f"Eje Y: {ylab}. Eje X: tiempo (hora local)."
        d = {"unit": unit, "custom": {"axisLabel": ylab, "drawStyle": "line", "lineWidth": 2, "fillOpacity": 15 if stack else 8, "showPoints": "never",
                                       "spanNulls": True, "stacking": {"mode": "normal" if stack else "none", "group": "A"}}}
        if min_ is not None:
            d["min"] = min_
        if thresholds:
            d["thresholds"] = {"mode": "absolute", "steps": thresholds}
            d["custom"]["thresholdsStyle"] = {"mode": "line"}
        return self.add("timeseries", title, targets, w, h, desc, ds, d,
                        options={"legend": {"displayMode": "table", "placement": "bottom", "calcs": ["lastNotNull", "max"]},
                                 "tooltip": {"mode": "multi", "sort": "desc"}})

    def stat(self, title, targets, calc="lastNotNull", unit="short", w=4, h=4, desc="", steps=None, color_mode="background", decimals=0):
        steps = steps or [{"color": "green", "value": None}]
        d = {"unit": unit, "decimals": decimals, "thresholds": {"mode": "absolute", "steps": steps}, "color": {"mode": "thresholds"},
             "noValue": "0"}
        return self.add("stat", title, targets, w, h, desc, CW, d,
                        options={"reduceOptions": {"calcs": [calc], "fields": "", "values": False}, "colorMode": color_mode,
                                 "graphMode": "none", "textMode": "value_and_name", "justifyMode": "center"})

    def table(self, title, targets, w=12, h=8, desc="", ds=CW, transformations=None):
        return self.add("table", title, targets, w, h, desc, ds, {"custom": {"align": "auto"}},
                        options={"showHeader": True, "cellHeight": "sm"}, transformations=transformations)

    def logs(self, title, targets, w=24, h=10, desc=""):
        return self.add("logs", title, targets, w, h, desc, CW, {}, options={"showTime": True, "wrapLogMessage": True, "sortOrder": "Ascending",
                                                                                "enableLogDetails": True})

    def text(self, title, md, w=24, h=4):
        p = self.add("text", title, [], w, h, "", None, {}, options={"mode": "markdown", "content": md})
        p.pop("datasource", None)
        return p

    def pending(self, title, metric, owner, incident, w=12, h=5, proxy=""):
        md = (f"**PENDIENTE DE METRICA** — `{metric}`\n\nEsta serie no existe todavia en CloudWatch. "
              f"Incidencia **OBS-{incident - 8}** (para `{owner}`) en `ORQUESTACION.md`.\n\n{proxy}")
        return self.text(f"[PENDIENTE] {title}", md, w, h)

    def var_text(self, name, label, default, desc=""):
        return {"type": "textbox", "name": name, "label": label, "query": default, "current": {"text": default, "value": default},
                "options": [{"selected": True, "text": default, "value": default}], "description": desc, "hide": 0}

    def build(self):
        cyc = self.var_text("cicloId", "cicloId", ".", "Regex sobre cicloId para Logs Insights; '.' = todos los ciclos. Las metricas EMF no llevan cicloId (dimension no disponible).")
        sfn = {"type": "query", "name": "sfn", "label": "State machine", "datasource": CW,
               "query": {"queryType": "dimensionValues", "region": "default", "namespace": "AWS/States", "metricName": "ExecutionsStarted",
                         "dimensionKey": "StateMachineArn", "dimensionFilters": {}, "refId": "VarSfn"},
               "regex": f"/.*{P}-facturacion$/", "refresh": 2, "includeAll": False, "multi": False, "sort": 0, "hide": 0,
               "current": {}, "options": []}
        return {
            "uid": self.uid, "title": self.title, "description": self.desc, "tags": ["voltera", "exp2"] + self.tags,
            "schemaVersion": 39, "version": 1, "editable": True, "graphTooltip": 1, "refresh": "30s",
            "time": {"from": "now-1h", "to": "now"}, "timepicker": {"refresh_intervals": ["10s", "30s", "1m", "5m"]},
            "timezone": "browser", "fiscalYearStartMonth": 0, "liveNow": False,
            "templating": {"list": [cyc, sfn] + self.extra_vars},
            "annotations": {"list": [{"builtIn": 1, "datasource": {"type": "grafana", "uid": "-- Grafana --"}, "enable": True,
                                      "hide": True, "iconColor": "rgba(0, 211, 255, 1)", "name": "Annotations & Alerts", "type": "dashboard"}]},
            "links": [{"type": "dashboards", "tags": ["voltera"], "asDropdown": True, "title": "Dashboards Voltera", "includeVars": False,
                       "keepTime": True}],
            "panels": self.panels,
        }

    def save(self, fname):
        path = os.path.join(A.out, fname)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.build(), f, indent=2, ensure_ascii=False)
            f.write("\n")


# ------------------------------------------------------------------ bloques reutilizables
def svc(s):
    return {"service": s}


def q_loss_balance(prefix_id="b"):
    """Saldo de conservacion acumulado: inyectadas - emitidas - rechazadas(negocio) - DLQ."""
    return [
        m("A", NS, "UnidadesEnOutbox", svc("ms-orchestrator-billing"), "Sum", 60, "inyectadas", "inj", True),
        m("B", NS, "FacturasEmitidas", svc("ms-facturacion"), "Sum", 60, "emitidas", "em", True),
        m("C", NS, "TarifasRechazadas", svc("ms-tarifas"), "Sum", 60, "rech_tarifa", "rt", True),
        m("D", NS, "CalculosRechazados", svc("ms-calculo-consumo-neto"), "Sum", 60, "rech_calculo", "rc", True),
        m("E", NS, "EmisionesRechazadas", svc("ms-facturacion"), "Sum", 60, "rech_emision", "re", True),
        m("F", "AWS/SQS", "ApproximateNumberOfMessagesVisible", {"QueueName": Q_TX_DLQ}, "Maximum", 60, "dlq", "dlq", True),
        expr("G", "RUNNING_SUM(FILL(inj,0)) - RUNNING_SUM(FILL(em,0)) - RUNNING_SUM(FILL(rt,0)) - RUNNING_SUM(FILL(rc,0)) - RUNNING_SUM(FILL(re,0)) - FILL(dlq,0)",
             "saldo (en vuelo + perdidas)", 60, "saldo"),
    ]


def cumulative(refid, ns, metric, dims, label, mid, stat="Sum"):
    return [m(refid + "m", ns, metric, dims, stat, 60, label, mid, True), expr(refid, f"RUNNING_SUM(FILL({mid},0))", label, 60)]


def lambdas_health(b, with_duration=False):
    b.ts("Errores por Lambda", [search("A", "AWS/Lambda", "FunctionName", "Errors", "Sum")], desc="AWS/Lambda Errors (todas las Lambdas del experimento).")
    b.ts("Throttles por Lambda", [search("A", "AWS/Lambda", "FunctionName", "Throttles", "Sum")],
         desc="Throttles: con concurrencia reservada en 0 (Exp.2) o saturacion (Exp.1).")
    b.ts("Concurrencia (ConcurrentExecutions, max)", [search("A", "AWS/Lambda", "FunctionName", "ConcurrentExecutions", "Maximum")])
    if with_duration:
        b.ts("Duracion p95 por Lambda (ms)", [search("A", "AWS/Lambda", "FunctionName", "Duration", "p95")], unit="ms")
    else:
        b.ts("Invocaciones por Lambda", [search("A", "AWS/Lambda", "FunctionName", "Invocations", "Sum")])


STEP_LOGS_Q = ('fields @timestamp, service, message, cicloId, facturaId, aprobado, numero, level\n'
               '| filter cicloId like /$cicloId/\n| sort @timestamp asc\n| limit 500')

# =========================================================== 00 ciclo en vivo
b = Board("voltera-ciclo-vivo", "Voltera Exp2 - Ciclo en vivo", "Resumen en vivo del ciclo de facturacion: avance, cola, DLQ y salud.", ["resumen"])
b.text("Como leerlo", "Resumen del ciclo de facturacion de fin de mes. Metricas EMF (`Voltera/Exp2`, dimension `service`) no llevan `cicloId`: "
       "los totales corresponden al **rango de tiempo** seleccionado (ajusta el rango a la corrida). El filtro `cicloId` aplica a paneles de Logs Insights. "
       "Saldo = inyectadas - emitidas - rechazadas de negocio - DLQ; en vuelo es transitorio, **debe converger a 0**.", h=3)
b.row("Avance del ciclo")
b.stat("Inyectadas (outbox)", [m("A", NS, "UnidadesEnOutbox", svc("ms-orchestrator-billing"), "Sum", 60)], calc="sum", w=4,
       desc="Metrica UnidadesEnOutbox del orchestrator.")
b.stat("Facturas emitidas", [m("A", NS, "FacturasEmitidas", svc("ms-facturacion"), "Sum", 60)], calc="sum", w=4)
b.stat("Facturas notificadas", [m("A", NS, "FacturasNotificadas", svc("ms-comprobante-factura"), "Sum", 60)], calc="sum", w=4)
b.stat("Rechazos de negocio", [m("A", NS, "TarifasRechazadas", svc("ms-tarifas"), "Sum", 60, "tarifa", "rt", True),
                               m("B", NS, "CalculosRechazados", svc("ms-calculo-consumo-neto"), "Sum", 60, "calculo", "rc", True),
                               m("C", NS, "EmisionesRechazadas", svc("ms-facturacion"), "Sum", 60, "emision", "re", True),
                               expr("D", "FILL(rt,0)+FILL(rc,0)+FILL(re,0)", "rechazos")], calc="sum", w=4)
b.stat("DLQ transacciones", [m("A", "AWS/SQS", "ApproximateNumberOfMessagesVisible", {"QueueName": Q_TX_DLQ}, "Maximum", 60)], calc="lastNotNull", w=4,
       steps=[{"color": "green", "value": None}, {"color": "red", "value": 1}])
b.stat("DLQ comprobantes", [m("A", "AWS/SQS", "ApproximateNumberOfMessagesVisible", {"QueueName": Q_CO_DLQ}, "Maximum", 60)], calc="lastNotNull", w=4,
       steps=[{"color": "green", "value": None}, {"color": "red", "value": 1}])
b.stat("Saldo de conservacion (en vuelo + perdidas)", q_loss_balance(), calc="lastNotNull", w=6, h=5,
       steps=[{"color": "green", "value": None}, {"color": "orange", "value": 1}],
       desc="RUNNING_SUM(inyectadas) - RUNNING_SUM(emitidas) - rechazos - DLQ. Naranja = trabajo en vuelo o perdida; al terminar la corrida debe ser 0.")
b.ts("Avance acumulado", cumulative("A", NS, "UnidadesEnOutbox", svc("ms-orchestrator-billing"), "inyectadas", "i") +
     cumulative("B", NS, "FacturasEmitidas", svc("ms-facturacion"), "emitidas", "e") +
     cumulative("C", NS, "FacturasNotificadas", svc("ms-comprobante-factura"), "notificadas", "n"), w=18, h=5)
b.row("Estado del ciclo")
b.stat("Ciclos completados", [m("A", NS, "CiclosCompletados", svc("ms-process-billing"), "Sum", 60)], calc="sum", w=4)
b.stat("Ciclos fallidos", [m("A", NS, "CiclosFallidos", svc("ms-process-billing"), "Sum", 60)], calc="sum", w=4, steps=[{"color": "green", "value": None}, {"color": "red", "value": 1}])
b.stat("Duracion del ciclo", [m("A", NS, "CicloDuracionSegundos", svc("ms-process-billing"), "Maximum", 60)], calc="lastNotNull", unit="s", w=4,
       steps=[{"color": "green", "value": None}, {"color": "red", "value": 120}])
b.stat("Fallos de publicacion al mesh", [expr("A", "SEARCH('{Voltera/Exp2,service} MetricName=\"MeshPublishFailures\"', 'Sum', 60)", "fallos")], calc="sum", w=4,
       steps=[{"color": "green", "value": None}, {"color": "orange", "value": 1}])
b.stat("Health ms-process-billing", [expr("A", "SEARCH('{Voltera/Exp2,pod,service} MetricName=\"HealthCheckOk\" service=\"ms-process-billing\"', 'Minimum', 60)", "salud")], calc="lastNotNull", w=4,
       steps=[{"color": "red", "value": None}, {"color": "green", "value": 1}])
b.row("Colas y cómputo")
b.ts("Cola de transacciones", [m("A", "AWS/SQS", "ApproximateNumberOfMessagesVisible", {"QueueName": Q_TX}, "Maximum", 60, "visibles"),
                               m("B", "AWS/SQS", "ApproximateNumberOfMessagesNotVisible", {"QueueName": Q_TX}, "Maximum", 60, "en vuelo")], w=8)
b.ts("Replicas ms-process-billing", [m("A", CI, "service_number_of_running_pods", {"ClusterName": CL, "Namespace": KNS, "Service": "ms-process-billing"}, "Maximum", 60, "replicas")],
     w=8, min_=0, desc="Container Insights (add-on amazon-cloudwatch-observability). KEDA 1..5.")
b.ts("Ejecuciones Step Functions", [m("A", "AWS/States", "ExecutionsStarted", {"StateMachineArn": "$sfn"}, "Sum", 60, "iniciadas"),
                                    m("B", "AWS/States", "ExecutionsSucceeded", {"StateMachineArn": "$sfn"}, "Sum", 60, "exitosas"),
                                    m("C", "AWS/States", "ExecutionsFailed", {"StateMachineArn": "$sfn"}, "Sum", 60, "fallidas")], w=8)
b.row("Salud")
b.ts("Errores por Lambda", [search("A", "AWS/Lambda", "FunctionName", "Errors", "Sum")], w=12)
b.ts("Throttles por Lambda", [search("A", "AWS/Lambda", "FunctionName", "Throttles", "Sum")], w=12)
b.table("Ultimos eventos del ciclo (logs estructurados)", [logs("A", STEP_LOGS_Q.replace("sort @timestamp asc", "sort @timestamp desc").replace("limit 500", "limit 50"), LG_STEPS)], w=24, h=9,
        desc="Logs Insights sobre los logs JSON de Powertools (campos cicloId/facturaId).")
b.save("00-ciclo-en-vivo.json")

# =========================================================== exp1
b = Board("voltera-exp1-absorcion", "Exp1 - Absorcion del pico (autoescalado)", "Queue-Based Load Leveling + KEDA: backlog, replicas, SLA del lote y cero perdidas.",
          ["exp1"], extra_vars=[{"type": "constant", "name": "slaSeg", "label": "SLA del lote (s)", "query": "120", "hide": 2,
                                  "current": {"text": "120", "value": "120"}, "options": [{"selected": True, "text": "120", "value": "120"}]}])
b.text("Hipotesis", "EventBridge dispara el cierre; se inyectan N transacciones en Kafka; KEDA escala `ms-process-billing` de 1 a n segun el lag, drena el backlog dentro del SLA "
       "(10 facturas en <= 2 min) y vuelve a 1 replica. **Cero perdidas por saturacion.** Escala <= 10: valida comportamiento, no capacidad.", h=3)
b.row("Backlog y escalado")
b.ts("Lag del consumidor Kafka (grupo ms-process-billing)",
     [m("Am", "Voltera/Exp2", "KafkaConsumerLag", {"service": "ms-process-billing", "topic": "voltera.consumo-facturable-preparado"}, "Sum", 60, "muestras sumadas", "lag", True),
      expr("A", "lag / 6", "lag total (mensajes pendientes)", 60)],
     w=12, h=8, min_=0, desc="KafkaConsumerLag lo publica cada pod con el lag de sus particiones cada 10 s. En un minuto hay 6 muestras por pod, asi que Sum/6 = lag total del grupo "
     "(asume METRICS_FLUSH_SECONDS=10). Aparece 1-2 min despues por la latencia de CloudWatch.")
b.ts("Replicas ms-process-billing (KEDA)", [m("A", CI, "service_number_of_running_pods", {"ClusterName": CL, "Namespace": KNS, "Service": "ms-process-billing"}, "Maximum", 60, "replicas")],
     w=12, h=8, min_=0, desc="ContainerInsights/service_number_of_running_pods. Deben subir con el lag y bajar a 1 al drenar.")
b.row("Tiempo del lote vs SLA")
b.table("Tiempo del lote por cicloId (inicio de ciclo -> ultima factura procesada)",
        [logs("A", 'fields toMillis(@timestamp) as t\n| filter cicloId like /$cicloId/ and (message = "ciclo iniciado" or message = "factura procesada")\n'
                   '| stats min(t) as ini, max(t) as fin, count(*) as eventos by cicloId\n| fields cicloId, (fin - ini) / 1000 as segundos, eventos\n| sort segundos desc',
              [LG["ms-orchestrator-billing"], LG["ms-facturacion"]])], w=12, h=8,
        desc="Compara 'segundos' con el SLA (variable slaSeg = 120). Las filas incluyen rechazos de negocio con la linea 'factura procesada'.")
b.stat("Duracion del ultimo lote (s)", [logs("A", 'fields toMillis(@timestamp) as t\n| filter cicloId like /$cicloId/ and (message = "ciclo iniciado" or message = "factura procesada")\n'
                                                  '| stats (max(t) - min(t)) / 1000 as segundos',
                                                  [LG["ms-orchestrator-billing"], LG["ms-facturacion"]])],
       calc="lastNotNull", unit="suffix: s", w=4, h=8, steps=[{"color": "green", "value": None}, {"color": "red", "value": 120}],
       desc="Rojo si supera el SLA de 120 s (umbral fijo; coincide con batch_sla_seconds del plan).")
b.ts("Tiempo por mensaje (s): total y sobrecosto",
     [m("A", NS, "MensajeTotalMs", svc("ms-process-billing"), "Average", 60, "tot_avg", "ta", True),
      m("B", NS, "MensajeTotalMs", svc("ms-process-billing"), "Maximum", 60, "tot_max", "tm", True),
      m("C", NS, "MensajeSobrecostoMs", svc("ms-process-billing"), "Average", 60, "sob_avg", "sa", True),
      m("D", NS, "MensajeSobrecostoMs", svc("ms-process-billing"), "Maximum", 60, "sob_max", "sm", True),
      expr("E", "ta/1000", "total promedio"), expr("F", "tm/1000", "total maximo"),
      expr("G", "sa/1000", "sobrecosto promedio"), expr("H", "sm/1000", "sobrecosto maximo")],
     unit="s", w=8, h=8, desc="MensajeTotalMs / MensajeSobrecostoMs (ms en origen, convertidos a segundos).")
b.stat("Duracion del ciclo (metrica CicloDuracionSegundos)", [m("A", NS, "CicloDuracionSegundos", svc("ms-process-billing"), "Maximum", 60, "duracion")],
       calc="lastNotNull", unit="suffix: s", w=4, h=8, steps=[{"color": "green", "value": None}, {"color": "red", "value": 120}],
       desc="Emitida por CycleState al completar el ciclo. Rojo si supera el SLA (120 s).")
b.ts("Throughput: facturas emitidas por minuto", [m("A", NS, "FacturasEmitidas", svc("ms-facturacion"), "Sum", 60, "emitidas/min")], w=8, h=8)
b.save("exp1-absorcion-pico.json")

# =========================================================== exp2
b = Board("voltera-exp2-aislamiento", "Exp2 - Caida de un dependiente (aislamiento)", "Async messaging + Bulkhead + DLQ + Retry: fallos aislados, backlog y reproceso.", ["exp2"])
b.text("Hipotesis", "Si se degrada `ms-tarifas` (caso a) o `ms-comprobante-factura` (caso b), las transacciones afectadas se reintentan (Step Functions: 3 intentos, backoff x2; SQS maxReceiveCount 3) "
       "y caen a la DLQ; el resto del flujo sigue y Kafka/`process-billing` siguen encolando. Al recuperarse, la DLQ se reprocesa (redrive).", h=3)
b.row("DLQ y backlog")
b.stat("DLQ transacciones", [m("A", "AWS/SQS", "ApproximateNumberOfMessagesVisible", {"QueueName": Q_TX_DLQ}, "Maximum", 60)], w=4, h=5,
       steps=[{"color": "green", "value": None}, {"color": "red", "value": 1}])
b.stat("DLQ comprobantes", [m("A", "AWS/SQS", "ApproximateNumberOfMessagesVisible", {"QueueName": Q_CO_DLQ}, "Maximum", 60)], w=4, h=5,
       steps=[{"color": "green", "value": None}, {"color": "red", "value": 1}])
b.ts("Mensajes en DLQ", [m("A", "AWS/SQS", "ApproximateNumberOfMessagesVisible", {"QueueName": Q_TX_DLQ}, "Maximum", 60, "DLQ transacciones"),
                         m("B", "AWS/SQS", "ApproximateNumberOfMessagesVisible", {"QueueName": Q_CO_DLQ}, "Maximum", 60, "DLQ comprobantes")], w=16, h=5, min_=0)
b.ts("Backlog de la cola de transacciones (sigue acumulando)", [m("A", "AWS/SQS", "ApproximateNumberOfMessagesVisible", {"QueueName": Q_TX}, "Maximum", 60, "visibles"),
                                                              m("B", "AWS/SQS", "ApproximateNumberOfMessagesNotVisible", {"QueueName": Q_TX}, "Maximum", 60, "en vuelo"),
                                                              m("C", "AWS/SQS", "NumberOfMessagesSent", {"QueueName": Q_TX}, "Sum", 60, "enviados (ingreso)")])
b.ts("Backlog de la cola de comprobantes (bulkhead)", [m("A", "AWS/SQS", "ApproximateNumberOfMessagesVisible", {"QueueName": Q_CO}, "Maximum", 60, "visibles"),
                                                     m("B", "AWS/SQS", "ApproximateNumberOfMessagesNotVisible", {"QueueName": Q_CO}, "Maximum", 60, "en vuelo"),
                                                     m("C", "AWS/SQS", "ApproximateAgeOfOldestMessage", {"QueueName": Q_CO}, "Maximum", 60, "edad mas antiguo (s)")])
b.row("Reintentos y fallos (Step Functions)")
b.ts("Ejecuciones Step Functions", [m("A", "AWS/States", "ExecutionsStarted", {"StateMachineArn": "$sfn"}, "Sum", 60, "iniciadas"),
                                    m("B", "AWS/States", "ExecutionsSucceeded", {"StateMachineArn": "$sfn"}, "Sum", 60, "exitosas"),
                                    m("C", "AWS/States", "ExecutionsFailed", {"StateMachineArn": "$sfn"}, "Sum", 60, "fallidas"),
                                    m("D", "AWS/States", "ExecutionsTimedOut", {"StateMachineArn": "$sfn"}, "Sum", 60, "timeout"),
                                    m("E", "AWS/States", "ExecutionThrottled", {"StateMachineArn": "$sfn"}, "Sum", 60, "throttled")],
     desc="El Catch de cada tarea envia a la DLQ y termina la ejecucion con exito: fallos agotados NO aparecen como ExecutionsFailed sino en la DLQ.")
b.table("Reintentos por tipo de evento de Step Functions (Logs Insights)",
        [logs("A", 'fields type\n| filter type in ["TaskStateEntered","TaskScheduled","TaskFailed","TaskTimedOut","TaskSucceeded","ExecutionFailed","ExecutionSucceeded"]\n'
                   '| stats count(*) as n by type\n| sort n desc', [LG_SFN])],
        desc="Reintentos = TaskScheduled - TaskStateEntered de las tareas Lambda. (Tipos de evento sin verificar contra AWS: ver README.)")
b.row("Lambdas")
lambdas_health(b, with_duration=True)
b.ts("Fallos de notificacion (ms-comprobante-factura)", [m("A", NS, "NotificacionesFallidas", svc("ms-comprobante-factura"), "Sum", 60, "fallidas"),
                                                         m("B", NS, "FacturasNotificadas", svc("ms-comprobante-factura"), "Sum", 60, "notificadas")])
b.row("Reproceso de la DLQ (SQS redrive)")
b.ts("DLQ: visibles vs. consumidos por redrive", [m("A", "AWS/SQS", "ApproximateNumberOfMessagesVisible", {"QueueName": Q_TX_DLQ}, "Maximum", 60, "visibles"),
                                                  m("B", "AWS/SQS", "NumberOfMessagesDeleted", {"QueueName": Q_TX_DLQ}, "Sum", 60, "borrados/redrive"),
                                                  m("C", "AWS/SQS", "NumberOfMessagesReceived", {"QueueName": Q_TX_DLQ}, "Sum", 60, "recibidos")],
     desc="Tras el StartMessageMoveTask la serie 'visibles' cae a 0 y 'borrados' sube.")
b.ts("Tras el redrive: facturas emitidas / notificadas", [m("A", NS, "FacturasEmitidas", svc("ms-facturacion"), "Sum", 60, "emitidas"),
                                                         m("B", NS, "FacturasNotificadas", svc("ms-comprobante-factura"), "Sum", 60, "notificadas")])
b.row("Servicios en linea (referencia)")
b.ts("Replicas ms-process-billing (sigue encolando)", [m("A", CI, "service_number_of_running_pods", {"ClusterName": CL, "Namespace": KNS, "Service": "ms-process-billing"}, "Maximum", 60, "replicas"),
                                                       m("B", CI, "pod_number_of_container_restarts", {"ClusterName": CL, "Namespace": KNS, "PodName": "ms-process-billing"}, "Maximum", 60, "reinicios")],
     w=12, min_=0, desc="Proxy de 'servicios en linea' mientras no exista endpoint de salud dummy con metrica.")
b.ts("HealthCheckOk por pod (servicio en linea)", [expr("A", "SEARCH('{Voltera/Exp2,pod,service} MetricName=\"HealthCheckOk\" service=\"ms-process-billing\"', 'Minimum', 60)", "${PROP('Dim.pod')}")],
     w=12, min_=0, desc="1 = /healthz responde OK en cada volcado (10 s); 0 = hilo caido. Referencia de 'servicios en linea' durante la falla inyectada.")
b.save("exp2-caida-dependiente.json")

# =========================================================== exp3
b = Board("voltera-exp3-cero-perdida", "Exp3 - Cero perdida de solicitudes", "Durable messaging + at-least-once + idempotencia + outbox: inyectadas = emitidas + DLQ.", ["exp3"])
b.text("Hipotesis y ecuacion", "**Conservacion:** `inyectadas = facturas emitidas + rechazos de negocio + mensajes en DLQ`. Un consumidor que muere a mitad de proceso no pierde mensajes (se reentregan) "
       "y la idempotencia (process-billing, ms-facturacion, ms-comprobante-factura) evita facturas duplicadas. Las metricas no llevan cicloId: ajusta el rango a la corrida.", h=3)
b.row("Ecuacion de conservacion")
b.stat("Inyectadas", [m("A", NS, "UnidadesEnOutbox", svc("ms-orchestrator-billing"), "Sum", 60)], calc="sum", w=4, h=5)
b.stat("Facturas emitidas", [m("A", NS, "FacturasEmitidas", svc("ms-facturacion"), "Sum", 60)], calc="sum", w=4, h=5)
b.stat("Rechazos de negocio", [m("A", NS, "TarifasRechazadas", svc("ms-tarifas"), "Sum", 60, "t", "rt", True),
                               m("B", NS, "CalculosRechazados", svc("ms-calculo-consumo-neto"), "Sum", 60, "c", "rc", True),
                               m("C", NS, "EmisionesRechazadas", svc("ms-facturacion"), "Sum", 60, "e", "re", True),
                               expr("D", "FILL(rt,0)+FILL(rc,0)+FILL(re,0)", "rechazos")], calc="sum", w=4, h=5)
b.stat("En DLQ (transacciones)", [m("A", "AWS/SQS", "ApproximateNumberOfMessagesVisible", {"QueueName": Q_TX_DLQ}, "Maximum", 60)], w=4, h=5,
       steps=[{"color": "green", "value": None}, {"color": "orange", "value": 1}])
b.stat("Saldo (debe ser 0 al terminar)", q_loss_balance(), w=8, h=5, steps=[{"color": "green", "value": None}, {"color": "red", "value": 1}],
       desc="inyectadas - (emitidas + rechazos + DLQ). Positivo = en vuelo o perdidas.")
b.ts("Saldo acumulado en el tiempo", q_loss_balance(), min_=0, w=12, desc="Debe subir al inyectar y converger a 0.")
b.table("Tabla de conservacion (totales del rango)",
        [m("A", NS, "UnidadesEnOutbox", svc("ms-orchestrator-billing"), "Sum", 60, "1 inyectadas"),
         m("B", NS, "FacturasEmitidas", svc("ms-facturacion"), "Sum", 60, "2 emitidas"),
         m("C", NS, "FacturasNotificadas", svc("ms-comprobante-factura"), "Sum", 60, "3 notificadas"),
         m("D", NS, "NotificacionesFallidas", svc("ms-comprobante-factura"), "Sum", 60, "4 notificaciones fallidas (intentos)"),
         m("E", "AWS/SQS", "ApproximateNumberOfMessagesVisible", {"QueueName": Q_TX_DLQ}, "Maximum", 60, "5 DLQ transacciones"),
         m("F", "AWS/SQS", "ApproximateNumberOfMessagesVisible", {"QueueName": Q_CO_DLQ}, "Maximum", 60, "6 DLQ comprobantes")], w=12,
        transformations=[{"id": "reduce", "options": {"reducers": ["sum", "max", "lastNotNull"], "mode": "seriesToRows"}}])
b.row("Reentregas (at-least-once)")
b.ts("Reentregas SQS transacciones (recibidos - enviados, acumulado)",
     [m("A", "AWS/SQS", "NumberOfMessagesReceived", {"QueueName": Q_TX}, "Sum", 60, "rcv", "rcv", True),
      m("B", "AWS/SQS", "NumberOfMessagesSent", {"QueueName": Q_TX}, "Sum", 60, "snt", "snt", True),
      expr("C", "RUNNING_SUM(FILL(rcv,0)) - RUNNING_SUM(FILL(snt,0))", "reentregas aprox.")],
     desc="Aproximacion: cada recepcion adicional a un envio es una reentrega (visibility timeout vencido / consumidor muerto).")
b.ts("Mensajes en vuelo y reentregas de comprobantes",
     [m("A", "AWS/SQS", "ApproximateNumberOfMessagesNotVisible", {"QueueName": Q_CO}, "Maximum", 60, "en vuelo"),
      m("B", "AWS/SQS", "NumberOfMessagesReceived", {"QueueName": Q_CO}, "Sum", 60, "recibidos", "rcv", True),
      m("C", "AWS/SQS", "NumberOfMessagesSent", {"QueueName": Q_CO}, "Sum", 60, "enviados", "snt", True),
      expr("D", "RUNNING_SUM(FILL(rcv,0)) - RUNNING_SUM(FILL(snt,0))", "reentregas aprox.")])
b.ts("Reentregas Kafka tras muerte del pod (MensajesReenviados)", [m("A", NS, "MensajesReenviados", svc("ms-process-billing"), "Sum", 60, "reenviados")], w=12, h=8,
     desc="Mensajes que el pod nuevo encontro en PROCESANDO y volvio a publicar en SQS tras la muerte del anterior.")
b.ts("Duplicados descartados en el ingreso (dedup de process-billing)", [m("A", NS, "MensajesDuplicados", svc("ms-process-billing"), "Sum", 60, "duplicados"),
                                                                           m("B", NS, "TransaccionesEnviadasASqs", svc("ms-process-billing"), "Sum", 60, "enviadas a SQS")], w=12,
     desc="EMF de process-billing: volcado cada 10 s por EmfAggregator.")
b.row("Idempotencia y facturas")
b.table("Facturas con mas de una ejecucion (idempotencia: reintento absorbido)",
        [logs("A", 'filter message = "factura procesada" and cicloId like /$cicloId/\n| stats count(*) as ejecuciones, count_distinct(numero) as numeros_distintos by facturaId\n'
                   '| filter ejecuciones > 1\n| sort ejecuciones desc', [LG["ms-facturacion"]])], w=12,
        desc="'ejecuciones - 1' = duplicados evitados por idempotencia. numeros_distintos debe ser 1 (misma factura, mismo consecutivo).")
b.stat("Facturas con numero duplicado (debe ser 0)",
       [logs("A", 'filter message = "factura procesada" and cicloId like /$cicloId/ and ispresent(numero)\n| stats count_distinct(numero) as numeros, count_distinct(facturaId) as facturas\n'
                  '| display (numeros - facturas) as duplicadas', [LG["ms-facturacion"]])], w=6, h=8,
       steps=[{"color": "green", "value": None}, {"color": "red", "value": 1}],
       desc="numeros distintos - facturas distintas. >0 = una factura recibio mas de un consecutivo.")
b.stat("Facturas emitidas (metrica)", [m("A", NS, "FacturasEmitidas", svc("ms-facturacion"), "Sum", 60)], calc="sum", w=6, h=8)
b.ts("Facturas emitidas vs notificadas", cumulative("A", NS, "FacturasEmitidas", svc("ms-facturacion"), "emitidas", "e") +
     cumulative("B", NS, "FacturasNotificadas", svc("ms-comprobante-factura"), "notificadas", "n"), w=12)
b.ts("Replays de idempotencia (duplicados evitados)", [m("A", NS, "IdempotenciaReplays", svc("ms-facturacion"), "Sum", 60, "ms-facturacion"),
                                                       m("B", NS, "IdempotenciaReplays", svc("ms-comprobante-factura"), "Sum", 60, "ms-comprobante-factura"),
                                                       m("C", NS, "MensajesDuplicados", svc("ms-process-billing"), "Sum", 60, "ingreso (dedup process-billing)")], w=12,
     desc="Cada replay = un reintento/entrega repetida absorbida sin re-emitir.")
b.row("Outbox")
b.ts("Outbox: eventos publicados por el relay", [m("A", NS, "EventosPublicadosOutbox", svc("outbox-relay"), "Sum", 60, "publicados"),
                                                 m("B", NS, "UnidadesEnOutbox", svc("ms-orchestrator-billing"), "Sum", 60, "escritos en outbox")],
     desc="Si publicados < escritos hay eventos pendientes de relay (la fila sigue en la tabla outbox).")
b.ts("Errores del relay", [m("A", "AWS/Lambda", "Errors", {"FunctionName": f"{P}-outbox-relay"}, "Sum", 60, "errores relay"),
                           m("B", "AWS/Lambda", "IteratorAge", {"FunctionName": f"{P}-outbox-relay"}, "Maximum", 60, "IteratorAge (ms)")])
b.save("exp3-cero-perdida.json")

# =========================================================== exp4
b = Board("voltera-exp4-event-mesh", "Exp4 - Event Mesh (observabilidad y contexto)", "Completitud de eventos, fallos de publicacion, linea de tiempo por factura, estado del ciclo y trazas.", ["exp4"],
          extra_vars=[])
b.extra_vars.append(b.var_text("facturaId", "facturaId", ".", "Regex sobre facturaId; '.' = todas."))
b.text("Hipotesis", "El mesh registra cada evento con `cicloId` + `facturaId`, permite reconstruir el recorrido de cada factura y mostrar el estado del ciclo. Los eventos viven en Kafka (`voltera.eventos`); "
       "aqui se observan a traves de las metricas EMF y de los logs estructurados de cada paso. Replay por offset, MirrorMaker2 y Apicurio se verifican con los scripts del cluster, no por CloudWatch.", h=3)
b.row("Completitud de eventos")
b.ts("Eventos esperados vs. registrados por etapa (acumulado)",
     cumulative("A", NS, "UnidadesEnOutbox", svc("ms-orchestrator-billing"), "esperadas (inyectadas)", "i") +
     [m("Bm", NS, "TarifasValidadas", svc("ms-tarifas"), "Sum", 60, "t1", "t1", True), m("Cm", NS, "TarifasRechazadas", svc("ms-tarifas"), "Sum", 60, "t2", "t2", True),
      expr("B", "RUNNING_SUM(FILL(t1,0)) + RUNNING_SUM(FILL(t2,0))", "tarifa (validada+rechazada)")] +
     [m("Dm", NS, "CargosCalculados", svc("ms-calculo-consumo-neto"), "Sum", 60, "c1", "c1", True), m("Em", NS, "CalculosRechazados", svc("ms-calculo-consumo-neto"), "Sum", 60, "c2", "c2", True),
      expr("D", "RUNNING_SUM(FILL(c1,0)) + RUNNING_SUM(FILL(c2,0))", "calculo (calculado+rechazado)")] +
     cumulative("F", NS, "FacturasEmitidas", svc("ms-facturacion"), "FacturaEmitida", "f") +
     cumulative("G", NS, "FacturasNotificadas", svc("ms-comprobante-factura"), "FacturaNotificada", "g"),
     w=12, desc="Cada factura aprobada debe producir TarifaValidada, CargoEnergeticoCalculado, FacturaEmitida y FacturaNotificada. Serie 'esperadas' = techo.")
b.table("Eventos publicados al mesh por factura (completitud)",
        [logs("A", 'filter message = "evento publicado" and cicloId like /$cicloId/ and facturaId like /$facturaId/\n'
                   '| stats count_distinct(tipo) as tipos_distintos, count(*) as publicaciones, min(@timestamp) as primera, max(@timestamp) as ultima by cicloId, facturaId\n| sort tipos_distintos asc, ultima desc\n| limit 200',
              LG_STEPS + [LG["ms-orchestrator-billing"]])], w=12,
        desc="Log 'evento publicado' (tipo, cicloId, facturaId, eventId) del publisher. Una factura completa aprobada publica TarifaValidada, CargoEnergeticoCalculado, FacturaEmitida, NotificacionRegistrada y FacturaNotificada. Filas con pocos tipos = eventos faltantes o rechazo de negocio.")
b.row("Fallos de publicacion al mesh")
b.ts("MeshPublishFailures por servicio", [expr("A", "SEARCH('{Voltera/Exp2,service} MetricName=\"MeshPublishFailures\"', 'Sum', 60)", "${PROP('Dim.service')}")], w=8, h=8, min_=0,
     desc="Metrica EMF emitida por el publisher cuando falla publish_event (best-effort: el paso de negocio continua).")
b.table("Fallos de publicacion detectados por log ('fallo publicando')",
        [logs("A", 'fields @timestamp, @log, @message\n| filter @message like /fallo publicando evento/\n| sort @timestamp desc\n| limit 100', LG_STEPS + [LG["outbox-relay"]])], w=16, h=8,
        desc="Detalle: el publisher registra el error en un log JSON ('fallo publicando evento al mesh').")
b.row("Linea de tiempo por factura / ciclo")
b.logs("Linea de tiempo (filtra por cicloId y facturaId arriba)",
       [logs("A", 'fields @timestamp, service, message, tipo, cicloId, facturaId, aprobado, numero, level\n| filter cicloId like /$cicloId/ and facturaId like /$facturaId/\n| sort @timestamp asc\n| limit 500', LG_ALL_LAMBDA + [LG_PB])],
       h=11, desc="Union de los logs JSON de los 6 Lambdas. Incluye eventos publicados, comprobante recibido/procesado. Los logs de process-billing viven en el log group de Container Insights (application); ver README.")
b.table("Ejecuciones de Step Functions del ciclo (log de la state machine)",
        [logs("A", 'fields @timestamp, type, execution_arn\n| filter type in ["ExecutionStarted","ExecutionSucceeded","ExecutionFailed","ExecutionTimedOut"] and @message like /$cicloId/\n| sort @timestamp desc\n| limit 100', [LG_SFN])],
        w=24, h=7, desc="La entrada de la ejecucion (details.input) contiene cicloId/facturaId; el filtro es por texto del evento.")
b.row("Estado del ciclo")
b.stat("Ciclos completados", [m("A", NS, "CiclosCompletados", svc("ms-process-billing"), "Sum", 60)], calc="sum", w=4, h=8)
b.stat("Ciclos fallidos", [m("A", NS, "CiclosFallidos", svc("ms-process-billing"), "Sum", 60)], calc="sum", w=4, h=8, steps=[{"color": "green", "value": None}, {"color": "red", "value": 1}])
b.stat("Duracion del ciclo (s)", [m("A", NS, "CicloDuracionSegundos", svc("ms-process-billing"), "Maximum", 60)], calc="lastNotNull", unit="s", w=4, h=8)
b.stat("Ejecuciones exitosas", [m("A", "AWS/States", "ExecutionsSucceeded", {"StateMachineArn": "$sfn"}, "Sum", 60)], calc="sum", w=4, h=8)
b.stat("Ejecuciones fallidas", [m("A", "AWS/States", "ExecutionsFailed", {"StateMachineArn": "$sfn"}, "Sum", 60)], calc="sum", w=4, h=8,
       steps=[{"color": "green", "value": None}, {"color": "red", "value": 1}])
b.stat("DLQ transacciones", [m("A", "AWS/SQS", "ApproximateNumberOfMessagesVisible", {"QueueName": Q_TX_DLQ}, "Maximum", 60)], w=4, h=8,
       steps=[{"color": "green", "value": None}, {"color": "red", "value": 1}])
b.stat("Saldo del ciclo (proxy de estado)", q_loss_balance(), w=4, h=8, steps=[{"color": "green", "value": None}, {"color": "orange", "value": 1}],
       desc="0 = todo inyectado quedo emitido, rechazado o en DLQ (ciclo cerrado).")
b.row("Trazas X-Ray")
b.add("table", "Trazas recientes (resumen)", [xr("A", "getTraceSummaries", query="annotation.cicloId = \"${cicloId}\"", group={"GroupName": "Default"}, columns=["Id", "Method", "ResponseTime", "Duration", "HasError", "HasFault"])],
      w=24, h=8, ds=XR, desc="Trazas de Lambdas (Powertools Tracer) y Step Functions (tracing activo). Anotaciones X-Ray cicloId y facturaId: filtra con  annotation.cicloId = <id>  o  annotation.facturaId = <id>.",
      defaults={}, options={"showHeader": True})
b.add("timeseries", "Estadisticas de servicio (latencia/errores)", [xr("A", "getTimeSeriesServiceStatistics", query="", group={"GroupName": "Default"})], w=12, h=8, ds=XR,
      defaults={"custom": {"drawStyle": "line", "lineWidth": 2, "fillOpacity": 8, "showPoints": "never"}}, options={"legend": {"displayMode": "list", "placement": "bottom"}})
b.add("nodeGraph", "Mapa de servicios", [xr("A", "getServiceMap", query="", group={"GroupName": "Default"})], w=12, h=8, ds=XR, defaults={}, options={})
b.save("exp4-event-mesh.json")
print("dashboards generados en", os.path.abspath(A.out))
