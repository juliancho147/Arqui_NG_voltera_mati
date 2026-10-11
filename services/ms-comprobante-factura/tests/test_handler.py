import json

import boto3
import pytest
from moto import mock_aws

import handler as h


def sqs_event(*facturas, receive=1):
    return {"Records": [{
        "messageId": f"m-{f}", "receiptHandle": "rh", "body": json.dumps({"evento": "FacturaEmitida", "cicloId": "C1", "facturaId": f}),
        "attributes": {"ApproximateReceiveCount": str(receive), "SentTimestamp": "1", "SenderId": "x", "ApproximateFirstReceiveTimestamp": "1"},
        "messageAttributes": {}, "md5OfBody": "", "eventSource": "aws:sqs", "eventSourceARN": "arn:aws:sqs:us-east-1:1:q", "awsRegion": "us-east-1",
    } for f in facturas]}


@pytest.fixture
def env(monkeypatch):
    with mock_aws():
        monkeypatch.setenv("TABLE_IDEMPOTENCIA", "idem")
        monkeypatch.setenv("IDEMPOTENCY_TTL_ATTR", "expiresAt")
        boto3.client("dynamodb").create_table(
            TableName="idem", KeySchema=[{"AttributeName": "facturaId", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "facturaId", "AttributeType": "S"}], BillingMode="PAY_PER_REQUEST")
        h._store = h._publisher = None
        yield
        h._store = h._publisher = None


def test_exito_publica_eventos(env, ctx):
    r = h.handler(sqs_event("F1"), ctx)
    assert r == {"batchItemFailures": []}
    assert h.get_publisher().backend.names() == ["NotificacionRegistrada", "FacturaNotificada"]


def test_idempotente_entrega_repetida(env, ctx):
    h.handler(sqs_event("F1"), ctx)
    h.handler(sqs_event("F1"), ctx)
    assert h.get_publisher().backend.names() == ["NotificacionRegistrada", "FacturaNotificada"]


def test_fallo_parcial_de_lote(env, ctx, monkeypatch):
    calls = {"n": 0}
    real = h.enviar_al_tercero

    def flaky(payload, intento):
        if payload["facturaId"] == "F2":
            monkeypatch.setenv("FORCE_FAIL", "true")
        else:
            monkeypatch.setenv("FORCE_FAIL", "false")
        return real(payload, intento)

    monkeypatch.setattr(h, "enviar_al_tercero", flaky)
    r = h.handler(sqs_event("F1", "F2", "F3"), ctx)
    assert r == {"batchItemFailures": [{"itemIdentifier": "m-F2"}]}
    names = h.get_publisher().backend.names()
    assert names.count("FacturaNotificada") == 2 and names.count("NotificacionFallida") == 1


def test_reintento_tras_fallo_y_definitivo(env, ctx, monkeypatch):
    monkeypatch.setenv("FORCE_FAIL", "true")
    assert h.handler(sqs_event("F1", receive=1), ctx)["batchItemFailures"]
    assert h.handler(sqs_event("F1", receive=3), ctx)["batchItemFailures"]
    fallos = [e for e in h.get_publisher().backend.events() if e.name == "NotificacionFallida"]
    assert [f.data["definitivo"] for f in fallos] == [False, True]
    monkeypatch.setenv("FORCE_FAIL", "false")  # el tercero se recupera: redrive de la DLQ
    assert h.handler(sqs_event("F1", receive=1), ctx) == {"batchItemFailures": []}
    assert h.get_publisher().backend.names()[-1] == "FacturaNotificada"


def test_replays_y_logs_estructurados(env, ctx, capsys):
    h.handler(sqs_event("F1"), ctx)
    out1 = capsys.readouterr().out
    assert "IdempotenciaReplays" not in out1 and "FacturasNotificadas" in out1
    h.handler(sqs_event("F1"), ctx)
    assert "IdempotenciaReplays" in capsys.readouterr().out
