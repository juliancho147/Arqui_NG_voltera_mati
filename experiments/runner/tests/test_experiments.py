import pytest

from runner import actions
from runner.experiments.exp1 import Exp1
from runner.experiments.exp2 import Exp2
from runner.experiments.exp4 import Exp4


def status(res):
    return {c.id: c.status for c in res.criteria}


def lam_env(ctx, svc):
    return ctx.client("lambda").get_function_configuration(FunctionName=ctx.cfg.lambda_name(svc))["Environment"]["Variables"]


def test_exp1_pass(make):
    ctx, w = make()
    res = Exp1(ctx, 10, "C1").run()
    st = status(res)
    assert res.error is None, res.error
    assert st["E1.1"] == st["E1.2"] == st["E1.3"] == st["E1.4"] == st["E1.5"] == st["E1.6"] == st["E1.7"] == "PASS", st
    assert res.verdict == "PASS" and w.peak >= 2
    assert max(s["replicas"] for s in res.data["serie"]) >= 2


def test_exp1_fails_when_sla_exceeded_and_no_scale(make):
    ctx, w = make({"sla": 10})
    res = Exp1(ctx, 6, "C2").run()
    st = status(res)
    assert st["E1.2"] == "FAIL" and res.verdict == "FAIL"


def test_exp1_detects_lost_transaction(make):
    ctx, w = make({"timeout": 60})
    orig = w._step

    def lossy():
        orig()
        # simula perdida: una factura nunca avanza
        for k, s in w.f.items():
            if k[1].endswith("F0002") and s["stage"] in ("new", "claimed"):
                s["t"] = w.t + 10**6
    w._step = lossy
    res = Exp1(ctx, 4, "C3").run()
    st = status(res)
    assert st["E1.1"] == "FAIL" and st["E1.7"] == "FAIL"


FAST = {"observe": 5, "fault_window": 10, "dupl": 6, "timeout_metricas": 30, "poll_metricas": 5, "settle": 5, "timeout_inflight": 60}


def run_exp2(make, n=6, opts=None, **world_kw):
    kw = {"claim_every": 4.0}
    kw.update(world_kw)
    ctx, w = make({**FAST, **(opts or {})}, **kw)
    return ctx, w, Exp2(ctx, n, "C").run()


def test_exp2_unificado_caso_b_pass_y_restaura(make):
    ctx, w, res = run_exp2(make)
    assert res.error is None, res.error
    st = status(res)
    bad = {k: v for k, v in st.items() if v == "FAIL"}
    assert not bad, bad
    for k in ("E2.1", "E2.2", "E2.3", "E2.4", "E2.5", "E2.6", "E2.7", "E2.8", "E2.9", "E2.10", "E2.11", "E2.12", "E2.13", "E2.14", "E2.15"):
        assert st[k] == "PASS", (k, [c.observed for c in res.criteria if c.id == k])
    assert res.verdict == "PASS"
    assert w.deleted, "debio matar el pod"
    # duplicados: 6 por SQS (replays de idempotencia) y 6 por Kafka (descartados), sin facturas extra
    assert w.replays == 6 and w.kafka_dups == 6 and w.produced == 6
    assert lam_env(ctx, "ms-comprobante-factura")["FORCE_FAIL"] == "false"
    assert lam_env(ctx, "ms-facturacion")["FAIL_RATE"] == "0"
    assert ctx.journal.pending() == []
    kinds = [e["kind"] for e in ctx.journal.all()]
    assert kinds.count("lambda_env") == 2 and kinds.count("pod_delete") == 1
    assert any("AISLAMIENTO: PASS" in x for x in res.notes) and any("IDEMPOTENCIA: PASS" in x for x in res.notes)
    assert {s["fase"] for s in res.data["serieFallos"]} >= {"disparo", "fallo_dependiente", "recuperacion"}


def test_exp2_aislamiento_facturas_suben_y_dlq_se_drena(make):
    ctx, w, res = run_exp2(make, opts={"dupl": 0})
    serie = res.data["serieFallos"]
    assert serie[-1]["dlqComp"] == 0 and serie[-1]["colaComp"] == 0
    assert max(s["dlqComp"] for s in serie) >= 1, "el fallo del comprobante debio llenar la DLQ de comprobantes"
    em = [s["emitidas"] for s in serie]
    assert em == sorted(em) and em[-1] == 6
    assert status(res)["E2.5"] == "MANUAL" and w.replays == 0 and w.kafka_dups == 0


def test_exp2_caso_a_tarifas_cae_dlq_y_redrive(make):
    ctx, w, res = run_exp2(make, opts={"case": "A", "dupl": 4})
    assert res.error is None, res.error
    st = status(res)
    assert "FAIL" not in st.values(), st
    assert st["E2.6"] == "PASS" and st["E2.8"] == "PASS" and st["E2.9"] == "PASS" and st["E2.11"] == "PASS"
    assert max(s["dlqTx"] for s in res.data["serieFallos"]) >= 3, "ms-tarifas caido: las transacciones deben llegar a la DLQ de transacciones"
    assert lam_env(ctx, "ms-tarifas")["FORCE_FAIL"] == "false" and ctx.journal.pending() == []


def test_exp2_modo_concurrencia_restaura(make):
    ctx, w, res = run_exp2(make, opts={"fault_mode": "concurrency", "dupl": 0, "fail_rate": 0})
    assert "FAIL" not in status(res).values(), status(res)
    fn = ctx.cfg.lambda_name("ms-comprobante-factura")
    assert "ReservedConcurrentExecutions" not in ctx.client("lambda").get_function_concurrency(FunctionName=fn)
    assert [e["kind"] for e in ctx.journal.all()].count("lambda_env") == 0  # fail_rate=0: sin fallo parcial


def test_exp2_restaura_aunque_el_experimento_falle(make, monkeypatch):
    ctx, w = make(dict(FAST))
    monkeypatch.setattr(Exp2, "_fase_pod", lambda self, r, s: (_ for _ in ()).throw(RuntimeError("falla simulada del runner")))
    res = Exp2(ctx, 4, "C").run()
    assert res.error and "falla simulada" in res.error
    assert lam_env(ctx, "ms-comprobante-factura")["FORCE_FAIL"] == "false"
    assert ctx.journal.pending() == []


def test_exp2_detecta_facturas_duplicadas(make):
    ctx, w, res = run_exp2(make, n=4, duplicate_invoice=True)
    assert status(res)["E2.11"] == "FAIL" and res.verdict == "FAIL"


def test_exp2_detecta_perdida(make):
    ctx, w = make({**FAST, "timeout": 60, "timeout_recovery": 30})
    orig = w._step

    def lossy():
        orig()
        for k, st in w.f.items():
            if k[1].endswith("F0002") and st["stage"] in ("new", "claimed"):
                st["t"] = w.t + 10**6
    w._step = lossy
    res = Exp2(ctx, 4, "C").run()
    assert status(res)["E2.6"] == "FAIL" and res.verdict == "FAIL"


def test_exp2_kafka_sin_cabeceras_reintenta(make):
    ctx, w, res = run_exp2(make, reject_headers=True)
    assert status(res)["E2.5"] == "PASS" and w.kafka_dups == 6


def test_exp2_kafka_inviable_documenta_y_sigue_con_sqs(make):
    ctx, w = make(dict(FAST), claim_every=4.0)
    orig = w.kube.runner
    from runner.kube import KubeResult
    w.kube.runner = lambda args, t: KubeResult(1, "", "no se puede ejecutar el producer") if "kafka-console-producer" in " ".join(args) else orig(args, t)
    res = Exp2(ctx, 6, "C").run()
    c5 = next(c for c in res.criteria if c.id == "E2.5")
    assert c5.status == "MANUAL" and "SQS=6, Kafka=0" in c5.observed
    assert w.replays == 6 and status(res)["E2.12"] == "PASS" and status(res)["E2.11"] == "PASS"


def test_exp2_dry_run_muestra_todas_las_fases(make):
    ctx, w = make({"dupl": 50})
    plan = "\n".join(Exp2(ctx, 300, "C").plan())
    for fase in ("estado_inicial", "disparo", "fallo_dependiente", "fallo_pod", "fallo_lambda", "duplicados", "recuperacion", "veredicto"):
        assert f"[{fase}]" in plan, fase
    assert "kafka-console-producer" in plan and "SQS" in plan


def test_exp4_pass(make):
    ctx, w = make({"delay": 0})
    res = Exp4(ctx, 4, "C").run()
    assert res.error is None, res.error
    st = status(res)
    for k in ("E4.0", "E4.1", "E4.2", "E4.3", "E4.4", "E4.5", "E4.6", "E4.7", "E4.8"):
        assert st[k] == "PASS", (k, [c.observed for c in res.criteria if c.id == k])
    assert st["E4.8b"] == "MANUAL" and st["E4.9"] == "MANUAL" and st["E4.10"] == "MANUAL"
    assert len(res.data["lineaDeTiempo"]) == 4


def test_exp4_detects_missing_events(make):
    ctx, w = make({"delay": 0}, drop_event="FacturaEmitida")
    res = Exp4(ctx, 3, "C").run()
    st = status(res)
    assert st["E4.1"] == "FAIL" and res.verdict == "FAIL"
    assert "FacturaEmitida" in str(res.criteria[1].evidence["faltantes"])
