"""Modo demo (`python -m runner demo exp1|exp2|exp3`): un experimento por vez, pensado para grabarse en pantalla con Grafana en vivo.

* Banner por fase (estado inicial, disparo, fallo inyectado, acumulacion, recuperacion, veredicto) con la hora y pausa
  interactiva ("Enter para continuar") antes de cada una.
* Imprime cada comando AWS/kubectl relevante antes de ejecutarlo (las lecturas repetitivas se muestran una sola vez).
* Marca cada fase: archivo `reports/<run>/marcas.json`, metrica CloudWatch `FaseExperimento` (namespace Voltera/Exp2,
  dimensiones experimento+fase) y, si hay credenciales (GRAFANA_TOKEN o GRAFANA_PASSWORD), anotacion de Grafana.
* Al final: tabla PASS/FAIL y seccion nueva en experiments/RESULTADOS.md.
* Siempre restaura las Lambdas (finally + `python -m runner restore`).
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable

from . import actions
from .config import REPORTS_DIR
from .context import Context
from .report import FAIL, MANUAL, PASS, ExperimentResult, write_report
from .resultados import RESULTADOS_PATH, append_section
from .safety import Aborted, SafetyError

METRIC_NAMESPACE = "Voltera/Exp2"
METRIC_NAME = "FaseExperimento"
DASHBOARD_UID = {"exp1": "voltera-exp1-absorcion", "exp2": "voltera-exp2-aislamiento", "exp3": "voltera-exp3-cero-perdida"}
PHASE_TITLES = {
    "estado_inicial": "ESTADO INICIAL", "disparo": "DISPARO", "fallo_inyectado": "FALLO INYECTADO", "acumulacion": "ACUMULACION / OBSERVACION",
    "absorcion": "ABSORCION DEL PICO", "fallo_pod": "FALLO: MUERTE DE PODS", "fallo_lambda": "FALLO: LAMBDAS", "recuperacion": "RECUPERACION",
    "veredicto": "VEREDICTO",
}
WIDTH = 78


def _hora() -> str:
    return time.strftime("%H:%M:%S")


class Grafana:
    """Anotaciones via HTTP API. Desactivada si no hay credenciales (GRAFANA_TOKEN o GRAFANA_PASSWORD) o con --no-grafana."""

    def __init__(self, url: str | None = None, enabled: bool = True, env: dict | None = None):
        env = os.environ if env is None else env
        self.url = (url or env.get("GRAFANA_URL") or "http://localhost:3000").rstrip("/")
        self.headers = {"Content-Type": "application/json"}
        if env.get("GRAFANA_TOKEN"):
            self.headers["Authorization"] = f"Bearer {env['GRAFANA_TOKEN']}"
        elif env.get("GRAFANA_PASSWORD"):
            cred = f"{env.get('GRAFANA_USER', 'admin')}:{env['GRAFANA_PASSWORD']}"
            self.headers["Authorization"] = "Basic " + base64.b64encode(cred.encode()).decode()
        self.enabled = enabled and "Authorization" in self.headers
        self.failed = False

    def annotate(self, uid: str | None, text: str, tags: list[str], epoch_ms: int) -> bool:
        if not self.enabled or self.failed:
            return False
        body = {"time": epoch_ms, "text": text, "tags": tags}
        if uid:
            body["dashboardUID"] = uid
        req = urllib.request.Request(f"{self.url}/api/annotations", data=json.dumps(body).encode(), headers=self.headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=4) as resp:  # noqa: S310 - URL del operador
                return 200 <= resp.status < 300
        except Exception:  # noqa: BLE001
            self.failed = True
            return False


class Demo:
    def __init__(self, ctx: Context, exp_name: str, ciclo: str, run_dir: Path, *, pause: bool = True, grafana: Grafana | None = None,
                 out: Callable[[str], None] | None = None):
        self.ctx, self.exp, self.ciclo, self.run_dir = ctx, exp_name, ciclo, Path(run_dir)
        self.pause = pause
        self.grafana = grafana or Grafana(enabled=False)
        self.out = out or (lambda s: print(s, flush=True))
        self.marks: list[dict[str, Any]] = []
        self.cw_ok = True
        self.run_dir.mkdir(parents=True, exist_ok=True)

    # ---- enganche con el Context
    def attach(self) -> None:
        self.ctx.phase_hook = self.phase
        self.ctx.set_echo(lambda line: self.out(f"  $ {line}"))

    def detach(self) -> None:
        self.ctx.phase_hook = None
        self.ctx.set_echo(None)

    # ---- fases
    def _can_pause(self) -> bool:
        if not self.pause:
            return False
        return sys.stdin.isatty() if self.ctx.isatty is None else self.ctx.isatty

    def phase(self, name: str, description: str = "") -> None:
        title = PHASE_TITLES.get(name, name.upper())
        bar = "=" * WIDTH
        head = f" FASE {len(self.marks) + 1} · {title}"
        self.out(f"\n{bar}\n{head}{_hora():>{WIDTH - len(head)}}\n {description}\n{bar}")
        if self._can_pause():
            try:
                self.ctx.input_fn("  >> Enter para continuar (Ctrl-C aborta y restaura) ")
            except EOFError:
                pass
        self.mark(name, description)

    def mark(self, name: str, description: str = "") -> dict:
        now = time.time()
        m = {"fase": name, "descripcion": description, "hora": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(now)),
             "epochMs": int(now * 1000), "experimento": self.exp, "ciclo": self.ciclo}
        self.marks.append(m)
        self._write_marks()
        self._metric(name, now)
        if self.grafana.annotate(DASHBOARD_UID.get(self.exp), f"{self.exp} · {PHASE_TITLES.get(name, name)}: {description}",
                                 ["voltera", self.exp, name], m["epochMs"]):
            self.out(f"  [anotacion Grafana: {name}]")
        return m

    def _write_marks(self) -> None:
        data = {"experimento": self.exp, "ciclo": self.ciclo, "run": self.run_dir.name, "metrica": f"{METRIC_NAMESPACE}/{METRIC_NAME}",
                "marcas": self.marks}
        (self.run_dir / "marcas.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def _metric(self, fase: str, now: float) -> None:
        if not self.cw_ok:
            return
        try:
            from datetime import datetime, timezone
            self.ctx.client("cloudwatch").put_metric_data(Namespace=METRIC_NAMESPACE, MetricData=[{
                "MetricName": METRIC_NAME, "Dimensions": [{"Name": "experimento", "Value": self.exp}, {"Name": "fase", "Value": fase}],
                "Value": 1.0, "Unit": "Count", "Timestamp": datetime.fromtimestamp(now, tz=timezone.utc)}])
        except Exception as exc:  # noqa: BLE001 - la marca en archivo basta
            self.cw_ok = False
            self.out(f"  [aviso] no se pudo publicar {METRIC_NAME} en CloudWatch ({type(exc).__name__}); queda marcas.json")


def results_table(res: ExperimentResult) -> str:
    rows = [("Id", "Estado", "Criterio", "Observado")]
    for c in res.criteria:
        rows.append((c.id, c.status, c.title[:58], c.observed[:46]))
    w = [max(len(r[i]) for r in rows) for i in range(4)]
    line = "+" + "+".join("-" * (x + 2) for x in w) + "+"
    out = [line]
    for i, r in enumerate(rows):
        out.append("| " + " | ".join(r[j].ljust(w[j]) for j in range(4)) + " |")
        if i == 0:
            out.append(line)
    out.append(line)
    cnt = {s: sum(1 for c in res.criteria if c.status == s) for s in (PASS, FAIL, MANUAL)}
    out.append(f"VEREDICTO: {res.verdict}   ({cnt[PASS]} PASS, {cnt[FAIL]} FAIL, {cnt[MANUAL]} MANUAL)")
    return "\n".join(out)


def apply_demo_defaults(ctx: Context, exp_name: str) -> None:
    o = ctx.options
    if o.get("delay") is None and exp_name in ("exp1", "exp3"):
        o["delay"] = 2.0
    if exp_name == "exp1" and o.get("sla") is None:
        o["sla_scale"] = True   # SLA proporcional a N (ver Exp1.sla)
    if exp_name == "exp2" and o.get("case") is None:
        o["case"] = "B"          # B: el resto sigue facturando mientras cae el comprobante; A (ms-tarifas) con --case A


def run_demo(ctx: Context, exp_name: str, n: int, ciclo: str, experiments: dict, *, pause: bool = True, grafana: Grafana | None = None,
             resultados: Path | str | None = RESULTADOS_PATH, out: Callable[[str], None] | None = None) -> int:
    out = out or (lambda s: print(s, flush=True))
    apply_demo_defaults(ctx, exp_name)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    run_dir = Path(ctx.reports_dir) / f"{stamp}-demo-{exp_name}"
    demo = Demo(ctx, exp_name, ciclo, run_dir, pause=pause, grafana=grafana, out=out)
    exp = experiments[exp_name](ctx, n, ciclo)
    out(f"\n{'#' * WIDTH}\n DEMO {exp.title}\n ciclo {ciclo} · N={n} · region {ctx.cfg.region} · prefijo {ctx.cfg.prefix}\n"
        f" marcas: {run_dir / 'marcas.json'} · metrica {METRIC_NAMESPACE}/{METRIC_NAME}\n"
        f" Grafana: {'anotaciones activas -> ' + grafana.url if grafana and grafana.enabled else 'sin anotaciones (defina GRAFANA_TOKEN o GRAFANA_PASSWORD)'}"
        f" · dashboard uid {DASHBOARD_UID.get(exp_name)}\n{'#' * WIDTH}")
    out("Plan:")
    for i, s in enumerate(exp.plan(), 1):
        out(f"  {i:>2}. {s}")
    demo.attach()
    rc, res = 0, None
    try:
        res = exp.run()
    except (Aborted, SafetyError) as exc:
        out(f"Abortado: {exc}")
        rc = 2
    except KeyboardInterrupt:
        out("\nInterrumpido por el operador: restaurando...")
        rc = 130
    finally:
        demo.detach()
        pend = ctx.journal.pending()
        if pend:
            for line in actions.restore_all(ctx):
                out(f"  restaurado: {line}")
        left = ctx.journal.pending()
        out("Estado restaurado: sin fallos inyectados pendientes." if not left else
            f"ATENCION: quedan fallos sin revertir {[e['id'] for e in left]}. Ejecute: python -m runner restore")
    if res is None:
        return rc
    out_dir = write_report(res, ctx.reports_dir, stamp=f"{stamp}-demo")
    out(f"\n{results_table(res)}\n\nReporte: {out_dir}  ·  marcas: {out_dir / 'marcas.json'}")
    if resultados:
        try:
            num = append_section(res, out_dir, resultados)
            out(f"RESULTADOS.md: agregada la 'Prueba {num}' ({resultados})")
        except OSError as exc:
            out(f"[aviso] no se pudo escribir RESULTADOS.md: {exc}")
    return 1 if res.verdict == FAIL else rc
