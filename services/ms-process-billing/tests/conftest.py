import os

import pytest

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_REGION", "us-east-1")
# Credenciales falsas SOLO para moto (nunca se llama a AWS real).
os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
os.environ["AWS_SESSION_TOKEN"] = "testing"
os.environ.pop("AWS_PROFILE", None)
os.environ["POWERTOOLS_TRACE_DISABLED"] = "1"
os.environ["POWERTOOLS_METRICS_NAMESPACE"] = "Voltera/Exp2"
os.environ["POWERTOOLS_LOG_LEVEL"] = "WARNING"
os.environ["MESH_BACKEND"] = "memory"
os.environ.pop("KAFKA_BOOTSTRAP_SERVERS", None)


@pytest.fixture(autouse=True)
def _no_faults(monkeypatch):
    monkeypatch.setenv("FAIL_RATE", "0")
    monkeypatch.setenv("FORCE_FAIL", "false")


class Ctx:
    function_name = "test"
    memory_limit_in_mb = 256
    invoked_function_arn = "arn:aws:lambda:us-east-1:123456789012:function:test"
    aws_request_id = "req-1"

    def get_remaining_time_in_millis(self):
        return 30000


@pytest.fixture
def ctx():
    return Ctx()


import json  # noqa: E402

import boto3  # noqa: E402
from moto import mock_aws  # noqa: E402

from config import Settings  # noqa: E402
from voltera_common import DomainEventPublisher, InMemoryBackend, make_event  # noqa: E402


@pytest.fixture
def aws():
    with mock_aws():
        ddb = boto3.resource("dynamodb")
        table = ddb.create_table(
            TableName="pb", BillingMode="PAY_PER_REQUEST",
            KeySchema=[{"AttributeName": "cicloId", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "cicloId", "AttributeType": "S"}, {"AttributeName": "sk", "AttributeType": "S"}],
        )
        sqs = boto3.client("sqs")
        url = sqs.create_queue(QueueName="tx")["QueueUrl"]
        yield table, sqs, url


@pytest.fixture
def settings(aws):
    return Settings(table="pb", sqs_queue_url=aws[2], simulated_delay_seconds=0, ciclo_timeout_seconds=60)


@pytest.fixture
def backend():
    return InMemoryBackend()


@pytest.fixture
def publisher(backend):
    return DomainEventPublisher("ms-process-billing", backend, best_effort=False)


def consumo(fid, ciclo="C1", **extra):
    return make_event("ConsumoFacturablePreparado", "ms-orchestrator-billing", ciclo, fid, ordinal=1, totalUnidades=2,
                      clienteId="CL1", tipoTarifa="RESIDENCIAL", periodo="2026-09", **extra).to_bytes()


def sqs_bodies(sqs, url):
    out = []
    while True:
        r = sqs.receive_message(QueueUrl=url, MaxNumberOfMessages=10, VisibilityTimeout=0)
        if not r.get("Messages"):
            return out
        for m in r["Messages"]:
            out.append(json.loads(m["Body"]))
            sqs.delete_message(QueueUrl=url, ReceiptHandle=m["ReceiptHandle"])
