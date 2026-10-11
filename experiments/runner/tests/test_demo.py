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


FASES_EXP2 = ["estado_inicial", "disparo", "fallo_dependiente", "fallo_pod", "fallo_lambda", "duplicados", "recuperacion", "veredicto"]
OPTS = {"observe": 5, "fault_window": 10, "dupl": 6, "timeout_metricas": 30, "poll_metricas": 5, "settle": 5, "timeout_inflight": 60,
        "fail_rate": 0.3, "kill_pods": 2}


def test_demo_exp2_unificado_fases_marcas_metrica_y_restauracion(demo_ctx, aws):
    ctx, w, inputs = demo_ctx(dict(OPTS), claim_every=4.0)
    out = []
    rc = run_demo(ctx, "exp2", 6, "CD2", EXPS, resultados=demo_ctx.resultados, out=out.append)
    fases, run_dir, data = phases(ctx)
    text = "\n".join(out)
    assert rc == 0, text
    assert fases == FASES_EXP2
    assert len(inputs) == 8 and all("Enter para continuar" in p for p in inputs), "una pausa Enter por fase"
    assert data["experimento"] == "exp2"
    cw = aws[0].client("cloudwatch")
    ms = cw.list_metrics(Namespace="Voltera/Exp2", MetricName="FaseExperimento")["Metrics"]
    assert {d["Value"] for m in ms for d in m["Dimensions"] if d["Name"] == "fase"} == set(FASES_EXP2)
    assert {d["Value"] for m in ms for d in m["Dimensions"] if d["Name"] == "experimento"} == {"exp2"}
    assert w.deleted and w.replays == 6 and w.kafka_dups == 6
    assert lam_env(ctx, "ms-comprobante-factura")["FORCE_FAIL"] == "false" and lam_env(ctx, "ms-facturacion")["FAIL_RATE"] == "0"
    assert ctx.journal.pending() == []
    assert "FASE 3 · FALLO: DEPENDIENTE CAIDO" in text and "FASE 6 · DUPLICADOS A PROPOSITO" in text and "Estado restaurado" in text
    assert "aws lambda update-function-configuration" in text and "kafka-console-producer" in text and "aws sqs send-message-batch" in text
    md = demo_ctx.resultados.read_text(encoding="utf-8")
    assert "Prueba 2" in md and "| Instante | Fase |" in md and "Resiliencia ante fallos" in md


def test_demo_exp3_es_alias_de_exp2(demo_ctx):
    ctx, w, inputs = demo_ctx(dict(OPTS), claim_every=4.0)
    out = []
    rc = run_demo(ctx, "exp3", 4, "CD3", EXPS, pause=False, resultados=None, out=out.append)
    fases, _, data = phases(ctx)
    assert rc == 0 and fases == FASES_EXP2 and data["experimento"] == "exp2"
    assert "se unio al exp2" in "\n".join(out) and inputs == []


def test_ctrl_c_durante_el_fallo_restaura(demo_ctx):
    ctx, w, inputs = demo_ctx(dict(OPTS), claim_every=4.0)

    def hook(prompt=""):
        inputs.append(prompt)
        if len(inputs) == 5:  # fase 'fallo_lambda': dependiente caido y, tras la inyeccion, FAIL_RATE
            assert lam_env(ctx, "ms-comprobante-factura")["FORCE_FAIL"] == "true"
            raise KeyboardInterrupt
        return ""
    ctx.input_fn = hook
    out = []
    rc = run_demo(ctx, "exp2", 4, "CD4", EXPS, resultados=None, out=out.append)
    assert rc == 130
    assert lam_env(ctx, "ms-comprobante-factura")["FORCE_FAIL"] == "false"
    assert ctx.journal.pending() == []


def test_ctrl_c_con_fail_rate_activo_restaura(demo_ctx):
    ctx, w, inputs = demo_ctx(dict(OPTS), claim_every=4.0)

    def hook(prompt=""):
        inputs.append(prompt)
        if len(inputs) == 6:  # fase 'duplicados': tras la ventana de FAIL_RATE
            raise KeyboardInterrupt
        return ""
    ctx.input_fn = hook
    rc = run_demo(ctx, "exp2", 4, "CD5", EXPS, resultados=None, out=lambda s: None)
    assert rc == 130
    assert lam_env(ctx, "ms-comprobante-factura")["FORCE_FAIL"] == "false" and lam_env(ctx, "ms-facturacion")["FAIL_RATE"] == "0"
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
    r = ExperimentResult("exp2", "Exp. 2", "h", started="a", finished="b", params={"N": 5, "cicloId": "C"})
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
    a = cli.build_parser().parse_args(["demo", "exp2", "--n", "500", "--delay", "2", "--fail-rate", "0", "--kill-pods", "2", "--dupl", "50", "--no-pause"])
    assert a.exp == "exp2" and a.n == 500 and a.no_pause
    o = cli._options(a)
    assert o["fail_rate"] == 0 and o["kill_pods"] == 2 and o["dupl"] == 50
    assert cli.main(["demo", "exp2", "--dry-run", "--n", "500"]) == 0
    out = capsys.readouterr().out
    assert "DRY-RUN demo" in out
    for fase in ("estado_inicial", "disparo", "fallo_dependiente", "fallo_pod", "fallo_lambda", "duplicados", "recuperacion", "veredicto"):
        assert f"[{fase}]" in out, fase


def test_cli_exp3_alias_avisa_y_muestra_el_plan_de_exp2(capsys):
    assert cli.main(["demo", "exp3", "--dry-run", "--n", "100"]) == 0
    cap = capsys.readouterr()
    assert "se unio al Exp. 2" in cap.err and "[duplicados]" in cap.out
    assert cli.main(["exp3", "--dry-run", "--n", "100"]) == 0
    cap = capsys.readouterr()
    assert "se unio al Exp. 2" in cap.err and "Resiliencia ante fallos" in cap.out
    assert cli.main(["all", "--dry-run", "--n", "10"]) == 0
    assert "Exp. 3" not in capsys.readouterr().out
