import boto3
import pytest
from boto3.dynamodb.types import TypeSerializer
from moto import mock_aws

import handler as h
from voltera_common import InMemoryBackend, InjectedFault, PublishError, make_event

ser = TypeSerializer()


def record(destino, name="ConsumoFacturablePreparado", fid="C1-F1", event_name="INSERT"):
    ev = make_event(name, "ms-orchestrator-billing", "C1", fid, **({"totalUnidades": 1} if name == "CicloDeFacturacionIniciado" else {}))
    item = {"eventId": ev.id, "destino": destino, "key": fid, "headers": {"cicloId": "C1", "facturaId": fid},
            "payload": ev.to_json(), "estado": "PENDIENTE"}
    return {"eventName": event_name, "dynamodb": {"NewImage": {k: ser.serialize(v) for k, v in item.items()}}}, ev


@pytest.fixture
def be(monkeypatch):
    b = InMemoryBackend()
    h._backend = b
    monkeypatch.setenv("KAFKA_TOPIC", "voltera.consumo-facturable-preparado")
    monkeypatch.setenv("KAFKA_TOPIC_EVENTOS", "voltera.eventos")
    monkeypatch.delenv("TABLE_OUTBOX", raising=False)
    yield b
    h._backend = None


def test_publica_a_topicos_segun_destino(be, ctx):
    r1, e1 = record("INGRESO")
    r2, e2 = record("EVENTOS", "CicloDeFacturacionIniciado", "CICLO")
    assert h.handler({"Records": [r1, r2]}, ctx) == {"publicados": 2}
    m1, m2 = be.messages
    assert (m1.topic, m1.key) == ("voltera.consumo-facturable-preparado", "C1-F1")
    assert m1.headers == {"cicloId": "C1", "facturaId": "C1-F1"} and m1.event().id == e1.id
    assert (m2.topic, m2.key) == ("voltera.eventos", "CICLO")


def test_ignora_no_insert(be, ctx):
    r, _ = record("INGRESO", event_name="MODIFY")
    assert h.handler({"Records": [r]}, ctx) == {"publicados": 0} and not be.messages


def test_fallo_de_kafka_lanza_para_reintento(be, ctx):
    be.fail = True
    r, _ = record("INGRESO")
    with pytest.raises(PublishError):
        h.handler({"Records": [r]}, ctx)


def test_fallo_inyectado(be, ctx, monkeypatch):
    monkeypatch.setenv("FORCE_FAIL", "true")
    with pytest.raises(InjectedFault):
        h.handler({"Records": []}, ctx)


def test_marca_publicado(be, ctx, monkeypatch):
    with mock_aws():
        monkeypatch.setenv("TABLE_OUTBOX", "outbox")
        c = boto3.client("dynamodb")
        c.create_table(TableName="outbox", KeySchema=[{"AttributeName": "eventId", "KeyType": "HASH"}],
                       AttributeDefinitions=[{"AttributeName": "eventId", "AttributeType": "S"}], BillingMode="PAY_PER_REQUEST")
        r, ev = record("INGRESO")
        c.put_item(TableName="outbox", Item={"eventId": {"S": ev.id}, "estado": {"S": "PENDIENTE"}})
        h._ddb = None
        h.handler({"Records": [r]}, ctx)
        assert c.get_item(TableName="outbox", Key={"eventId": {"S": ev.id}})["Item"]["estado"]["S"] == "PUBLICADO"
        h._ddb = None
