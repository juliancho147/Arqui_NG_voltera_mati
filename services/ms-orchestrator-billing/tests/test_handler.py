from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

import handler as h
from voltera_common import InjectedFault, parse_cloudevent


def mk(c, name, keys):
    c.create_table(TableName=name, KeySchema=[{"AttributeName": k, "KeyType": t} for k, t in keys],
                   AttributeDefinitions=[{"AttributeName": k, "AttributeType": "S"} for k, _ in keys], BillingMode="PAY_PER_REQUEST")


@pytest.fixture
def env(monkeypatch):
    with mock_aws():
        monkeypatch.setenv("TABLE_TRANSACCIONES", "tx")
        monkeypatch.setenv("TABLE_OUTBOX", "outbox")
        monkeypatch.setenv("N_SOLICITUDES", "10")
        c = boto3.client("dynamodb")
        mk(c, "tx", [("cicloId", "HASH"), ("facturaId", "RANGE")])
        mk(c, "outbox", [("eventId", "HASH")])
        t = boto3.resource("dynamodb").Table("tx")
        for i in range(1, 8):
            t.put_item(Item={"cicloId": "C1", "facturaId": f"C1-F{i:02d}", "clienteId": f"CL{i}", "tipoTarifa": "RESIDENCIAL",
                             "periodo": "2026-09", "consumoKwh": Decimal("100"), "excedentesKwh": Decimal("0")})
        h._ddb = None
        yield
        h._ddb = None


def outbox_items():
    return boto3.resource("dynamodb").Table("outbox").scan()["Items"]


def test_respeta_n_y_escribe_outbox(env, ctx, monkeypatch):
    r = h.handler({"detail": {"cicloId": "C1", "nSolicitudes": 5}}, ctx)
    assert r["total"] == 5 and r["outboxNuevos"] == 6
    items = outbox_items()
    inicio = [i for i in items if i["destino"] == "EVENTOS"]
    consumo = [i for i in items if i["destino"] == "INGRESO"]
    assert len(inicio) == 1 and len(consumo) == 5
    ev = parse_cloudevent(inicio[0]["payload"])
    assert ev.name == "CicloDeFacturacionIniciado" and ev.data["totalUnidades"] == 5 and ev.facturaid == "CICLO"
    c = parse_cloudevent(consumo[0]["payload"])
    assert c.name == "ConsumoFacturablePreparado" and c.data["clienteId"] and c.data["totalUnidades"] == 5
    assert consumo[0]["headers"] == {"cicloId": "C1", "facturaId": c.facturaid} and consumo[0]["key"] == c.facturaid
    assert "expiresAt" in consumo[0] and consumo[0]["estado"] == "PENDIENTE"


def test_n_por_env_y_menos_disponibles(env, ctx, monkeypatch):
    monkeypatch.setenv("N_SOLICITUDES", "100")
    assert h.handler({"cicloId": "C1"}, ctx)["total"] == 7


def test_redisparo_no_duplica_outbox(env, ctx):
    h.handler({"cicloId": "C1"}, ctx)
    r = h.handler({"cicloId": "C1"}, ctx)
    assert r["outboxNuevos"] == 0 and len(outbox_items()) == 8


def test_fallo_inyectado(env, ctx, monkeypatch):
    monkeypatch.setenv("FORCE_FAIL", "true")
    with pytest.raises(InjectedFault):
        h.handler({"cicloId": "C1"}, ctx)
