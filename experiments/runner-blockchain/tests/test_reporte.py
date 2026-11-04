"""Pruebas del Reporte_Resultados a nivel de corrida (`reporte.py`, R7.1-R7.5, R3.4).

Construyen `ExperimentResult`s sinteticos (sin tocar la cadena) y verifican que el reporte
de corrida: agrega el veredicto por experimento y el de la corrida (R7.1, R7.4), arma la
cabecera con runId/inicio/fin/cantidades/repeticiones/contratos/herramientas (R7.2),
consolida la evidencia on-chain con txHash/blockNumber/gas y expone la frontera
on/off-chain (R7.3), marca las metricas incumplidas con valor y umbral en los FAIL (R7.5) y
nunca deja aparecer credenciales de Pinata ni la llave de la plataforma (R3.4). Tambien que
escribe `report.json` y `report.md` por corrida (R7.1) y que el veredicto es reproducible.
"""
from __future__ import annotations

import json
from pathlib import Path

from runner_blockchain.reporte import (
    CLAVES_SENSIBLES,
    construir_reporte,
    escribir_reporte,
    reporte_desde_deployment,
    sanear,
    to_markdown,
)
from runner_blockchain.reporte_modelo import ExperimentResult


def _e1_pass() -> ExperimentResult:
    e = ExperimentResult(
        "E1",
        "E1 — Integridad del Oracle",
        "hip E1",
        started="2024-01-01T00:00:00+0000",
        finished="2024-01-01T00:01:00+0000",
    )
    e.params.update(
        {
            "runId": "run-1",
            "invalidas": 200,
            "validas": 200,
            "porCategoria": {"valor_alterado": 70, "medidor_desconocido": 65, "lectura_duplicada": 65},
            "metricas": {"tasaRechazo": 1.0, "latenciaP95Segundos": 2.5},
        }
    )
    e.add("R2.5", "tasa de rechazo", ok=True, expected="100%", observed="100%")
    e.add("R2.8", "p95", ok=True, expected="p95<=10 s", observed="p95=2.5 s")
    e.data["eventos"] = [
        {
            "tipo": "Emitido",
            "contrato": "EnergyToken",
            "transactionHash": "0xaaa",
            "blockNumber": 5,
            "gasUsed": 21000,
            "logIndex": 0,
            "args": {"id": 1, "kwh": 10},
        }
    ]
    return e


def _e2_fail() -> ExperimentResult:
    e = ExperimentResult(
        "E2",
        "E2 — Integridad del certificado off-chain",
        "hip E2",
        started="2024-01-01T00:02:00+0000",
        finished="2024-01-01T00:03:00+0000",
    )
    e.params.update(
        {
            "totalAlterados": 50,
            "conteoPorForma": {"byte": 20, "metadatos": 15, "reemplazo": 15},
            "metricas": {"p95VerificacionSegundos": 4.2, "falsosPositivos": 0},
        }
    )
    e.add("R3.6", "deteccion", ok=True, expected="100%", observed="100%")
    e.add("R3.10", "p95 verificacion", ok=False, expected="p95 <= 3 s", observed="p95 = 4.2 s")
    return e


def _e3_pass() -> ExperimentResult:
    e = ExperimentResult(
        "E3",
        "E3 — Tokenizacion sin doble venta",
        "hip E3",
        started="2024-01-01T00:04:00+0000",
        finished="2024-01-01T00:05:00+0000",
    )
    e.params.update({"repeticiones": 10, "comprasPorOferta": 100})
    e.add("R4.4", "una venta por oferta", ok=True, expected="1 por oferta", observed="10/10")
    e.data["evidencia"] = [
        {
            "tipo": "Compra",
            "contrato": "MarketEscrow",
            "transactionHash": "0xbbb",
            "blockNumber": 9,
            "gasUsed": 50000,
            "logIndex": 1,
            "args": {"ofertaId": 1},
        }
    ]
    return e


# --- R7.1 / R7.4: veredictos por experimento y de la corrida -----------------
def test_verdict_corrida_pass_si_todos_pass() -> None:
    r = construir_reporte("run-1", [_e1_pass(), _e3_pass()])
    assert r.verdict == "PASS"


def test_verdict_corrida_fail_si_algun_experimento_fail() -> None:
    r = construir_reporte("run-1", [_e1_pass(), _e2_fail(), _e3_pass()])
    assert r.verdict == "FAIL"


def test_verdict_corrida_fail_sin_experimentos() -> None:
    assert construir_reporte("run-1", []).verdict == "FAIL"


# --- R7.2: cabecera de corrida ----------------------------------------------
def test_cabecera_incluye_parametros_de_corrida() -> None:
    r = construir_reporte(
        "run-1",
        [_e1_pass(), _e2_fail(), _e3_pass()],
        contratos={"EnergyToken": "0x1", "MarketEscrow": "0x2"},
        herramientas={"foundry": "1.9.0"},
    )
    h = r.to_dict()["header"]
    assert h["runId"] == "run-1"
    assert h["inicio"] == "2024-01-01T00:00:00+0000"  # primer inicio
    assert h["fin"] == "2024-01-01T00:05:00+0000"  # ultimo fin
    assert h["contratos"] == {"EnergyToken": "0x1", "MarketEscrow": "0x2"}
    assert h["herramientas"] == {"foundry": "1.9.0"}
    assert h["cantidades"]["E1"]["invalidas"] == 200
    assert h["cantidades"]["E1"]["validas"] == 200
    assert h["cantidades"]["E2"]["totalAlterados"] == 50
    assert h["repeticiones"]["E3"] == 10


def test_reporte_desde_deployment_toma_contratos_y_herramientas() -> None:
    class _Dep:
        contratos = {"EnergyToken": "0xAA", "MarketEscrow": "0xBB"}
        herramientas = {"foundry": "1.9.0", "anvil": "1.9.0"}
        chain_id = 11155111
        rpc_url = "http://localhost:8545"

    r = reporte_desde_deployment("run-1", [_e1_pass()], _Dep())
    h = r.to_dict()["header"]
    assert h["contratos"]["EnergyToken"] == "0xAA"
    assert h["herramientas"]["anvil"] == "1.9.0"
    assert h["params"]["chainId"] == 11155111
    assert h["params"]["rpcUrl"] == "http://localhost:8545"


# --- R7.3: evidencia on-chain y frontera ------------------------------------
def test_evidencia_on_chain_con_txhash_block_y_gas() -> None:
    r = construir_reporte("run-1", [_e1_pass(), _e3_pass()])
    ev = r.evidencia_on_chain()
    por_tipo = {e["tipo"]: e for e in ev}
    assert por_tipo["Emitido"]["transactionHash"] == "0xaaa"
    assert por_tipo["Emitido"]["blockNumber"] == 5
    assert por_tipo["Emitido"]["gasUsed"] == 21000
    assert por_tipo["Compra"]["transactionHash"] == "0xbbb"
    assert por_tipo["Compra"]["gasUsed"] == 50000


def test_evidencia_deduplica_eventos_repetidos() -> None:
    e = _e1_pass()
    # El mismo evento aparece en ambas vistas: debe contarse una sola vez.
    e.data["evidencia"] = list(e.data["eventos"])
    r = construir_reporte("run-1", [e])
    assert len(r.evidencia_on_chain()) == 1


def test_frontera_on_off_chain_presente() -> None:
    doc = construir_reporte("run-1", [_e1_pass()]).to_dict()
    assert "onChain" in doc["fronteraOnOffChain"]
    assert "offChain" in doc["fronteraOnOffChain"]


# --- R7.5: metricas incumplidas en los FAIL ---------------------------------
def test_fail_marca_metrica_incumplida_con_valor_y_umbral() -> None:
    r = construir_reporte("run-1", [_e1_pass(), _e2_fail()])
    inc = r.metricas_incumplidas()
    assert "E1" not in inc  # E1 es PASS
    e2 = inc["E2"]
    assert len(e2) == 1
    assert e2[0]["id"] == "R3.10"
    assert e2[0]["observado"] == "p95 = 4.2 s"
    assert e2[0]["umbral"] == "p95 <= 3 s"


def test_fail_por_error_de_ejecucion_se_registra() -> None:
    e = ExperimentResult("E1", "E1", "h")
    e.error = "indisponibilidad de la cadena"
    r = construir_reporte("run-1", [e])
    inc = r.metricas_incumplidas()["E1"]
    assert any(it["id"] == "error" for it in inc)


# --- R3.4: credenciales de Pinata / llave de plataforma nunca aparecen -------
def test_sanear_elimina_claves_sensibles_anidadas() -> None:
    bruto = {
        "ok": 1,
        "PINATA_JWT": "secreto",
        "nested": {"privateKey": "0xdead", "keep": "visible"},
        "lista": [{"apiSecret": "x"}, {"mantener": "si"}],
    }
    limpio = sanear(bruto)
    texto = json.dumps(limpio)
    assert "secreto" not in texto
    assert "0xdead" not in texto
    assert limpio["nested"]["keep"] == "visible"
    assert limpio["lista"][1]["mantener"] == "si"


def test_reporte_json_no_contiene_credenciales() -> None:
    e = _e1_pass()
    e.params["PINATA_JWT"] = "jwt-super-secreto"
    e.data["PLATAFORMA_PRIVATE_KEY"] = "0xllavesecreta"
    r = construir_reporte("run-1", [e])
    texto = json.dumps(r.to_dict())
    assert "jwt-super-secreto" not in texto
    assert "0xllavesecreta" not in texto
    # Las claves sensibles conocidas estan todas contempladas.
    assert "pinata_jwt" in CLAVES_SENSIBLES


# --- R7.1: escritura de report.json + report.md -----------------------------
def test_escribir_reporte_crea_json_y_md(tmp_path: Path) -> None:
    r = construir_reporte(
        "run-1",
        [_e1_pass(), _e2_fail(), _e3_pass()],
        contratos={"EnergyToken": "0x1", "MarketEscrow": "0x2"},
        herramientas={"foundry": "1.9.0", "anvil": "1.9.0"},
    )
    out = escribir_reporte(r, tmp_path, stamp="20240101-000000")
    assert out == tmp_path / "20240101-000000-run-1"
    doc = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert doc["verdict"] == "FAIL"
    assert doc["runId"] == "run-1"
    md = (out / "report.md").read_text(encoding="utf-8")
    assert "Reporte de corrida" in md
    assert "Frontera on-chain / off-chain" in md
    assert "Evidencia on-chain" in md
    assert "0xaaa" in md  # txHash del evento Emitido


# --- R7.4: reproducibilidad del veredicto ------------------------------------
def test_veredicto_reproducible_con_mismos_resultados() -> None:
    v1 = construir_reporte("run-1", [_e1_pass(), _e2_fail(), _e3_pass()]).verdict
    v2 = construir_reporte("run-1", [_e1_pass(), _e2_fail(), _e3_pass()]).verdict
    assert v1 == v2 == "FAIL"


def test_markdown_renderiza_sin_error() -> None:
    md = to_markdown(construir_reporte("run-1", [_e1_pass(), _e3_pass()]))
    assert md.startswith("# Reporte de corrida")
