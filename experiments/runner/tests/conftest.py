import json
import sys
import zipfile
from io import BytesIO
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runner.config import SERVICES, Config  # noqa: E402
from runner.context import Context  # noqa: E402

from .world import World  # noqa: E402

REGION = "us-east-1"
PREFIX = "voltera-exp2"


def _zip() -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("handler.py", "def handler(e, c):\n    return {}\n")
    return buf.getvalue()


@pytest.fixture
def aws(monkeypatch):
    for k, v in {"AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test", "AWS_SESSION_TOKEN": "test",
                 "AWS_DEFAULT_REGION": REGION}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    with mock_aws():
        s = boto3.Session(region_name=REGION)
        ddb, sqs, lam, ev = s.client("dynamodb"), s.client("sqs"), s.client("lambda"), s.client("events")
        cfg = Config.defaults(PREFIX, REGION)
        cfg.placeholder = False
        keys = {"transacciones": ("cicloId", "facturaId"), "outbox": ("eventId", None), "process-billing": ("cicloId", "sk"),
                "idem-facturacion": ("facturaId", None), "idem-comprobante": ("facturaId", None)}
        for k, (h, r) in keys.items():
            schema = [{"AttributeName": h, "KeyType": "HASH"}] + ([{"AttributeName": r, "KeyType": "RANGE"}] if r else [])
            attrs = [{"AttributeName": n, "AttributeType": "S"} for n in (h, r) if n]
            ddb.create_table(TableName=cfg.tables[k], KeySchema=schema, AttributeDefinitions=attrs, BillingMode="PAY_PER_REQUEST")
        for k in ("transacciones", "comprobantes"):
            dlq = sqs.create_queue(QueueName=f"{PREFIX}-{k}-dlq")["QueueUrl"]
            dlq_arn = sqs.get_queue_attributes(QueueUrl=dlq, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
            url = sqs.create_queue(QueueName=f"{PREFIX}-{k}", Attributes={
                "VisibilityTimeout": "30", "RedrivePolicy": json.dumps({"deadLetterTargetArn": dlq_arn, "maxReceiveCount": "3"})})["QueueUrl"]
            arn = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
            cfg.queues[k] = {"url": url, "arn": arn, "dlq_url": dlq, "dlq_arn": dlq_arn}
        ev.create_event_bus(Name=cfg.bus_name)
        trust = json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"},
                                                                    "Action": "sts:AssumeRole"}]})
        role = s.client("iam").create_role(RoleName="r", AssumeRolePolicyDocument=trust)["Role"]["Arn"]
        for svc in SERVICES:
            lam.create_function(FunctionName=f"{PREFIX}-{svc}", Runtime="python3.12", Role=role,
                                Handler="handler.handler", Code={"ZipFile": _zip()},
                                Environment={"Variables": {"FORCE_FAIL": "false", "FAIL_RATE": "0", "OTRA": "x"}})
        yield s, cfg


@pytest.fixture
def make(aws, tmp_path):
    session, cfg = aws

    def factory(options=None, **world_kw):
        w = World(None, cfg, session, **world_kw)
        opts = {"poll": 5, "timeout": 600, "scaledown_timeout": 200, "timeout_recovery": 300, "fault_window": 40, "mirror_timeout": 30}
        opts.update(options or {})
        ctx = Context(cfg, yes=True, session=session, kube=w.kube, reports_dir=tmp_path / "reports", clock=w.clock, sleep=w.sleep, options=opts)
        return ctx, w
    return factory
