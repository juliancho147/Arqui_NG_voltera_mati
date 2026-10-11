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
ap.add_argument("--legacy", action="store_true", help="ademas genera los antiguos exp2/exp3 separados en dashboards/_legacy/ (Grafana no los carga)")
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
    def __init__(self, uid, title, desc, tags, extra_vars=(), refresh="30s", time_from="now-1h"):
        self.uid, self.title, self.desc, self.tags = uid, title, desc, tags
        self.refresh, self.time_from, self.annos = refresh, time_from, []
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

    def ts(self, title, targets, unit="short", stack=False, w=12, h=8, desc="", min_=None, thresholds=None, ds=CW, ylab=None,
           overrides=None, decimals=None):
        ylab = ylab or y_label(title, unit)
        title = f"{title}  (eje X: hora)"
        desc = (desc + " " if desc else "") + f"Eje Y: {ylab}. Eje X: tiempo (hora local)."
        d = {"unit": unit, "custom": {"axisLabel": ylab, "drawStyle": "line", "lineWidth": 2, "fillOpacity": 15 if stack else 8, "showPoints": "never",
                                       "spanNulls": True, "stacking": {"mode": "normal" if stack else "none", "group": "A"}}}
        if min_ is not None:
            d["min"] = min_
        if decimals is not None:
            d["decimals"] = decimals
        if thresholds:
            d["thresholds"] = {"mode": "absolute", "steps": thresholds}
            d["custom"]["thresholdsStyle"] = {"mode": "line"}
        return self.add("timeseries", title, targets, w, h, desc, ds, d, overrides=overrides,
                        options={"legend": {"displayMode": "table", "placement": "bottom", "calcs": ["lastNotNull", "max"]},
                                 "tooltip": {"mode": "multi", "sort": "desc"}})

    def stat(self, title, targets, calc="lastNotNull", unit="short", w=4, h=4, desc="", steps=None, color_mode="background", decimals=0, value_size=None, mappings=None):
        steps = steps or [{"color": "green", "value": None}]
        d = {"unit": unit, "decimals": decimals, "thresholds": {"mode": "absolute", "steps": steps}, "color": {"mode": "thresholds"},
             "noValue": "0"}
        if mappings:
            d["mappings"] = mappings
        opts = {"reduceOptions": {"calcs": [calc], "fields": "", "values": False}, "colorMode": color_mode,
                "graphMode": "none", "textMode": "value_and_name", "justifyMode": "center"}
        if value_size:  # tipografia grande para video
            opts["text"] = {"valueSize": value_size, "titleSize": 20}
        return self.add("stat", title, targets, w, h, desc, CW, d, options=opts)

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
            "schemaVersion": 39, "version": 1, "editable": True, "graphTooltip": 1, "refresh": self.refresh,
            "time": {"from": self.time_from, "to": "now"}, "timepicker": {"refresh_intervals": ["5s", "10s", "30s", "1m", "5m"]},
            "timezone": "browser", "fiscalYearStartMonth": 0, "liveNow": False,
            "templating": {"list": [cyc, sfn] + self.extra_vars},
            "annotations": {"list": [{"builtIn": 1, "datasource": {"type": "grafana", "uid": "-- Grafana --"}, "enable": True,
                                      "hide": True, "iconColor": "rgba(0, 211, 255, 1)", "name": "Annotations & Alerts", "type": "dashboard"}] + self.annos},
            "links": [{"type": "dashboards", "tags": ["voltera"], "asDropdown": True, "title": "Dashboards Voltera", "includeVars": False,
                       "keepTime": True}],
            "panels": self.panels,
        }

    def save(self, fname, sub=""):
        os.makedirs(os.path.join(A.out, sub), exist_ok=True)
        path = os.path.join(A.out, sub, fname)
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
b.stat("Ciclos reconciliados", [m("A", NS, "CiclosReconciliados", svc("ms-process-billing"), "Sum", 60)], calc="sum", w=4,
       desc="Ciclos cerrados por reconciliacion contra DynamoDB (evento de estado perdido).")
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

# =========================================================== dashboards para GRABAR (exp1, exp2, exp3)
# Contrato con el runner: metrica CloudWatch FaseExperimento (namespace Voltera/Exp2), dimensiones experimento y fase, valor 1 en el
# instante del evento. Las anotaciones de Grafana se alimentan de ella (ver anno()).
FASES = {  # experimento -> [(fase, nombre de la anotacion, color)]
    "exp1": [("disparo", "Pico inyectado", "orange")],
    "exp2": [("estado_inicial", "Estado inicial", "gray"), ("disparo", "Disparo", "orange"), ("fallo_dependiente", "Fallo del dependiente", "red"),
             ("fallo_pod", "Pods muertos", "purple"), ("fallo_lambda", "Fallo en Lambda", "yellow"), ("duplicados", "Duplicados reenviados", "blue"),
             ("recuperacion", "Recuperacion", "green")],
}
FASES_LEGACY = {  # solo --legacy
    "exp2": [("fallo_inyectado", "Fallo inyectado", "red"), ("recuperacion", "Recuperacion", "green")],
    "exp3": [("fallo_pod", "Pods muertos", "red"), ("fallo_lambda", "Fallo en Lambdas", "purple"), ("recuperacion", "Recuperacion", "green")],
}
BIG = 72  # tamano de fuente de los stats (video)


def anno(b, exp, fases=None):
    """Fila final con un panel por fase (consulta FaseExperimento) y anotaciones que leen el resultado de esos paneles
    (datasource '-- Dashboard --'). Los paneles son solo la fuente de datos; no se explican en la grabacion."""
    b.row("Fuente de anotaciones (FaseExperimento; no se explica)")
    for fase, nombre, color in (fases or FASES[exp]):
        p = b.table(f"Marca: {nombre}", [m("A", NS, "FaseExperimento", {"experimento": exp, "fase": fase}, "Sum", 60, fase)], w=8, h=3,
                    desc=f"CloudWatch {NS}/FaseExperimento experimento={exp} fase={fase}. Cada punto dibuja la anotacion '{nombre}'.")
        b.annos.append({"datasource": {"type": "datasource", "uid": "-- Dashboard --"}, "enable": True, "iconColor": color, "name": nombre,
                        "filter": {"exclude": False, "ids": [p["id"]]},
                        "target": {"limit": 100, "matchAny": False, "tags": [], "type": "dashboard"},
                        "mappings": {"title": {"source": "text", "value": nombre}}})


def que(mirar, patron):
    return f"Qué mirar: {mirar} Patrón de arquitectura: {patron}"


def all_rechazos():
    return [m("Rt", NS, "TarifasRechazadas", svc("ms-tarifas"), "Sum", 60, "rt", "rt", True),
            m("Rc", NS, "CalculosRechazados", svc("ms-calculo-consumo-neto"), "Sum", 60, "rc", "rc", True),
            m("Re", NS, "EmisionesRechazadas", svc("ms-facturacion"), "Sum", 60, "re", "re", True)]


RED_AT = lambda v: [{"color": "green", "value": None}, {"color": "red", "value": v}]

# =========================================================== exp1
b = Board("voltera-exp1-absorcion", "Exp1 - Absorcion del pico (autoescalado)",
          "Queue-Based Load Leveling + KEDA: backlog, replicas y tiempo del lote vs SLA. Pensado para grabar.", ["exp1", "video"],
          refresh="5s", time_from="now-15m")
b.stat("Tiempo del lote en segundos (SLA: 120 s)", [m("A", NS, "CicloDuracionSegundos", svc("ms-process-billing"), "Maximum", 60, "tiempo del lote")],
       calc="lastNotNull", unit="suffix: s", w=8, h=6, steps=RED_AT(120), value_size=BIG, decimals=1,
       desc=que("verde = el lote termino dentro del SLA de 120 s; rojo = lo supero. Aparece 1-2 min despues de cerrar el ultimo lote (latencia de CloudWatch).",
                "SLA de cierre de ciclo; criterio de aceptacion del ASR de absorcion de picos."))
b.stat("Pods de ms-process-billing en el pico (escala KEDA)", [m("A", CI, "service_number_of_running_pods", {"ClusterName": CL, "Namespace": KNS, "Service": "ms-process-billing"}, "Maximum", 60, "replicas")],
       calc="max", w=8, h=6, steps=[{"color": "blue", "value": None}], value_size=BIG,
       desc=que("de 1 pod en reposo a 5 al llegar el pico (tope de KEDA).", "Autoescalado por evento (KEDA) sobre el lag del consumidor."))
b.stat("Mensajes pendientes al llegar el pico (maximo)",
       [m("Am", "Voltera/Exp2", "KafkaConsumerLag", {"service": "ms-process-billing", "topic": "voltera.consumo-facturable-preparado"}, "Sum", 60, "muestras", "lag", True),
        expr("A", "lag / 6", "mensajes pendientes")],
       calc="max", w=8, h=6, steps=[{"color": "orange", "value": None}], value_size=BIG,
       desc=que("tamano del pico que hubo que absorber; luego el grafico de abajo debe llevarlo a 0.", "Queue-Based Load Leveling: la cola (Kafka) absorbe lo que el consumo aun no procesa."))
b.ts("ms-process-billing: mensajes pendientes en Kafka y pods que escalan",
     [m("Am", "Voltera/Exp2", "KafkaConsumerLag", {"service": "ms-process-billing", "topic": "voltera.consumo-facturable-preparado"}, "Sum", 60, "muestras sumadas", "lag", True),
      expr("A", "lag / 6", "Kafka: mensajes pendientes por procesar (lag)", 60),
      m("B", CI, "service_number_of_running_pods", {"ClusterName": CL, "Namespace": KNS, "Service": "ms-process-billing"}, "Maximum", 60, "ms-process-billing: pods (replicas)")],
     w=24, h=10, min_=0, ylab="Mensajes pendientes (lag)",
     overrides=[{"matcher": {"id": "byName", "options": "ms-process-billing: pods (replicas)"}, "properties": [
         {"id": "custom.axisPlacement", "value": "right"}, {"id": "custom.axisLabel", "value": "Pods de ms-process-billing"},
         {"id": "custom.fillOpacity", "value": 0}, {"id": "custom.lineWidth", "value": 3}, {"id": "color", "value": {"mode": "fixed", "fixedColor": "orange"}}]}],
     desc=que("el lag sube de golpe al inyectar el lote y las replicas suben 1 -> 4 -> 5 unos 35 s despues; el lag cae a 0 y las replicas vuelven a 1. "
              "Lag = KafkaConsumerLag Sum/6 (6 muestras por minuto por pod; asume METRICS_FLUSH_SECONDS=10).",
              "Queue-Based Load Leveling + autoescalado por evento (KEDA, lagThreshold 2). Eje izq: mensajes; eje der: pods."))
b.ts("Facturas emitidas acumuladas (el lote avanza)",
     cumulative("A", NS, "FacturasEmitidas", svc("ms-facturacion"), "facturas emitidas", "e") +
     cumulative("B", NS, "UnidadesEnOutbox", svc("ms-orchestrator-billing"), "inyectadas (meta)", "i"),
     w=12, h=9, min_=0, ylab="Facturas acumuladas",
     desc=que("la curva de emitidas sube hasta alcanzar la meta (inyectadas); el instante en que la alcanza es el tiempo del lote.",
              "Cero perdida por saturacion: todo lo inyectado termina emitido aunque llegue en rafaga."))
b.ts("Cuanto tarda ms-process-billing en procesar UNA factura (segundos)",
     [m("A", NS, "MensajeTotalMs", svc("ms-process-billing"), "Average", 60, "tot_avg", "ta", True),
      m("B", NS, "MensajeTotalMs", svc("ms-process-billing"), "Maximum", 60, "tot_max", "tm", True),
      m("C", NS, "MensajeSobrecostoMs", svc("ms-process-billing"), "Average", 60, "sob_avg", "sa", True),
      expr("E", "ta/1000", "Tiempo total por factura (promedio)"), expr("F", "tm/1000", "Tiempo total de la factura mas lenta"),
      expr("G", "sa/1000", "Solo el trabajo de mensajeria (sin la espera simulada)")],
     unit="s", w=12, h=9, ylab="Segundos por factura", decimals=2,
     desc=que("mide UNA factura dentro de un pod de ms-process-billing, desde que la lee de Kafka hasta que la confirma. La linea de arriba (~2 s) es casi toda la espera simulada que fija el experimento (--delay); "
              "la linea de abajo es lo que cuesta la mensajeria real (DynamoDB, SQS, commit) y debe ser menor a 0,2 s. Si la de abajo es chica, el servicio no es el cuello: la demora esta en el escalado o el reparto de particiones.",
              "Medicion del costo de la mensajeria durable (claim, SQS, commit) frente al trabajo util."))
b.ts("Lambdas que escalan: ejecuciones simultaneas por servicio",
     [search("A", "AWS/Lambda", "FunctionName", "ConcurrentExecutions", "Maximum")],
     w=12, h=9, min_=0, ylab="Ejecuciones simultaneas de la Lambda",
     desc=que("cada linea es una Lambda del flujo (ms-tarifas, ms-calculo-consumo-neto, ms-facturacion, ms-comprobante-factura): sube cuando llegan facturas y baja a 0 al terminar. Lambda escala sola, sin KEDA.",
              "Computo serverless por evento: escala por concurrencia, a diferencia de ms-process-billing que escala por lag con KEDA."))
anno(b, "exp1")
b.save("exp1-absorcion-pico.json")

# =========================================================== LEGACY (solo con --legacy): antiguos Exp2 y Exp3 separados
if A.legacy:
    # =========================================================== exp2
    b = Board("voltera-exp2-aislamiento", "Exp2 - Caida de un dependiente (aislamiento)",
              "Async messaging + Bulkhead + DLQ + Retry: un dependiente caido no tumba el resto. Pensado para grabar.", ["exp2", "video"],
              refresh="5s", time_from="now-15m")
    b.stat("Mensajes atascados en DLQ (lo que fallo de verdad)",
           [m("A", "AWS/SQS", "ApproximateNumberOfMessagesVisible", {"QueueName": Q_TX_DLQ}, "Maximum", 60, "tx", "d1", True),
            m("B", "AWS/SQS", "ApproximateNumberOfMessagesVisible", {"QueueName": Q_CO_DLQ}, "Maximum", 60, "co", "d2", True),
            expr("C", "FILL(d1,0)+FILL(d2,0)", "en DLQ")],
           calc="lastNotNull", w=6, h=6, steps=[{"color": "green", "value": None}, {"color": "red", "value": 1}], value_size=BIG,
           desc=que("sube de 0 cuando el dependiente caido agota sus reintentos y baja a 0 tras el redrive (recuperacion).",
                    "Dead Letter Queue: lo que no se pudo procesar se aparta sin perderse y sin frenar al resto."))
    b.stat("Facturas emitidas (siguen subiendo)", [m("A", NS, "FacturasEmitidas", svc("ms-facturacion"), "Sum", 60, "emitidas")],
           calc="sum", w=6, h=6, steps=[{"color": "blue", "value": None}], value_size=BIG,
           desc=que("el contador no se congela durante el fallo: el resto del flujo sigue facturando.", "Bulkhead: el fallo queda contenido en un solo dependiente."))
    b.stat("ms-process-billing (el ingreso, NO se cae): estado",
           [expr("A", "MIN(SEARCH('{Voltera/Exp2,pod,service} MetricName=\"HealthCheckOk\" service=\"ms-process-billing\"', 'Minimum', 60))", "disponibilidad")],
           calc="lastNotNull", w=6, h=6, value_size=BIG,
           steps=[{"color": "red", "value": None}, {"color": "green", "value": 1}],
           mappings=[{"type": "value", "options": {"1": {"text": "EN LINEA", "color": "green"}, "0": {"text": "CAIDO", "color": "red"}}}],
           desc=que("este es el servicio que recibe las facturas y NO se cae en este experimento: debe seguir EN LINEA todo el fallo. El que se cae es el dependiente (ver el indicador de la derecha).", "Aislamiento por mensajeria asincrona: productor y consumidor desacoplados."))
    b.stat("Servicio que se cae: errores por minuto de su Lambda",
           [m("A", "AWS/Lambda", "Errors", {"FunctionName": "voltera-exp2-ms-comprobante-factura"}, "Sum", 60, "ms-comprobante-factura (caso B)"),
            m("B", "AWS/Lambda", "Errors", {"FunctionName": "voltera-exp2-ms-tarifas"}, "Sum", 60, "ms-tarifas (caso A)")],
           calc="max", w=6, h=6, steps=[{"color": "green", "value": None}, {"color": "red", "value": 1}], value_size=BIG,
           desc=que("sube de 0 en la Lambda que el runner tumba: ms-comprobante-factura en el caso B, ms-tarifas en el caso A. Es el dependiente caido; el resto del flujo sigue.", "Fallo contenido en un solo dependiente (Bulkhead); los errores disparan Retry y luego DLQ."))
    b.ts("Cola y DLQ del dependiente caido",
         [m("A", "AWS/SQS", "ApproximateNumberOfMessagesVisible", {"QueueName": Q_CO}, "Maximum", 60, "comprobantes en cola"),
          m("B", "AWS/SQS", "ApproximateNumberOfMessagesNotVisible", {"QueueName": Q_CO}, "Maximum", 60, "comprobantes en proceso"),
          m("C", "AWS/SQS", "ApproximateNumberOfMessagesVisible", {"QueueName": Q_CO_DLQ}, "Maximum", 60, "DLQ comprobantes"),
          m("D", "AWS/SQS", "ApproximateNumberOfMessagesVisible", {"QueueName": Q_TX_DLQ}, "Maximum", 60, "DLQ transacciones"),
          m("E", "AWS/SQS", "ApproximateNumberOfMessagesVisible", {"QueueName": Q_TX}, "Maximum", 60, "transacciones en cola")],
         w=12, h=9, min_=0, ylab="Mensajes en cola",
         desc=que("tras 'Fallo inyectado' la cola del dependiente (ms-comprobante-factura caso b) o la DLQ de transacciones (ms-tarifas caso a) crece; tras 'Recuperacion' vuelve a 0.",
                  "Queue-Based Load Leveling + Retry con backoff + DLQ: el backlog se acumula en la cola, no en quien llama."))
    b.ts("Facturas emitidas y notificadas (acumulado)",
         cumulative("A", NS, "FacturasEmitidas", svc("ms-facturacion"), "emitidas", "e") +
         cumulative("B", NS, "FacturasNotificadas", svc("ms-comprobante-factura"), "notificadas", "n"),
         w=12, h=9, min_=0, ylab="Facturas acumuladas",
         desc=que("'emitidas' sigue subiendo durante el fallo; 'notificadas' se aplana si cae el comprobante y alcanza a emitidas tras la recuperacion.",
                  "Bulkhead + desacople por cola: emitir no espera a notificar."))
    b.ts("Errores de Step Functions y reintentos",
         [m("A", "AWS/States", "ExecutionsStarted", {"StateMachineArn": "$sfn"}, "Sum", 60, "ejecuciones iniciadas"),
          m("B", "AWS/States", "ExecutionsFailed", {"StateMachineArn": "$sfn"}, "Sum", 60, "ejecuciones fallidas"),
          m("C", "AWS/States", "ExecutionsTimedOut", {"StateMachineArn": "$sfn"}, "Sum", 60, "ejecuciones con timeout"),
          expr("D", f"SUM(SEARCH('{{AWS/Lambda,FunctionName}} MetricName=\"Errors\" {P}', 'Sum', 60))", "errores de Lambda (disparan reintentos)")],
         w=24, h=8, min_=0, ylab="Eventos por minuto",
         desc=que("los errores de Lambda suben durante el fallo (son los reintentos); 'fallidas' casi no se mueve porque el Catch manda a la DLQ y la ejecucion termina con exito.",
                  "Retry con backoff exponencial y Catch hacia DLQ en la orquestacion (Saga / Step Functions)."))
    anno(b, "exp2", FASES_LEGACY["exp2"])
    b.save("exp2-caida-dependiente.json", "_legacy")

    # =========================================================== exp3
    b = Board("voltera-exp3-cero-perdida", "Exp3 - Cero perdida de solicitudes",
              "Durable messaging + at-least-once + idempotencia + outbox: inyectadas = emitidas + rechazadas + DLQ. Pensado para grabar.", ["exp3", "video"],
              refresh="5s", time_from="now-15m")
    CONT_Q = ([m("A", NS, "UnidadesEnOutbox", svc("ms-orchestrator-billing"), "Sum", 60, "inyectadas", "inj", True),
               m("B", NS, "FacturasEmitidas", svc("ms-facturacion"), "Sum", 60, "emitidas", "em", True)] + all_rechazos() +
              [m("F", "AWS/SQS", "ApproximateNumberOfMessagesVisible", {"QueueName": Q_TX_DLQ}, "Maximum", 60, "dlq", "dlq", True)])
    CONT_EXPR = "RUNNING_SUM(FILL(em,0)) + RUNNING_SUM(FILL(rt,0)) + RUNNING_SUM(FILL(rc,0)) + RUNNING_SUM(FILL(re,0)) + FILL(dlq,0)"
    b.stat("Solicitudes inyectadas", [m("A", NS, "UnidadesEnOutbox", svc("ms-orchestrator-billing"), "Sum", 60, "inyectadas")],
           calc="sum", w=5, h=7, steps=[{"color": "blue", "value": None}], value_size=BIG,
           desc=que("el total que entro al sistema; es el lado izquierdo de la ecuacion.", "Outbox transaccional: lo inyectado queda registrado antes de publicarse."))
    b.stat("Emitidas + rechazadas + en DLQ", CONT_Q + [expr("G", CONT_EXPR, "contabilizadas")],
           calc="lastNotNull", w=5, h=7, steps=[{"color": "blue", "value": None}], value_size=BIG,
           desc=que("debe igualar a las inyectadas: todo termino emitido, rechazado por negocio o apartado en DLQ.", "Conservacion de mensajes: at-least-once + DLQ, nada desaparece en silencio."))
    b.stat("SALDO (inyectadas - contabilizadas)", q_loss_balance(), calc="lastNotNull", w=6, h=7,
           steps=[{"color": "green", "value": None}, {"color": "orange", "value": 1}], value_size=96,
           desc=que("0 = cero perdida. Naranja mientras hay trabajo en vuelo; al terminar la corrida debe volver a 0 y quedarse verde.", "Verificacion de cero perdida (ASR de confiabilidad)."))
    b.stat("Ciclos y facturas reconciliados",
           [m("A", NS, "CiclosCompletados", svc("ms-process-billing"), "Sum", 60, "ciclos completados"),
            m("B", NS, "CiclosFallidos", svc("ms-process-billing"), "Sum", 60, "ciclos fallidos"),
            m("C", NS, "CiclosReconciliados", svc("ms-process-billing"), "Sum", 60, "ciclos reconciliados"),
            m("D", NS, "FacturasReconciliadas", svc("ms-process-billing"), "Sum", 60, "facturas reconciliadas")],
           calc="sum", w=8, h=7, color_mode="value", steps=[{"color": "blue", "value": None}], value_size=44,
           desc=que("'completados' sube al cerrar el ciclo; 'fallidos' debe ser 0; 'reconciliados' > 0 indica que se perdio un evento de estado y la reconciliacion contra DynamoDB cerro el ciclo (no se perdio la factura).",
                    "Reconciliacion (compensacion periodica) sobre un estado de ciclo basado en eventos best-effort."))
    b.ts("Conservacion en el tiempo: inyectadas vs contabilizadas",
         CONT_Q + [expr("G", CONT_EXPR, "emitidas + rechazadas + DLQ", 60),
                   expr("H", "RUNNING_SUM(FILL(inj,0))", "inyectadas (acumulado)", 60)],
         w=12, h=9, min_=0, ylab="Solicitudes acumuladas",
         desc=que("las dos lineas se separan al inyectar y vuelven a juntarse; juntas = saldo 0. Una separacion que no cierra seria una perdida.",
                  "Durable messaging (Kafka/SQS) + outbox: el trabajo en vuelo es recuperable."))
    b.ts("Reintentos, duplicados descartados y replays",
         [m("A", NS, "MensajesReenviados", svc("ms-process-billing"), "Sum", 60, "reenviados tras muerte del pod"),
          m("B", NS, "MensajesDuplicados", svc("ms-process-billing"), "Sum", 60, "duplicados descartados en ingreso"),
          m("C", NS, "IdempotenciaReplays", svc("ms-facturacion"), "Sum", 60, "replays idempotencia: facturacion"),
          m("D", NS, "IdempotenciaReplays", svc("ms-comprobante-factura"), "Sum", 60, "replays idempotencia: comprobante"),
          m("E", NS, "NotificacionesFallidas", svc("ms-comprobante-factura"), "Sum", 60, "notificaciones reintentadas")],
         w=12, h=9, min_=0, ylab="Eventos por minuto",
         desc=que("tras 'Fallo inyectado' aparecen reenvios y duplicados: el sistema entrega mas de una vez, pero las facturas emitidas no se duplican (el saldo sigue en 0).",
                  "Entrega at-least-once + consumidor idempotente (dedup en ingreso, Powertools idempotency en facturacion y comprobante)."))
    anno(b, "exp3", FASES_LEGACY["exp3"])
    b.save("exp3-cero-perdida.json", "_legacy")


# =========================================================== exp2 UNIFICADO (resiliencia: aislamiento + cero perdida)
b = Board("voltera-exp2-resiliencia", "Exp2 - Resiliencia ante fallos",
          "Un solo escenario: cae un dependiente, mueren pods, falla una Lambda y se reenvian duplicados; el ingreso no se cae y el saldo vuelve a 0. Pensado para grabar.",
          ["exp2", "video"], refresh="5s", time_from="now-15m")
DLQ_TX = m("A", "AWS/SQS", "ApproximateNumberOfMessagesVisible", {"QueueName": Q_TX_DLQ}, "Maximum", 60, "tx", "d1", True)
# --- fila de stats (lectura: izquierda -> derecha)
b.stat("ms-process-billing: el ingreso, no se cae",
       [expr("A", "MIN(SEARCH('{Voltera/Exp2,pod,service} MetricName=\"HealthCheckOk\" service=\"ms-process-billing\"', 'Minimum', 60))", "disponibilidad")],
       calc="lastNotNull", w=6, h=6, value_size=BIG, steps=[{"color": "red", "value": None}, {"color": "green", "value": 1}],
       mappings=[{"type": "value", "options": {"1": {"text": "EN LINEA", "color": "green"}, "0": {"text": "CAIDO", "color": "red"}}}],
       desc=que("ms-process-billing recibe las facturas (el ingreso) y debe decir EN LINEA durante TODO el escenario, incluso al matar sus pods y al caer el dependiente.",
                "Bulkhead: el fallo de un componente queda aislado; productor y consumidor desacoplados por mensajeria asincrona."))
b.stat("Servicio que se cae: fallas por minuto (ms-comprobante-factura / ms-tarifas)",
       [m("A", NS, "FallaInyectada", svc("ms-comprobante-factura"), "Sum", 60, "ms-comprobante-factura"),
        m("B", NS, "FallaInyectada", svc("ms-tarifas"), "Sum", 60, "ms-tarifas (caso A)")],
       calc="max", w=6, h=6, value_size=BIG, steps=[{"color": "green", "value": None}, {"color": "red", "value": 1}],
       desc=que("sube de 0 solo en la fase 'fallo_dependiente': ms-comprobante-factura (caso B) o ms-tarifas (caso A). Es el dependiente que se cae; el resto sigue.",
                "Bulkhead + Retry con backoff: el error queda en un solo dependiente y se reintenta antes de ir a la DLQ."))
b.stat("Facturas emitidas por ms-facturacion", [m("A", NS, "FacturasEmitidas", svc("ms-facturacion"), "Sum", 60, "emitidas")],
       calc="sum", w=6, h=6, value_size=BIG, steps=[{"color": "blue", "value": None}],
       desc=que("el contador no se congela durante los fallos: el flujo sigue facturando y termina con todas las facturas.",
                "Bulkhead + Outbox: lo inyectado queda registrado y el flujo avanza aunque algo falle."))
b.stat("SALDO de conservacion: inyectadas - (emitidas + rechazadas + DLQ)", q_loss_balance(), calc="lastNotNull", w=6, h=6, value_size=96,
       steps=[{"color": "red", "value": None}, {"color": "green", "value": 0}, {"color": "orange", "value": 1}],
       desc=que("0 (verde) = cero perdida. Naranja mientras hay trabajo en vuelo durante los fallos; debe volver a 0 tras 'recuperacion'. Rojo (negativo) = se contaron de mas.",
                "DLQ + Idempotencia + Outbox: at-least-once sin perder ni duplicar facturas."))
# --- Estado de los servicios en el tiempo (State timeline): protagonista de la narracion
def _lambda_state(refid, svc_name, k):
    fn = {"FunctionName": f"{P}-{svc_name}"}
    # AWS/Lambda Errors NO sirve: ms-comprobante-factura falla por registro (batchItemFailures) y su Errors vale 0.
    # Se usa FallaInyectada (Voltera/Exp2, dim service), emitida por maybe_fail en cada fallo inyectado.
    return [m(f"E{k}", NS, "FallaInyectada", svc(svc_name), "Sum", 60, f"fallas_{svc_name}", f"e{k}", True),
            m(f"I{k}", "AWS/Lambda", "Invocations", fn, "Sum", 60, f"inv_{svc_name}", f"i{k}", True),
            m(f"T{k}", "AWS/Lambda", "Throttles", fn, "Sum", 60, f"thr_{svc_name}", f"t{k}", True),
            expr(refid, f"IF(FILL(t{k},0)>0 || (FILL(e{k},0)>0 && FILL(e{k},0)>=FILL(i{k},0)), 0, IF(FILL(e{k},0)>0, 1, 2))", svc_name)]


_tl = []
_tl += [m("Hp", CI, "service_number_of_running_pods", {"ClusterName": CL, "Namespace": KNS, "Service": "ms-process-billing"}, "Maximum", 60, "pods", "pods", True),
        expr("Hh", "MIN(SEARCH('{Voltera/Exp2,pod,service} MetricName=\"HealthCheckOk\" service=\"ms-process-billing\"', 'Minimum', 60))", "salud", mid="hc", hide=True),
        m("Hr", NS, "MensajesReenviados", svc("ms-process-billing"), "Sum", 60, "reenvios", "re", True),
        expr("H", "IF(FILL(pods,0)==0 || FILL(hc,1)==0, 0, IF(RATE(pods)<0 || FILL(re,0)>0, 1, 2))", "ms-process-billing")]
for k, s_ in enumerate(["ms-tarifas", "ms-calculo-consumo-neto", "ms-facturacion", "ms-comprobante-factura"], 1):
    _tl += _lambda_state(f"L{k}", s_, k)
_st_map = [{"type": "value", "options": {"2": {"text": "OK", "color": "green", "index": 0}, "1": {"text": "DEGRADADO", "color": "yellow", "index": 1},
                                         "0": {"text": "OFF", "color": "red", "index": 2}}}]
b.add("state-timeline", "Estado de los servicios en el tiempo (eje X: hora; una fila por servicio)", _tl, w=24, h=9,
      desc=que("cada fila es un servicio y el color dice su estado minuto a minuto: verde OK, amarillo DEGRADADO, rojo OFF. Se espera: todo OK; ms-comprobante-factura OFF (fallo_dependiente); ms-process-billing DEGRADADO (fallo_pod); ms-facturacion DEGRADADO (fallo_lambda); todo OK en la recuperacion. "
               "Reglas. Lambdas (por minuto): OFF si hay throttles o errores >= invocaciones (FORCE_FAIL / concurrencia 0); DEGRADADO si hay errores pero menos que invocaciones (FAIL_RATE); OK si no hay errores (sin invocaciones cuenta como OK). "
               "ms-process-billing: OFF si 0 pods o HealthCheckOk=0; DEGRADADO si bajan los pods respecto al minuto anterior o hay MensajesReenviados>0 (pods muertos); OK en otro caso. "
               "Limites: ms-process-billing no tiene linea base de pods, por eso 'degradado' se infiere de la caida de pods o de reentregas (un escalado KEDA hacia abajo tambien se veria amarillo); con el minuto como resolucion minima, fallos de menos de 1 min se difuminan. Metrica minima recomendada: que ms-process-billing emita PodsEsperados (Gauge) para comparar contra los pods vivos.",
               "Bulkhead + observabilidad del aislamiento: se ve que un servicio cae y los demas siguen."),
      defaults={"mappings": _st_map, "color": {"mode": "thresholds"}, "min": 0, "max": 2, "noValue": "OK",
                "thresholds": {"mode": "absolute", "steps": [{"color": "red", "value": None}, {"color": "yellow", "value": 1}, {"color": "green", "value": 2}]},
                "custom": {"fillOpacity": 85, "lineWidth": 0}},
      options={"mergeValues": True, "showValue": "auto", "alignValue": "center", "rowHeight": 0.85, "legend": {"showLegend": True, "displayMode": "list", "placement": "bottom"},
               "tooltip": {"mode": "single"}})
# --- graficos A..E
b.ts("A) Facturas emitidas vs notificadas (acumuladas): emitir no espera a notificar",
     cumulative("A", NS, "FacturasEmitidas", svc("ms-facturacion"), "emitidas (ms-facturacion)", "e") +
     cumulative("B", NS, "FacturasNotificadas", svc("ms-comprobante-factura"), "notificadas (ms-comprobante-factura)", "n"),
     w=12, h=9, min_=0, ylab="Facturas acumuladas",
     desc=que("'emitidas' sigue subiendo aunque ms-comprobante-factura este caido; 'notificadas' se aplana en el fallo y alcanza a 'emitidas' tras la recuperacion.",
              "Bulkhead + desacople por cola: la emision no espera a la notificacion."))
b.ts("B) DLQ: mensajes apartados por servicio",
     [m("A", "AWS/SQS", "ApproximateNumberOfMessagesVisible", {"QueueName": Q_TX_DLQ}, "Maximum", 60, "DLQ transacciones (ms-tarifas / ms-calculo-consumo-neto / ms-facturacion)"),
      m("B", "AWS/SQS", "ApproximateNumberOfMessagesVisible", {"QueueName": Q_CO_DLQ}, "Maximum", 60, "DLQ comprobantes (ms-comprobante-factura)")],
     w=12, h=9, min_=0, ylab="Mensajes en la DLQ",
     desc=que("solo las DLQ, que son las que se acumulan: en 'fallo_dependiente' y 'fallo_lambda' suben las del servicio que falla; en 'recuperacion' vuelven a 0 tras el redrive. Nada se pierde: se aparta.",
              "Retry con backoff + DLQ: lo que no se procesa se aparta sin perderse y sin frenar al resto."))
b.ts("C) Pods de ms-process-billing y mensajes reenviados tras la muerte de un pod",
     [m("A", CI, "service_number_of_running_pods", {"ClusterName": CL, "Namespace": KNS, "Service": "ms-process-billing"}, "Maximum", 60, "ms-process-billing: pods en ejecucion"),
      m("B", NS, "MensajesReenviados", svc("ms-process-billing"), "Sum", 60, "MensajesReenviados (reentregas de Kafka)")],
     w=12, h=9, min_=0, ylab="Mensajes reenviados por minuto",
     overrides=[{"matcher": {"id": "byName", "options": "ms-process-billing: pods en ejecucion"}, "properties": [
         {"id": "custom.axisPlacement", "value": "right"}, {"id": "custom.axisLabel", "value": "Pods de ms-process-billing"},
         {"id": "custom.fillOpacity", "value": 0}, {"id": "custom.lineWidth", "value": 3}, {"id": "color", "value": {"mode": "fixed", "fixedColor": "orange"}}]}],
     desc=que("en 'fallo_pod' los pods bajan y Kubernetes los repone; los mensajes que tenian en mano se reentregan (MensajesReenviados > 0) y se procesan igual.",
              "Entrega at-least-once (Kafka no confirma hasta terminar) + replicas: el ingreso se recupera solo. Eje izq: reenvios; eje der: pods."))
b.ts("D) Duplicados reenviados a proposito y descartados por idempotencia",
     [m("A", NS, "MensajesDuplicados", svc("ms-process-billing"), "Sum", 60, "duplicados descartados en el ingreso (ms-process-billing)"),
      m("B", NS, "IdempotenciaReplays", svc("ms-facturacion"), "Sum", 60, "replays ignorados en ms-facturacion"),
      m("C", NS, "IdempotenciaReplays", svc("ms-comprobante-factura"), "Sum", 60, "replays ignorados en ms-comprobante-factura")],
     w=12, h=9, min_=0, ylab="Duplicados por minuto",
     desc=que("estas series valen 0 en todo el escenario SALVO en la fase 'duplicados' (copias reenviadas por SQS y Kafka a proposito): ahi suben, pero las facturas emitidas NO se duplican y el saldo sigue en 0.",
              "Idempotencia: el consumidor reconoce lo ya procesado y lo descarta (dedup en el ingreso, Powertools idempotency en facturacion y comprobante)."))
b.ts("E) Fallas inyectadas por servicio y errores de Step Functions",
     [expr("A", "SEARCH('{Voltera/Exp2,service} MetricName=\"FallaInyectada\"', 'Sum', 60)", "fallas inyectadas: ${PROP('Dim.service')}"),
      m("B", "AWS/States", "ExecutionsFailed", {"StateMachineArn": "$sfn"}, "Sum", 60, "Step Functions: ejecuciones fallidas"),
      m("C", "AWS/States", "ExecutionsTimedOut", {"StateMachineArn": "$sfn"}, "Sum", 60, "Step Functions: ejecuciones con timeout")],
     w=24, h=8, min_=0, ylab="Fallas por minuto",
     desc=que("las fallas inyectadas (metrica FallaInyectada) suben en 'fallo_dependiente' y 'fallo_lambda' (son los reintentos); 'fallidas' de Step Functions casi no se mueve porque el Catch manda a la DLQ y la ejecucion termina bien.",
              "Retry con backoff exponencial y Catch hacia DLQ en la orquestacion (Saga / Step Functions)."))
anno(b, "exp2")
b.save("exp2-resiliencia.json")

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
