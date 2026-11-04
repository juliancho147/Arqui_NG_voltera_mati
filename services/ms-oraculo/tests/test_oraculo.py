"""Pruebas unitarias de la validacion real y determinista de ms_oraculo (R2.2, R2.3, R2.4, R5.1)."""
from __future__ import annotations

import pytest

from config import Settings
from oraculo import (
    LECTURA_DUPLICADA,
    MEDIDOR_DESCONOCIDO,
    VALOR_ALTERADO,
    Lectura,
    LecturaInvalidaError,
    RegistroDuplicados,
    evaluar,
)
from stubs import ClimaStub, MedidorStub, referencia_esperada

TOL = Settings.tolerancia_relativa


def _lectura(**over):
    base = {
        "lecturaId": "L-1",
        "medidorId": "MED-001",
        "epoca": 202606,  # junio: factor solar 1.2 -> referencia 100*1.2 = 120
        "fuente": "solar",
        "kwh": 120,
        "precio": 5,
        "participante": "0xabc",
    }
    base.update(over)
    return Lectura.from_payload(base)


def _evaluar(lectura, **kw):
    return evaluar(lectura, MedidorStub(), ClimaStub(), tolerancia_relativa=TOL, **kw)


def test_lectura_valida_consistente_con_referencia_se_acepta():
    lectura = _lectura(kwh=120)  # == referencia exacta
    v = _evaluar(lectura)
    assert v.aceptada is True
    assert v.categoria is None


def test_valor_dentro_de_tolerancia_se_acepta():
    # referencia 120, tolerancia 10% -> [108, 132]
    assert _evaluar(_lectura(kwh=130)).aceptada is True
    assert _evaluar(_lectura(kwh=110)).aceptada is True


def test_valor_alterado_fuera_de_tolerancia_se_rechaza():
    v = _evaluar(_lectura(kwh=200))  # muy por encima de 120 +/-10%
    assert v.aceptada is False
    assert v.categoria == VALOR_ALTERADO


def test_valor_negativo_es_valor_alterado():
    v = _evaluar(_lectura(kwh=-5))
    assert v.aceptada is False
    assert v.categoria == VALOR_ALTERADO


def test_fuente_no_esperada_para_el_medidor_es_valor_alterado():
    # MED-001 solo tiene solar/eolica; hidro no tiene referencia.
    v = _evaluar(_lectura(fuente="hidro", kwh=10))
    assert v.aceptada is False
    assert v.categoria == VALOR_ALTERADO


def test_medidor_desconocido_se_rechaza():
    v = _evaluar(_lectura(medidorId="MED-999"))
    assert v.aceptada is False
    assert v.categoria == MEDIDOR_DESCONOCIDO


def test_lectura_duplicada_por_lectura_id():
    lectura = _lectura()
    v = _evaluar(lectura, vistas_lectura={"L-1"})
    assert v.aceptada is False
    assert v.categoria == LECTURA_DUPLICADA


def test_lectura_duplicada_por_tupla_medidor_epoca():
    lectura = _lectura(lecturaId="L-2")  # distinto id, misma (MED-001, 202606)
    v = _evaluar(lectura, vistas_epoca={("MED-001", 202606)})
    assert v.aceptada is False
    assert v.categoria == LECTURA_DUPLICADA


def test_determinismo_misma_entrada_mismo_veredicto():
    # R2.2: dos evaluaciones de la misma lectura producen el mismo veredicto y categoria.
    for kwh in (120, 200, -1):
        lectura = _lectura(kwh=kwh)
        v1 = _evaluar(lectura)
        v2 = _evaluar(lectura)
        assert (v1.aceptada, v1.categoria) == (v2.aceptada, v2.categoria)


def test_orden_de_evaluacion_prioriza_causa_intrinseca_sobre_duplicado():
    # Un medidor desconocido ademas duplicado se rechaza por 'medidor_desconocido'.
    lectura = _lectura(medidorId="MED-999")
    v = _evaluar(lectura, vistas_lectura={"L-1"})
    assert v.categoria == MEDIDOR_DESCONOCIDO


def test_registro_duplicados_marca_lectura_y_epoca():
    reg = RegistroDuplicados()
    reg.registrar(_lectura())
    assert "L-1" in reg.lecturas
    assert ("MED-001", 202606) in reg.epocas


@pytest.mark.parametrize("payload", [
    {},
    {"lecturaId": "L-1"},
    {"lecturaId": "L-1", "medidorId": "MED-001", "epoca": "x", "fuente": "solar",
     "kwh": 1, "precio": 1, "participante": "0x"},
])
def test_contrato_invalido_lanza_error(payload):
    with pytest.raises(LecturaInvalidaError):
        Lectura.from_payload(payload)


def test_referencia_esperada_ajusta_por_estacion():
    med, cli = MedidorStub(), ClimaStub()
    # solar base 100; junio factor 1.2 -> 120; diciembre factor 0.6 -> 60.
    assert referencia_esperada(med, cli, "MED-001", "solar", 202606) == 120
    assert referencia_esperada(med, cli, "MED-001", "solar", 202612) == 60
    assert referencia_esperada(med, cli, "MED-001", "hidro", 202606) is None
