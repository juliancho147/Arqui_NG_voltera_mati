import json
import os

import boto3
from moto import mock_aws

os.environ.update(AWS_ACCESS_KEY_ID="testing", AWS_SECRET_ACCESS_KEY="testing", AWS_DEFAULT_REGION="us-east-1")

import seed_transacciones as seed  # noqa: E402


def test_generar_determinista_y_unico():
    a = seed.generar("C1", 10)
    assert a == seed.generar("C1", 10) and len({i["facturaId"] for i in a}) == 10
    assert a[0]["facturaId"] == "C1-F0001" and all(i["cicloId"] == "C1" for i in a)


def test_rechazos_forzados():
    items = seed.generar("C1", 6, rechazos_tarifa=1, rechazos_calculo=2)
    assert items[-1]["tipoTarifa"] == "INEXISTENTE"
    assert all(i["excedentesKwh"] > i["consumoKwh"] for i in items[-3:-1])
    assert all(i["excedentesKwh"] <= i["consumoKwh"] for i in items[:-3])


def test_dry_run_no_escribe(capsys, monkeypatch):
    monkeypatch.setattr(seed, "escribir", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no debe escribir")))
    assert seed.main(["--ciclo-id", "C1", "--n", "3", "--dry-run"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 3 and json.loads(lines[0])["cicloId"] == "C1"


def test_escribe_en_dynamodb_con_endpoint(monkeypatch):
    with mock_aws():
        boto3.client("dynamodb").create_table(
            TableName="tx", BillingMode="PAY_PER_REQUEST",
            KeySchema=[{"AttributeName": "cicloId", "KeyType": "HASH"}, {"AttributeName": "facturaId", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "cicloId", "AttributeType": "S"}, {"AttributeName": "facturaId", "AttributeType": "S"}])
        assert seed.main(["--ciclo-id", "C9", "--n", "4", "--table", "tx"]) == 0
        assert boto3.resource("dynamodb").Table("tx").scan()["Count"] == 4
        assert seed.main(["--ciclo-id", "C9", "--n", "4", "--table", "tx"]) == 0  # re-ejecutable
        assert boto3.resource("dynamodb").Table("tx").scan()["Count"] == 4
