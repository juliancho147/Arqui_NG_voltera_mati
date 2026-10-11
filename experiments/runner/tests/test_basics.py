import json

import pytest

from runner import actions, cli, evidence, mesh
from runner.config import Config, load_config, unwrap
from runner.kube import Kube, KubeResult
from runner.report import ExperimentResult, to_markdown, write_report
from runner.safety import Aborted, Journal, SafetyError, confirm, guard_name

TF = {
    "region": {"value": "us-east-1", "type": "string"},
    "dynamodb_tables": {"value": {"names": {"transacciones": "voltera-exp2-transacciones", "outbox": "voltera-exp2-outbox",
                                            "process-billing": "voltera-exp2-process-billing", "idem-facturacion": "voltera-exp2-idem-facturacion",
                                            "idem-comprobante": "voltera-exp2-idem-comprobante"}}, "type": "object"},
    "eventbridge": {"value": {"bus_name": "voltera-exp2-bus"}, "type": "object"},
    "sqs": {"value": {"transacciones": {"url": "u", "arn": "a", "dlq_url": "du", "dlq_arn": "da"},
                      "comprobantes": {"url": "u2", "arn": "a2", "dlq_url": "du2", "dlq_arn": "da2"}}, "type": "object"},
    "lambdas": {"value": {"ms-tarifas": {"name": "voltera-exp2-ms-tarifas", "arn": "x"}}, "type": "object"},
    "experiment_parameters": {"value": {"n_solicitudes": 7, "batch_sla_seconds": 99, "kafka_topic": "voltera.consumo-facturable-preparado"}, "type": "object"},
}


def test_unwrap_and_load_config(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps(TF))
    assert unwrap(TF)["region"] == "us-east-1"
    cfg = load_config(str(p), region="us-east-1")
    assert cfg.prefix == "voltera-exp2" and cfg.n_default == 7 and cfg.param("batch_sla_seconds") == 99
    assert cfg.queue("transacciones")["dlq_arn"] == "da" and cfg.lambda_name("ms-tarifas") == "voltera-exp2-ms-tarifas"
    assert cfg.lambda_name("ms-facturacion") == "voltera-exp2-ms-facturacion"  # derivado


def test_load_config_from_terraform_runner():
    calls = []

    class CP:
        returncode, stderr = 0, ""
        stdout = json.dumps(TF)

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return CP()
    cfg = load_config(tf_runner=fake_run)
    assert any("output" in c for c in calls[0]) and cfg.bus_name == "voltera-exp2-bus"


def test_dry_run_default_does_not_call_terraform():
    def boom(*a, **k):
        raise AssertionError("no debe llamar a terraform")
    assert load_config(dry_run=True, tf_runner=boom).placeholder


def test_guard_name():
    assert guard_name("voltera-exp2-ms-tarifas", "voltera-exp2")
    with pytest.raises(SafetyError):
        guard_name("produccion-ms-tarifas", "voltera-exp2")


def test_confirm_modes():
    confirm(["x"], yes=True)
    with pytest.raises(Aborted):
        confirm(["x"], yes=False, isatty=False)
    with pytest.raises(Aborted):
        confirm(["x"], yes=False, isatty=True, input_fn=lambda _: "n")
    confirm(["x"], yes=False, isatty=True, input_fn=lambda _: "s")


def test_journal(tmp_path):
    j = Journal(tmp_path / "j.json")
    a = j.record("lambda_env", "f", {"function": "f"})
    j.record("pod_delete", "ns/p", {}, revertible=False)
    assert [e["id"] for e in j.pending()] == [a]
    j.mark_restored(a)
    assert j.pending() == [] and len(j.all()) == 2


def test_kube_fake_runner_records_calls():
    k = Kube(runner=lambda a, t: KubeResult(0, json.dumps({"status": {"replicas": 2, "readyReplicas": 1}, "spec": {"replicas": 2}})), context="ctx")
    st = k.deployment_status("voltera", "ms-process-billing")
    assert st["replicas"] == 2 and st["ready"] == 1 and k.calls[0][:2] == ["--context", "ctx"]


def test_parse_console_line_and_names():
    ev = {"id": "e1", "type": "com.voltera.facturacion.tarifa-validada.v1", "cicloid": "C", "facturaid": "C-F0001"}
    line = f"Partition:2\tOffset:7\tcicloId:C,facturaId:C-F0001,content-type:application/cloudevents+json; charset=UTF-8\tC-F0001\t{json.dumps(ev)}"
    r = mesh.parse_console_line(line)
    assert (r.partition, r.offset, r.key, r.id) == (2, 7, "C-F0001", "e1") and r.headers["cicloId"] == "C"
    assert mesh.type_to_name(ev["type"]) == "TarifaValidada"
    assert mesh.parse_console_line("Processed a total of 3 messages") is None
    assert mesh.expected_types("OK", set()) == mesh.HAPPY_PATH
    assert mesh.expected_types("RECHAZADA", {"TarifaValidada", "CalculoDeCargoRechazado"}) == ["TarifaValidada", "CalculoDeCargoRechazado"]


def _event(name_kebab="tarifa-validada", data=None):
    return {"specversion": "1.0", "id": "i", "source": "/voltera/ms-tarifas", "type": f"com.voltera.facturacion.{name_kebab}.v1",
            "time": "2026-10-10T10:00:00.000Z", "subject": "C-F0001", "datacontenttype": "application/json", "cicloid": "C",
            "facturaid": "C-F0001", "data": data or {"cicloId": "C", "facturaId": "C-F0001"}}


def test_catalog_validates_real_asyncapi():
    cat = mesh.load_catalog()
    assert len(cat.by_type) >= 13
    assert cat.validate(_event()) == []
    assert cat.validate(_event("tarifa-rechazada", {"cicloId": "C", "facturaId": "C-F0001", "motivo": "x"})) == []
    bad = _event()
    del bad["cicloid"]
    assert cat.validate(bad)
    assert cat.validate(_event("tarifa-rechazada"))  # falta motivo
    assert cat.validate(_event("no-existe"))


def test_report_files(tmp_path):
    r = ExperimentResult("expX", "Titulo", "Hip")
    r.add("X.1", "ok", True, "a", "b", ids=[1, 2])
    r.add("X.2", "man", None)
    assert r.verdict == "PASS"
    r.add("X.3", "mal", False)
    assert r.verdict == "FAIL"
    out = write_report(r, tmp_path, "20261010-000000")
    assert json.loads((out / "report.json").read_text())["verdict"] == "FAIL"
    assert "| X.3 |" in (out / "report.md").read_text() and "FAIL" in to_markdown(r)


def test_cli_dry_run_never_touches_aws_or_kubectl(monkeypatch, capsys):
    import boto3
    monkeypatch.setattr(boto3, "Session", lambda *a, **k: (_ for _ in ()).throw(AssertionError("AWS")))
    monkeypatch.setattr("runner.kube.subprocess_runner", lambda *a, **k: (_ for _ in ()).throw(AssertionError("kubectl")))
    monkeypatch.setattr("subprocess.run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("subprocess")))
    assert cli.main(["all", "--dry-run", "--n", "4", "--ciclo-id", "T9"]) == 0
    out = capsys.readouterr().out
    for e in ("Exp. 1", "Exp. 2", "Exp. 4"):
        assert e in out
    assert "T9-EXP1" in out and "FORCE_FAIL" in out and "kubectl delete pod" in out


def test_cli_requires_confirmation_for_mutating(aws, tmp_path, capsys, monkeypatch):
    session, cfg = aws
    monkeypatch.setattr("sys.stdin.isatty", lambda: False, raising=False)
    cfgfile = tmp_path / "c.json"
    cfgfile.write_text(json.dumps({"runner": {}}))
    rc = cli.main(["exp2", "--ciclo-id", "T", "--reports-dir", str(tmp_path)],
                  ctx_factory=lambda a: cli.Context(cfg, yes=a.yes, session=session, reports_dir=tmp_path, options=cli._options(a)))
    assert rc == 2 and "confirmacion" in capsys.readouterr().err
