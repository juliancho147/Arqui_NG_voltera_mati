import boto3
import pytest
from moto import mock_aws

import handler as h
from voltera_common import InjectedFault


def ev(fid="C1-F1", valor=1000.0, aprobado=True):
    return {"tx": {"cicloId": "C1", "facturaId": fid}, "tarifa": {"aprobado": True, "valorKwh": 1.0},
            "calculo": {"aprobado": aprobado, "valorCargo": valor}}


@pytest.fixture
def env(monkeypatch):
    with mock_aws():
        monkeypatch.setenv("TABLE_IDEMPOTENCIA", "idem")
        monkeypatch.setenv("IDEMPOTENCY_TTL_ATTR", "expiresAt")
        c = boto3.client("dynamodb")
        c.create_table(TableName="idem", KeySchema=[{"AttributeName": "facturaId", "KeyType": "HASH"}],
                       AttributeDefinitions=[{"AttributeName": "facturaId", "AttributeType": "S"}], BillingMode="PAY_PER_REQUEST")
        h._store = h._ddb = h._publisher = None
        yield c
        h._store = h._ddb = h._publisher = None


def test_emite_con_consecutivo_y_evento(env, ctx):
    r1 = h.handler(ev("C1-F1"), ctx)
    r2 = h.handler(ev("C1-F2"), ctx)
    assert (r1["numeroFactura"], r2["numeroFactura"]) == ("FV-000001", "FV-000002")
    assert h.get_publisher().backend.names() == ["FacturaEmitida", "FacturaEmitida"]


def test_idempotente_por_factura_id(env, ctx):
    r1 = h.handler(ev("C1-F1"), ctx)
    r2 = h.handler(ev("C1-F1"), ctx)   # reintento de Step Functions
    assert r1 == r2
    assert len(h.get_publisher().backend.messages) == 1  # no re-publica
    nxt = h.handler(ev("C1-F9"), ctx)
    assert nxt["numeroFactura"] == "FV-000002"  # el reintento no consumio consecutivo


def test_rechazo_de_negocio(env, ctx):
    r = h.handler(ev(valor=0.0), ctx)
    assert r["aprobado"] is False
    assert h.get_publisher().backend.names() == ["EmisionDeFacturaRechazada"]


def test_fallo_tecnico_libera_idempotencia_y_se_puede_reintentar(env, ctx, monkeypatch):
    monkeypatch.setenv("FORCE_FAIL", "true")
    with pytest.raises(InjectedFault):
        h.handler(ev(), ctx)
    monkeypatch.setenv("FORCE_FAIL", "false")
    r = h.handler(ev(), ctx)
    assert r["aprobado"] is True and r["numeroFactura"] == "FV-000001"


def test_metrica_replays(env, ctx, capsys):
    h.handler(ev("C1-F1"), ctx)
    capsys.readouterr()
    h.handler(ev("C1-F1"), ctx)
    assert "IdempotenciaReplays" in capsys.readouterr().out
