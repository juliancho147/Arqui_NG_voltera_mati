from voltera_common import DomainEventPublisher, InMemoryBackend, make_event
from voltera_common.publisher import PublishError


class Flaky(InMemoryBackend):
    def __init__(self, fallos: int):
        super().__init__()
        self.restantes = fallos

    def flush(self, timeout: float = 5.0) -> None:
        if self.restantes > 0:
            self.restantes -= 1
            raise PublishError("flush transitorio")


def _ev():
    return make_event("FacturaNotificada", "ms-comprobante-factura", "C1", "F1")


def test_reintenta_y_publica_tras_fallo_transitorio():
    b = Flaky(2)
    pub = DomainEventPublisher("t", b, attempts=3, retry_delay=0)
    assert pub.publish_event(_ev()) is True
    assert pub.failures == 0
    assert len(b.messages) == 3  # 2 intentos fallidos + 1 bueno; el mismo eventId (consumidor idempotente)


def test_agota_intentos_y_cuenta_el_fallo_en_best_effort():
    b = Flaky(5)
    pub = DomainEventPublisher("t", b, attempts=3, retry_delay=0)
    assert pub.publish_event(_ev()) is False
    assert pub.failures == 1


def test_fallo_inyectado_emite_senal(monkeypatch, capsys):
    from voltera_common import maybe_fail
    from voltera_common.faults import InjectedFault
    import pytest
    monkeypatch.setenv("FORCE_FAIL", "true")
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "voltera-exp2-ms-tarifas")
    with pytest.raises(InjectedFault):
        maybe_fail(label="x")
    assert "FallaInyectada" in capsys.readouterr().out
