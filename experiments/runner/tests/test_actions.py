import json

import pytest

from runner import actions, evidence
from runner.safety import SafetyError


def test_dispatch_seeds_and_puts_event(make):
    ctx, w = make()
    d = actions.dispatch_cierre(ctx, "CICLO-T1", 4, retardo_segundos=2)
    assert d["facturaIds"] == [f"CICLO-T1-F000{i}" for i in range(1, 5)]
    assert evidence.injected_ids(ctx, "CICLO-T1") == d["facturaIds"]
    item = ctx.table("transacciones").get_item(Key={"cicloId": "CICLO-T1", "facturaId": "CICLO-T1-F0001"})["Item"]
    assert float(item["retardoSegundos"]) == 2.0


def test_put_cierre_detail_format(make, aws):
    session, cfg = aws
    ctx, w = make()
    sent = {}
    real = ctx.client("events")

    class Spy:
        def put_events(self, **kw):
            sent.update(kw)
            return real.put_events(**kw)
    ctx._clients["events"] = Spy()
    actions.put_cierre_de_mes(ctx, "C1", 3)
    e = sent["Entries"][0]
    assert (e["Source"], e["DetailType"], e["EventBusName"]) == ("voltera.runner", "CierreDeMes", cfg.bus_name)
    assert json.loads(e["Detail"]) == {"cicloId": "C1", "nSolicitudes": 3}


def _env(ctx, svc):
    return ctx.client("lambda").get_function_configuration(FunctionName=ctx.cfg.lambda_name(svc))["Environment"]["Variables"]


def test_inject_and_restore_env(make):
    ctx, w = make()
    eid = actions.inject_fault(ctx, "ms-tarifas")
    assert _env(ctx, "ms-tarifas")["FORCE_FAIL"] == "true" and _env(ctx, "ms-tarifas")["OTRA"] == "x"
    assert [e["id"] for e in ctx.journal.pending()] == [eid]
    actions.restore_all(ctx)
    assert _env(ctx, "ms-tarifas") == {"FORCE_FAIL": "false", "FAIL_RATE": "0", "OTRA": "x"}
    assert ctx.journal.pending() == []


def test_inject_and_restore_concurrency(make):
    ctx, w = make()
    lam = ctx.client("lambda")
    fn = ctx.cfg.lambda_name("ms-comprobante-factura")
    actions.inject_fault(ctx, "ms-comprobante-factura", "concurrency")
    assert lam.get_function_concurrency(FunctionName=fn)["ReservedConcurrentExecutions"] == 0
    actions.restore_all(ctx)
    assert "ReservedConcurrentExecutions" not in lam.get_function_concurrency(FunctionName=fn)
    # con reserva previa
    lam.put_function_concurrency(FunctionName=fn, ReservedConcurrentExecutions=3)
    actions.inject_fault(ctx, "ms-comprobante-factura", "concurrency")
    actions.restore_all(ctx)
    assert lam.get_function_concurrency(FunctionName=fn)["ReservedConcurrentExecutions"] == 3


def test_restore_after_new_context_uses_journal(make):
    ctx, w = make()
    actions.inject_fault(ctx, "ms-tarifas")
    ctx2, _ = make()
    ctx2.journal = ctx.journal.__class__(ctx.journal.path)
    actions.restore_all(ctx2)
    assert _env(ctx, "ms-tarifas")["FORCE_FAIL"] == "false"


def test_guard_rejects_foreign_prefix(make):
    ctx, w = make()
    ctx.cfg.lambdas["ms-tarifas"] = {"name": "otra-cuenta-ms-tarifas", "arn": ""}
    with pytest.raises(SafetyError):
        actions.inject_fault(ctx, "ms-tarifas")
    assert ctx.journal.all() == []


def test_redrive_moves_messages_back(make):
    ctx, w = make()
    q = ctx.cfg.queue("transacciones")
    sqs = ctx.client("sqs")
    for i in range(3):
        sqs.send_message(QueueUrl=q["dlq_url"], MessageBody=json.dumps({"cicloId": "C", "facturaId": f"C-F000{i}"}))
    ids, aprox, _ = evidence.dlq_factura_ids(ctx, "transacciones", "C")
    assert len(ids) == 3 and aprox == 3
    res = actions.redrive_dlq(ctx, "transacciones")
    assert res["status"] == "COMPLETED"
    assert evidence.queue_total(evidence.queue_state(ctx, q["dlq_url"])) == 0
    assert evidence.queue_state(ctx, q["url"])["visibles"] == 3


def test_manual_redrive_fallback(make, monkeypatch):
    ctx, w = make()
    q = ctx.cfg.queue("comprobantes")
    ctx.client("sqs").send_message(QueueUrl=q["dlq_url"], MessageBody="{}")
    class NoApi:
        def __getattr__(self, n):
            return getattr(ctx.session.client("sqs"), n)
        def start_message_move_task(self, **kw):
            raise NotImplementedError
    ctx._clients["sqs"] = NoApi()
    assert actions.redrive_dlq(ctx, "comprobantes")["mode"] == "manual"
