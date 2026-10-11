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
