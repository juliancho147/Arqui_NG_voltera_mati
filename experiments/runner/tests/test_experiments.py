import pytest

from runner import actions
from runner.experiments.exp1 import Exp1
from runner.experiments.exp2 import Exp2
from runner.experiments.exp3 import Exp3
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


def test_exp2_both_cases_pass_and_restore(make):
    ctx, w = make()
    res = Exp2(ctx, 3, "C").run()
    assert res.error is None, res.error
    bad = {k: v for k, v in status(res).items() if v == "FAIL"}
    assert not bad, bad
    for k in ("E2.A.1", "E2.A.4", "E2.A.6", "E2.A.7", "E2.A.8", "E2.A.9", "E2.B.1", "E2.B.2", "E2.B.3", "E2.B.6", "E2.B.8", "E2.B.9"):
        assert status(res)[k] == "PASS", k
    assert lam_env(ctx, "ms-tarifas")["FORCE_FAIL"] == "false"
    assert lam_env(ctx, "ms-comprobante-factura")["FORCE_FAIL"] == "false"
    assert ctx.journal.pending() == []
    assert len(ctx.journal.all()) == 2


def test_exp2_restores_even_when_experiment_crashes(make, monkeypatch):
    ctx, w = make()
    real = actions.dispatch_cierre

    def boom(*a, **k):
        raise RuntimeError("falla simulada del runner")
    monkeypatch.setattr(actions, "dispatch_cierre", boom)
    res = Exp2(ctx, 3, "C", ).run()
    assert res.error and "falla simulada" in res.error
    assert lam_env(ctx, "ms-tarifas")["FORCE_FAIL"] == "false"
    assert ctx.journal.pending() == []


def test_exp2_concurrency_mode(make):
    ctx, w = make({"fault_mode": "concurrency", "case": "A"})
    res = Exp2(ctx, 3, "C").run()
    assert status(res)["E2.A.1"] == "PASS" and status(res)["E2.A.8"] == "PASS"
    fn = ctx.cfg.lambda_name("ms-tarifas")
    assert "ReservedConcurrentExecutions" not in ctx.client("lambda").get_function_concurrency(FunctionName=fn)


def test_exp3_conservation_and_no_duplicates(make):
    ctx, w = make({"fault_window": 10}, dlq_after=10**9)
    res = Exp3(ctx, 6, "C").run()
    assert res.error is None, res.error
    st = status(res)
    assert w.deleted, "debio matar el pod"
    for k in ("E3.1", "E3.2", "E3.3", "E3.4", "E3.5", "E3.6"):
        assert st[k] == "PASS", (k, [c for c in res.criteria if c.id == k])
    assert ctx.journal.pending() == []
    assert any(e["kind"] == "pod_delete" for e in ctx.journal.all())


def test_exp3_detects_duplicate_invoices(make):
    ctx, w = make({"fault_window": 5}, dlq_after=10**9, duplicate_invoice=True)
    res = Exp3(ctx, 4, "C").run()
    assert status(res)["E3.5"] == "FAIL" and res.verdict == "FAIL"


def test_exp3_comprobante_dlq_counts(make):
    # el fallo dura mas que dlq_after: los comprobantes caen a la DLQ de comprobantes (no se pierden, E3.6 lo acepta)
    ctx, w = make({"fault_window": 60}, dlq_after=5)
    res = Exp3(ctx, 4, "C").run()
    st = status(res)
    assert st["E3.4"] == "PASS" and st["E3.6"] == "PASS"


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
