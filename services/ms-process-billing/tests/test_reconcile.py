import json

import boto3
import pytest

from state import CycleState
from voltera_common import make_event


def ev(name, fid, ciclo="C1", **data):
    return make_event(name, "x", ciclo, fid, **data).to_bytes()


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def idem(aws):
    ddb = boto3.resource("dynamodb")
    t = ddb.create_table(TableName="idem", BillingMode="PAY_PER_REQUEST",
                         KeySchema=[{"AttributeName": "facturaId", "KeyType": "HASH"}],
                         AttributeDefinitions=[{"AttributeName": "facturaId", "AttributeType": "S"}])
    return t


def notificada(idem, fid, status="COMPLETED", estado="NOTIFICADA"):
    idem.put_item(Item={"facturaId": f"fn#{fid}", "status": status, "data": json.dumps({"facturaId": fid, "estado": estado})})


def enviado(table, fid, ciclo="C1", estado="ENVIADO"):
    table.put_item(Item={"cicloId": ciclo, "sk": f"DEDUP#{fid}", "estado": estado})


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def st(aws, settings, publisher, idem, clock):
    settings.reconcile_after_seconds = 45
    return CycleState(settings, aws[0], publisher, clock=clock, recon_table=idem)


def arrancar(st, clock, aws, total=3, ok=("F1", "F2")):
    st.handle(ev("CicloDeFacturacionIniciado", "CICLO", totalUnidades=total))
    for f in ok:
        st.handle(ev("FacturaNotificada", f))
    for i in range(1, total + 1):
        enviado(aws[0], f"F{i}")


def test_reconcilia_factura_perdida_y_completa(aws, st, clock, idem, backend):
    arrancar(st, clock, aws)
    notificada(idem, "F3")
    assert st.sweep_timeouts() == []           # primera observacion: aun no esta estancado
    clock.t += 50
    st.sweep_timeouts()
    meta = aws[0].get_item(Key={"cicloId": "C1", "sk": "META"})["Item"]
    assert meta["estado"] == "COMPLETADO" and int(meta["emitidas"]) == 3
    assert backend.names() == ["ProcesoDeFacturacionCompletado"]
    assert aws[0].get_item(Key={"cicloId": "C1", "sk": "FACT#F3"})["Item"]["estado"] == "OK"


def test_idempotente_entre_replicas(aws, settings, publisher, idem, clock, backend):
    a = CycleState(settings, aws[0], publisher, clock=clock, recon_table=idem)
    b = CycleState(settings, aws[0], publisher, clock=clock, recon_table=idem)
    arrancar(a, clock, aws)
    b.known.add("C1")
    notificada(idem, "F3")
    for s in (a, b):
        s.sweep_timeouts()
    clock.t += 50
    assert a.reconcile("C1") == 1
    assert b.reconcile("C1") == 0   # otra replica ya la registro (o el ciclo ya no esta EN_CURSO)
    assert int(aws[0].get_item(Key={"cicloId": "C1", "sk": "META"})["Item"]["emitidas"]) == 3
    assert backend.names() == ["ProcesoDeFacturacionCompletado"]


def test_no_reconcilia_si_faltan_envios_a_sqs(aws, st, clock, idem):
    st.handle(ev("CicloDeFacturacionIniciado", "CICLO", totalUnidades=3))
    st.handle(ev("FacturaNotificada", "F1"))
    enviado(aws[0], "F1"); enviado(aws[0], "F2"); enviado(aws[0], "F3", estado="PROCESANDO")
    notificada(idem, "F2"); notificada(idem, "F3")
    st.sweep_timeouts(); clock.t += 50
    assert st.reconcile("C1") == 0


def test_no_reconcilia_si_el_comprobante_no_lo_notifico(aws, st, clock, idem):
    arrancar(st, clock, aws)
    notificada(idem, "F3", status="INPROGRESS")
    st.sweep_timeouts(); clock.t += 50
    assert st.reconcile("C1") == 0
    assert int(aws[0].get_item(Key={"cicloId": "C1", "sk": "META"})["Item"]["emitidas"]) == 2


def test_no_reconcilia_antes_del_umbral_ni_con_progreso(aws, st, clock, idem):
    arrancar(st, clock, aws)
    notificada(idem, "F3")
    st.sweep_timeouts(); clock.t += 30
    assert st.reconcile("C1") == 0


def test_sin_tabla_de_reconciliacion_no_hace_nada(aws, settings, publisher, clock):
    st = CycleState(settings, aws[0], publisher, clock=clock)
    arrancar(st, clock, aws)
    clock.t += 50
    assert st.reconcile("C1") == 0


def test_metricas(aws, settings, publisher, idem, clock):
    class M:
        def __init__(self): self.c = {}
        def add(self, n, v=1, u="Count", dims=None): self.c[n] = self.c.get(n, 0) + v
    m = M()
    st = CycleState(settings, aws[0], publisher, clock=clock, recon_table=idem, metrics=m)
    arrancar(st, clock, aws); notificada(idem, "F3")
    st.sweep_timeouts(); clock.t += 50; st.sweep_timeouts()
    assert m.c["FacturasReconciliadas"] == 1 and m.c["CiclosReconciliados"] == 1 and m.c["CiclosCompletados"] == 1
