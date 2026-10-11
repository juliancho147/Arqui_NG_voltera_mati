from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

import handler as h
from voltera_common import InjectedFault

TX = {"cicloId": "C1", "facturaId": "C1-F1"}
TARIFA = {"aprobado": True, "valorKwh": 650.0}


@pytest.fixture
def table(monkeypatch):
    with mock_aws():
        monkeypatch.setenv("TABLE_TRANSACCIONES", "tx")
        ddb = boto3.resource("dynamodb")
        t = ddb.create_table(
            TableName="tx",
            KeySchema=[{"AttributeName": "cicloId", "KeyType": "HASH"}, {"AttributeName": "facturaId", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "cicloId", "AttributeType": "S"}, {"AttributeName": "facturaId", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        h._table = None
        h._publisher = None
        yield t
        h._table = None
        h._publisher = None


def put(t, consumo, exced, fid="C1-F1"):
    t.put_item(Item={"cicloId": "C1", "facturaId": fid, "consumoKwh": Decimal(str(consumo)), "excedentesKwh": Decimal(str(exced))})


def test_calculo_neto(table, ctx):
    put(table, 200, 50)
    r = h.handler({"tx": TX, "tarifa": TARIFA}, ctx)
    assert r == {"aprobado": True, "consumoNetoKwh": 150.0, "valorCargo": 97500.0, "moneda": "COP"}
    ev = h.get_publisher().backend.events()
    assert [e.name for e in ev] == ["CargoEnergeticoCalculado"]
    assert ev[0].data["valorCargo"] == 97500.0


def test_excedentes_superan_consumo_rechaza(table, ctx):
    put(table, 10, 50)
    r = h.handler({"tx": TX, "tarifa": TARIFA}, ctx)
    assert r["aprobado"] is False and r["motivo"] == "EXCEDENTES_SUPERAN_CONSUMO"
    assert h.get_publisher().backend.names() == ["CalculoDeCargoRechazado"]


def test_transaccion_inexistente_rechaza(table, ctx):
    assert h.handler({"tx": TX, "tarifa": TARIFA}, ctx)["motivo"] == "TRANSACCION_NO_ENCONTRADA"


def test_fallo_tecnico(table, ctx, monkeypatch):
    monkeypatch.setenv("FORCE_FAIL", "true")
    with pytest.raises(InjectedFault):
        h.handler({"tx": TX, "tarifa": TARIFA}, ctx)
