import json
import random
from pathlib import Path

import pytest

from runner import cli, demo, evidence
from runner.context import render_aws_command
from runner.demo import Grafana, run_demo
from runner.experiments.exp1 import Exp1
from runner.report import ExperimentResult
from runner.resultados import MARKER, append_section, build_section, next_number

EXPS = cli.EXPERIMENTS

TEMPLATE = f"""# Resultados

## Prueba 1 — algo
- cosa

---
{MARKER}

```
## Prueba <n> — ...
```
"""


def lam_env(ctx, svc):
    return ctx.client("lambda").get_function_configuration(FunctionName=ctx.cfg.lambda_name(svc))["Environment"]["Variables"]


@pytest.fixture
def demo_ctx(make, tmp_path):
    inputs = []

    def build(options=None, **kw):
        ctx, w = make(options, **kw)
        ctx.isatty = True
        ctx.input_fn = lambda prompt="": inputs.append(prompt) or ""
        return ctx, w, inputs
    res = tmp_path / "RESULTADOS.md"
    res.write_text(TEMPLATE, encoding="utf-8")
    build.resultados = res
    return build


def phases(ctx):
    runs = sorted(Path(ctx.reports_dir).glob("*-demo-*"))
    assert runs, "no se creo la carpeta del run"
    data = json.loads((runs[-1] / "marcas.json").read_text(encoding="utf-8"))
    return [m["fase"] for m in data["marcas"]], runs[-1], data


def test_demo_exp1_phases_marks_metric_echo_and_resultados(demo_ctx, aws):
    ctx, w, inputs = demo_ctx({"delay": 1})
    out = []
    rc = run_demo(ctx, "exp1", 10, "CD1", EXPS, resultados=demo_ctx.resultados, out=out.append)
    fases, run_dir, data = phases(ctx)
    assert rc == 0, "\n".join(out)
    assert fases == ["estado_inicial", "disparo", "absorcion", "recuperacion", "veredicto"]
    assert len(inputs) == 5 and all("Enter para continuar" in p for p in inputs)
    # metrica CloudWatch
    cw = aws[0].client("cloudwatch")
    ms = cw.list_metrics(Namespace="Voltera/Exp2", MetricName="FaseExperimento")["Metrics"]
    assert {d["Value"] for m in ms for d in m["Dimensions"] if d["Name"] == "fase"} >= {"disparo", "veredicto"}
    assert all({d["Name"] for d in m["Dimensions"]} == {"experimento", "fase"} for m in ms)
    # eco de comandos
    text = "\n".join(out)
    assert "$ kubectl" in text and "get deploy ms-process-billing" in text
    assert "aws events put-events" in text and "aws sqs get-queue-attributes" in text
    assert "FASE 1 · ESTADO INICIAL" in text and "VEREDICTO: PASS" in text and "| E1.2" in text
    # RESULTADOS.md
    md = demo_ctx.resultados.read_text(encoding="utf-8")
    assert md.index("## Prueba 2 —") < md.index(MARKER) and "**PASS**" in md and "| Instante |" in md
    assert (run_dir / "report.md").exists()


def test_demo_exp2_case_b_default_restores_and_marks(demo_ctx):
    ctx, w, inputs = demo_ctx()
    out = []
    rc = run_demo(ctx, "exp2", 4, "CD2", EXPS, pause=False, resultados=None, out=out.append)
    fases, _, _ = phases(ctx)
    assert rc == 0, "\n".join(out)
    assert fases == ["estado_inicial", "fallo_inyectado", "disparo", "acumulacion", "recuperacion", "veredicto"]
    assert inputs == [], "--no-pause no debe preguntar"
    assert lam_env(ctx, "ms-comprobante-factura")["FORCE_FAIL"] == "false"
    assert ctx.journal.pending() == []
    assert all(c.id.startswith("E2.B") for c in [])  # solo caso B
    assert "aws lambda update-function-configuration" in "\n".join(out)
    assert "Estado restaurado" in "\n".join(out)


def test_exp2_serie_dlq_acumulandose_y_drenando(make):
    ctx, w = make({"case": "B"})
    from runner.experiments.exp2 import Exp2
    res = Exp2(ctx, 3, "C").run()
    serie = res.data["serieB"]
    assert serie and max(s["dlqComp"] for s in serie) >= 3 and serie[-1]["dlqComp"] == 0


def test_demo_exp3_fail_rate_and_restore(demo_ctx):
    ctx, w, inputs = demo_ctx({"fault_window": 10, "fail_rate": 0.3, "kill_pods": 2}, dlq_after=10**9)
    out = []
    rc = run_demo(ctx, "exp3", 6, "CD3", EXPS, pause=False, resultados=demo_ctx.resultados, out=out.append)
    fases, _, _ = phases(ctx)
    assert "fallo_pod" in fases and "fallo_lambda" in fases and fases[-1] == "veredicto"
    assert w.deleted
    assert lam_env(ctx, "ms-facturacion")["FAIL_RATE"] == "0" and lam_env(ctx, "ms-comprobante-factura")["FORCE_FAIL"] == "false"
    assert ctx.journal.pending() == []
    kinds = [e["kind"] for e in ctx.journal.all()]
    assert kinds.count("lambda_env") == 2
    assert rc == 0, "\n".join(out)
    assert "Prueba 2" in demo_ctx.resultados.read_text(encoding="utf-8")


def test_exp3_fail_rate_zero_skips_partial_fault(make):
    from runner.experiments.exp3 import Exp3
    ctx, w = make({"fault_window": 5, "fail_rate": 0}, dlq_after=10**9)
    Exp3(ctx, 4, "C").run()
    assert [e["target"].endswith("ms-comprobante-factura") for e in ctx.journal.all() if e["kind"] == "lambda_env"] == [True]


def test_ctrl_c_during_fault_restores(demo_ctx):
    ctx, w, inputs = demo_ctx()

    def hook(prompt=""):
        inputs.append(prompt)
        if len(inputs) == 4:  # fase 'acumulacion': el fallo esta activo
            assert lam_env(ctx, "ms-comprobante-factura")["FORCE_FAIL"] == "true"
            raise KeyboardInterrupt
        return ""
    ctx.input_fn = hook
    out = []
    rc = run_demo(ctx, "exp2", 3, "CD4", EXPS, resultados=None, out=out.append)
    assert rc == 130
    assert lam_env(ctx, "ms-comprobante-factura")["FORCE_FAIL"] == "false"
    assert ctx.journal.pending() == []


def test_metric_failure_falls_back_to_file(demo_ctx, monkeypatch):
    ctx, w, _ = demo_ctx()
    d = demo.Demo(ctx, "exp1", "C", Path(ctx.reports_dir) / "x", pause=False, out=lambda s: None)
    monkeypatch.setattr(ctx, "client", lambda s: (_ for _ in ()).throw(RuntimeError("sin permisos")))
    d.mark("disparo", "x")
    assert d.cw_ok is False
    assert json.loads((d.run_dir / "marcas.json").read_text())["marcas"][0]["fase"] == "disparo"


# ---------------------------------------------------------------- unidades
def test_render_aws_command():
    line, mut, _ = render_aws_command("sqs", "GetQueueAttributes", {"QueueUrl": "https://sqs.x/123/q", "AttributeNames": ["All"]})
    assert line == "aws sqs get-queue-attributes --queue-url q --attribute-names ['All']" and not mut
    line, mut, _ = render_aws_command("lambda", "UpdateFunctionConfiguration", {"FunctionName": "f"})
    assert line == "aws lambda update-function-configuration --function-name f" and mut


def test_grafana_disabled_without_credentials_and_posts_with_token(monkeypatch):
    assert Grafana(env={}).enabled is False and Grafana(env={}).annotate("u", "t", [], 1) is False
    seen = {}

    class Resp:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake(req, timeout):
        seen["url"], seen["body"], seen["auth"] = req.full_url, json.loads(req.data), req.headers["Authorization"]
        return Resp()
    monkeypatch.setattr(demo.urllib.request, "urlopen", fake)
    g = Grafana("http://g:3000/", env={"GRAFANA_TOKEN": "tok"})
    assert g.annotate("voltera-exp1-absorcion", "txt", ["a"], 5) is True
    assert seen["url"] == "http://g:3000/api/annotations" and seen["body"]["dashboardUID"] == "voltera-exp1-absorcion"
    assert seen["auth"] == "Bearer tok"
    monkeypatch.setattr(demo.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    assert g.annotate(None, "t", [], 1) is False and g.failed


def test_append_section_numbering_and_template_kept(tmp_path):
    f = tmp_path / "R.md"
    f.write_text(TEMPLATE, encoding="utf-8")
    r = ExperimentResult("exp3", "Exp. 3", "h", started="a", finished="b", params={"N": 5, "cicloId": "C"})
    r.add("E3.1", "algo", True, "x", "x")
    r.add("E3.2", "otro", False, "x", "y")
    assert append_section(r, tmp_path / "20261011-demo-exp3", f) == 2
    assert append_section(r, tmp_path / "20261011-demo-exp3", f) == 3
    md = f.read_text(encoding="utf-8")
    assert md.count(MARKER) == 1 and md.index("## Prueba 3") < md.index(MARKER)
    assert "E3.2 FAIL" in md and "(1 PASS, 1 FAIL, 0 MANUAL)" in md and next_number(md) == 4
    assert "reports/20261011-demo-exp3/" in build_section(r, 9, "x/20261011-demo-exp3")


def test_sla_scales_with_n(make):
    ctx, _ = make({"delay": 2, "sla_scale": True})
    assert Exp1(ctx, 10, "C").sla == 120
    assert Exp1(ctx, 500, "C").sla == 500 * 2 / 5 * 1.5 + 60
    ctx.options["sla_per_msg"] = 1.0
    assert Exp1(ctx, 500, "C").sla == 500
    ctx.options["sla"] = 77
    assert Exp1(ctx, 500, "C").sla == 77


def test_peek_queue_covers_large_random_sampling():
    ids = [f"m{i}" for i in range(500)]
    rng = random.Random(1)

    class Q:
        def receive_message(self, **kw):
            return {"Messages": [{"MessageId": i, "Body": json.dumps({"cicloId": "C", "facturaId": i})} for i in rng.sample(ids, 10)]}

    class Ctx:
        def client(self, s): return Q()
    got = evidence.peek_queue(Ctx(), "u", max_messages=550)
    assert len(got) >= 475  # muestra aleatoria: cubre casi todo
    assert evidence.dlq_covers(ids, {g["body"]["facturaId"] for g in got}, 500)
    assert not evidence.dlq_covers(ids[:50], set(ids[:49]), 50)


def test_cli_demo_parser_and_dry_run(capsys):
    a = cli.build_parser().parse_args(["demo", "exp3", "--n", "500", "--delay", "2", "--fail-rate", "0", "--kill-pods", "2", "--no-pause"])
    assert a.exp == "exp3" and a.n == 500 and a.no_pause
    assert cli._options(a)["fail_rate"] == 0 and cli._options(a)["kill_pods"] == 2
    assert cli.main(["demo", "exp2", "--dry-run", "--n", "500"]) == 0
    assert "DRY-RUN demo" in capsys.readouterr().out
