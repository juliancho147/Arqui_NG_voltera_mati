"""CLI: python -m runner exp1|exp2|exp4|all|restore|demo <exp> [opciones]  (exp3 = alias de exp2)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import actions
from .config import REPORTS_DIR, ConfigError, load_config
from .context import Context
from .demo import ALIASES, Grafana, apply_demo_defaults, run_demo
from .experiments.exp1 import Exp1
from .experiments.exp2 import Exp2
from .experiments.exp4 import Exp4
from .report import write_report
from .resultados import RESULTADOS_PATH
from .safety import Aborted, SafetyError

EXPERIMENTS = {"exp1": Exp1, "exp2": Exp2, "exp4": Exp4}   # exp3 es alias de exp2 (ver demo.ALIASES)
ALIAS_AVISO = "AVISO: el antiguo Exp. 3 (cero perdida) se unio al Exp. 2 (Resiliencia ante fallos: aislamiento + cero perdida); se ejecuta exp2."


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    g = common.add_argument_group("generales")
    g.add_argument("--n", "--n-solicitudes", dest="n", type=int, default=None, help="N_SOLICITUDES (por defecto el de terraform, 10)")
    g.add_argument("--ciclo-id", default=None, help="cicloId (por defecto EXP-<UTC timestamp>)")
    g.add_argument("--dry-run", action="store_true", help="imprime el plan de acciones sin llamar a AWS ni a kubectl")
    g.add_argument("--config", default=None, help="JSON con salidas de `terraform output -json` (si no, se leen de terraform base/platform)")
    g.add_argument("--yes", "-y", action="store_true", help="no pedir confirmacion interactiva (exp2/exp3 modifican estado)")
    g.add_argument("--region", default=None, help="region AWS (var AWS_REGION; por defecto us-east-1)")
    g.add_argument("--profile", default=None, help="perfil AWS (var AWS_PROFILE)")
    g.add_argument("--prefix", default=None, help="prefijo del proyecto; solo se actua sobre recursos que lo usen (var VOLTERA_PREFIX)")
    g.add_argument("--kube-context", default=None, help="contexto de kubectl")
    g.add_argument("--reports-dir", default=str(REPORTS_DIR))
    t = common.add_argument_group("ajustes de experimentos")
    t.add_argument("--delay", type=float, default=None, help="retardo simulado por mensaje (s) en process-billing (exp1/exp2)")
    t.add_argument("--sla", type=float, default=None, help="SLA del lote en s (exp1)")
    t.add_argument("--fault-mode", choices=["env", "concurrency"], default="env", help="exp2: FORCE_FAIL=true o concurrencia reservada 0")
    t.add_argument("--case", choices=["A", "B", "a", "b"], default=None, help="exp2: dependiente que cae: A (ms-tarifas) o B (ms-comprobante-factura, defecto)")
    t.add_argument("--timeout", type=float, default=None, help="tope de espera principal en s")
    t.add_argument("--poll", type=float, default=None, help="intervalo de muestreo en s")
    t.add_argument("--scaledown-timeout", type=float, default=None)
    t.add_argument("--skip-scaledown", action="store_true")
    t.add_argument("--fault-window", type=float, default=None, help="exp2: segundos que dura el fallo parcial (FAIL_RATE) en ms-facturacion")
    t.add_argument("--graceful", action="store_true", help="exp2: apagado ordenado del pod en vez de --force --grace-period=0")
    t.add_argument("--no-dispatch", action="store_true", help="exp4: auditar un ciclo ya ejecutado")
    t.add_argument("--asyncapi", default=None)
    t.add_argument("--sla-per-msg", dest="sla_per_msg", type=float, default=None, help="exp1: SLA = max(base, N x este valor en s/mensaje)")
    t.add_argument("--sla-factor", dest="sla_factor", type=float, default=None, help="exp1 con --sla-scale/demo: holgura sobre el ideal N*delay/replicas_max (1.5)")
    t.add_argument("--sla-scale", dest="sla_scale", action="store_true", help="exp1: SLA proporcional a N (siempre activo en demo)")
    t.add_argument("--time-per-msg", dest="time_per_msg", type=float, default=None, help="segundos extra de timeout por mensaje sobre 10 (exp2)")
    t.add_argument("--fail-rate", dest="fail_rate", type=float, default=None, help="exp2: FAIL_RATE (0..1) en ms-facturacion durante la ventana (0 = sin fallo parcial; defecto 0.25)")
    t.add_argument("--kill-pods", dest="kill_pods", type=int, default=None, help="exp2: cuantos pods de process-billing matar (defecto 1)")
    t.add_argument("--dupl", "--duplicates", dest="dupl", type=int, default=None, help="exp2: copias de mensajes ya enviados que se reenvian a proposito por SQS y Kafka (defecto 50; 0 = omitir)")
    t.add_argument("--observe", type=float, default=None, help="exp2: segundos de observacion tras inyectar el fallo del dependiente (defecto 30)")
    t.add_argument("--timeout-metricas", dest="timeout_metricas", type=float, default=None, help="exp2: espera maxima (s) a que CloudWatch refleje replays/duplicados (defecto 150)")

    d = argparse.ArgumentParser(add_help=False)
    dg = d.add_argument_group("demo")
    dg.add_argument("--no-pause", action="store_true", help="demo: sin pausas interactivas")
    dg.add_argument("--no-grafana", action="store_true", help="demo: no escribir anotaciones en Grafana")
    dg.add_argument("--grafana-url", default=None, help="demo: URL de Grafana (var GRAFANA_URL; defecto http://localhost:3000). Credenciales: GRAFANA_TOKEN o GRAFANA_USER/GRAFANA_PASSWORD")
    dg.add_argument("--resultados", default=None, help="demo: ruta de RESULTADOS.md (defecto experiments/RESULTADOS.md)")
    dg.add_argument("--no-resultados", action="store_true", help="demo: no modificar RESULTADOS.md")

    p = argparse.ArgumentParser(prog="python -m runner", description="Runner de la experimentacion 2 de Voltera.")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, cls in EXPERIMENTS.items():
        sub.add_parser(name, parents=[common], help=cls.title)
    dm = sub.add_parser("demo", parents=[common, d], help="modo demo para grabar UN experimento: pausas, banners, marcas y RESULTADOS.md")
    dm.add_argument("exp", choices=["exp1", "exp2", "exp3"], help="exp3 es alias de exp2")
    sub.add_parser("exp3", parents=[common], help="alias de exp2 (se unio al Exp. 2)")
    sub.add_parser("all", parents=[common], help="exp1, exp2 y exp4 en orden")
    rs = sub.add_parser("restore", parents=[common], help="revierte los cambios pendientes de la bitacora (fallos inyectados)")
    rs.add_argument("--list", action="store_true", help="solo listar los cambios registrados")
    return p


def _options(a) -> dict:
    keys = ["delay", "sla", "fault_mode", "case", "timeout", "poll", "scaledown_timeout", "skip_scaledown", "fault_window",
            "graceful", "dupl", "observe", "timeout_metricas", "no_dispatch", "asyncapi", "sla_per_msg", "sla_factor", "sla_scale", "time_per_msg", "fail_rate", "kill_pods"]
    return {k: getattr(a, k) for k in keys if getattr(a, k, None) is not None and getattr(a, k, None) is not False}


def make_context(a, **kw) -> Context:
    cfg = load_config(a.config, dry_run=a.dry_run, region=a.region, profile=a.profile, prefix=a.prefix)
    if a.kube_context:
        cfg.kube_context = a.kube_context
    return Context(cfg, yes=a.yes, dry_run=a.dry_run, reports_dir=Path(a.reports_dir), options=_options(a), **kw)


def cmd_restore(a, ctx: Context) -> int:
    entries = ctx.journal.all()
    pend = ctx.journal.pending()
    if a.list or a.dry_run:
        print(f"{len(entries)} cambios registrados, {len(pend)} pendientes de revertir ({ctx.journal.path}):")
        for e in entries:
            print(f"  [{'PENDIENTE' if e in pend else 'ok'}] {e['id']} {e['ts']} {e['kind']} {e['target']} antes={e['before']}")
        return 0
    if not pend:
        print("Nada que restaurar.")
        return 0
    ctx.confirm([f"revertir {e['kind']} en {e['target']} a {e['before']}" for e in pend])
    for line in actions.restore_all(ctx):
        print(line)
    left = ctx.journal.pending()
    print("Restauracion completa." if not left else f"AUN PENDIENTES: {[e['id'] for e in left]}")
    return 0 if not left else 1


def main(argv: list[str] | None = None, *, ctx_factory=None) -> int:
    a = build_parser().parse_args(argv)
    try:
        ctx = ctx_factory(a) if ctx_factory else make_context(a)
    except ConfigError as exc:
        print(f"Error de configuracion: {exc}", file=sys.stderr)
        return 2
    if a.cmd == "restore":
        try:
            return cmd_restore(a, ctx)
        except (Aborted, SafetyError) as exc:
            print(f"Abortado: {exc}", file=sys.stderr)
            return 2
    if a.cmd in ALIASES:
        print(ALIAS_AVISO, file=sys.stderr)
        a.cmd = ALIASES[a.cmd]
    if a.cmd == "demo" and a.exp in ALIASES:
        print(ALIAS_AVISO, file=sys.stderr)
        a.exp = ALIASES[a.exp]
    names = list(EXPERIMENTS) if a.cmd == "all" else [a.cmd]
    n = a.n or ctx.cfg.n_default
    base_ciclo = a.ciclo_id or actions.new_ciclo_id()
    if a.cmd == "demo":
        if a.dry_run:
            print(f"# DRY-RUN demo: N={n}")
            apply_demo_defaults(ctx, a.exp)
            exp = EXPERIMENTS[a.exp](ctx, n, base_ciclo)
            for i, s in enumerate(exp.plan(), 1):
                print(f"{i:>2}. {s}")
            return 0
        res_path = None if a.no_resultados else (a.resultados or RESULTADOS_PATH)
        return run_demo(ctx, a.exp, n, base_ciclo, EXPERIMENTS, pause=not a.no_pause,
                        grafana=Grafana(a.grafana_url, enabled=not a.no_grafana), resultados=res_path)
    if a.dry_run:
        print(f"# DRY-RUN: no se llama a AWS ni a kubectl (config {'por defecto' if ctx.cfg.placeholder else 'cargada'}, "
              f"region {ctx.cfg.region}, prefijo {ctx.cfg.prefix}, N={n})")
    rc = 0
    for name in names:
        ciclo = base_ciclo if len(names) == 1 else f"{base_ciclo}-{name.upper()}"
        exp = EXPERIMENTS[name](ctx, n, ciclo)
        if a.dry_run:
            print(f"\n## {exp.title}" + ("  [modifica estado: pedira confirmacion]" if exp.mutates else ""))
            for i, s in enumerate(exp.plan(), 1):
                print(f"{i:>2}. {s}")
            if exp.mutates:
                print("    Cambios a registrar/revertir:")
                for m in exp.mutations():
                    print(f"      - {m}")
            continue
        try:
            res = exp.run()
        except (Aborted, SafetyError) as exc:
            print(f"Abortado: {exc}", file=sys.stderr)
            return 2
        out = write_report(res, ctx.reports_dir)
        print(f"\n== {res.title}: {res.verdict}  (reporte: {out})")
        for c in res.criteria:
            print(f"  [{c.status:6}] {c.id} {c.title}" + (f" -> {c.observed}" if c.status != 'PASS' else ""))
        if res.error:
            print(f"  ERROR: {res.error.splitlines()[0]}")
        if res.verdict == "FAIL":
            rc = 1
    return rc
