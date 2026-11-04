"""Pruebas del ciclo de vida de los microservicios (`servicios.py`, R5, R7.6).

Validan la orquestacion del conjunto (arranque, readiness por `/healthz`, teardown, orden)
sin levantar procesos ni abrir puertos reales: se inyectan las funciones de arranque,
readiness y parada. Tambien aseveran que `construir_specs` cablea puertos consistentes y las
URLs entre servicios (ms_oraculo -> ms_energia) que exige la tarea 13.1.
"""
from __future__ import annotations

import pytest

from runner_blockchain import servicios
from runner_blockchain.servicios import (
    EspecServicio,
    Microservicios,
    ServicioEnEjecucion,
    ServicioError,
    construir_specs,
)


class _ProcesoFalso:
    """Doble minimo de `subprocess.Popen`: vivo hasta que se detiene (o se marca muerto)."""

    def __init__(self, muerto: bool = False, returncode: int = 0):
        self._muerto = muerto
        self.returncode = returncode
        self.terminado = False
        self.matado = False
        self.pid = 1234
        self.stdout = None

    def poll(self):
        return self.returncode if self._muerto else None

    def terminate(self):
        self.terminado = True
        self._muerto = True

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.matado = True
        self._muerto = True


def _specs(n=3):
    return [EspecServicio(f"ms_{i}", directorio=object(), puerto=9000 + i) for i in range(n)]  # type: ignore[arg-type]


def test_construir_specs_puertos_y_urls_entre_servicios():
    specs = construir_specs(deployment_path=None, rpc_url="http://localhost:8545")
    por_nombre = {s.nombre: s for s in specs}
    # Puertos fijados por la tarea 13.1 (ms_energia 8081 para no chocar con ms_oraculo 8080).
    assert por_nombre["ms_oraculo"].puerto == servicios.PUERTO_ORACULO == 8080
    assert por_nombre["ms_energia"].puerto == servicios.PUERTO_ENERGIA == 8081
    assert por_nombre["ms_venta"].puerto == 8083
    assert por_nombre["ms_compra"].puerto == 8084
    assert por_nombre["ms_certificado"].puerto == 8085
    # ms_oraculo publica GeneracionValidada a ms_energia por MS_ENERGIA_URL.
    assert por_nombre["ms_oraculo"].env["MS_ENERGIA_URL"].endswith(":8081")
    # ms_energia arranca antes que ms_oraculo (dependencia de publicacion).
    assert [s.nombre for s in specs].index("ms_energia") < [s.nombre for s in specs].index("ms_oraculo")
    # El RPC y el deployment se propagan a los servicios que tocan la cadena.
    assert por_nombre["ms_venta"].env["RPC_URL"] == "http://localhost:8545"


def test_construir_specs_incluye_pinata_jwt_solo_si_se_provee():
    con = {s.nombre: s for s in construir_specs(pinata_jwt="jwt-secreto")}
    sin = {s.nombre: s for s in construir_specs(pinata_jwt=None)}
    assert con["ms_certificado"].env["PINATA_JWT"] == "jwt-secreto"
    assert "PINATA_JWT" not in sin["ms_certificado"].env


def test_iniciar_arranca_todos_y_espera_readiness_en_orden():
    arrancados: list[str] = []
    esperados: list[str] = []

    def arrancar(spec):
        arrancados.append(spec.nombre)
        return _ProcesoFalso()

    def esperar(spec, *, proceso=None, timeout_s=30):
        esperados.append(spec.nombre)

    m = Microservicios(_specs(3), arrancar=arrancar, esperar=esperar, detener=lambda e: None)
    ejecuciones = m.iniciar()
    nombres = [s.nombre for s in _specs(3)]
    assert arrancados == nombres
    assert esperados == nombres
    assert [e.spec.nombre for e in ejecuciones] == nombres


def test_iniciar_detiene_lo_levantado_si_falla_la_readiness():
    detenidos: list[str] = []

    def esperar(spec, *, proceso=None, timeout_s=30):
        if spec.nombre == "ms_1":
            raise ServicioError("no respondio /healthz")

    def detener(ejecucion):
        detenidos.append(ejecucion.spec.nombre)

    m = Microservicios(_specs(3), arrancar=lambda s: _ProcesoFalso(), esperar=esperar, detener=detener)
    with pytest.raises(ServicioError):
        m.iniciar()
    # Se detienen los dos levantados (ms_0, ms_1) en orden inverso; ms_2 nunca arranco.
    assert detenidos == ["ms_1", "ms_0"]
    assert m.en_ejecucion == []


def test_detener_es_idempotente_y_en_orden_inverso():
    orden: list[str] = []
    m = Microservicios(_specs(2), arrancar=lambda s: _ProcesoFalso(),
                       esperar=lambda *a, **k: None,
                       detener=lambda e: orden.append(e.spec.nombre))
    m.iniciar()
    m.detener()
    m.detener()  # idempotente: no vuelve a detener nada
    assert orden == ["ms_1", "ms_0"]


def test_esperar_readiness_aborta_si_el_proceso_muere():
    spec = EspecServicio("ms_x", directorio=object(), puerto=9999)  # type: ignore[arg-type]
    proceso = _ProcesoFalso(muerto=True, returncode=1)
    with pytest.raises(ServicioError, match="termino antes de responder"):
        servicios.esperar_readiness(spec, proceso=proceso, timeout_s=1, intervalo_s=0.01,
                                    sonda=lambda url: False)


def test_esperar_readiness_ok_cuando_la_sonda_responde():
    spec = EspecServicio("ms_x", directorio=object(), puerto=9999)  # type: ignore[arg-type]
    llamadas = {"n": 0}

    def sonda(url):
        llamadas["n"] += 1
        return llamadas["n"] >= 2  # lista en el segundo intento

    servicios.esperar_readiness(spec, proceso=_ProcesoFalso(), timeout_s=2, intervalo_s=0.01, sonda=sonda)
    assert llamadas["n"] >= 2
