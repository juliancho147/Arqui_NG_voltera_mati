"""Pruebas del cableado extremo a extremo de la corrida `all` (`cli.ejecutar_corrida`, R7.1/R7.6).

Validan que una corrida `all` conecta, en orden, el arranque del entorno, el levantamiento
de los microservicios (readiness por /healthz), la construccion del backend de E2, la
ejecucion de E1/E2/E3 y el teardown (servicios + Anvil en `finally`), sin requerir una
cadena viva ni procesos reales: todas las costuras se inyectan con dobles.
"""
from __future__ import annotations

from pathlib import Path

from runner_blockchain import cli
from runner_blockchain.cli import OpcionesCorrida, ejecutar_corrida
from runner_blockchain.reporte_modelo import ExperimentResult


class _ServiciosFalsos:
    """Doble del gestor de microservicios: registra iniciar()/detener()."""

    def __init__(self):
        self.iniciado = False
        self.detenido = False

    def iniciar(self):
        self.iniciado = True
        return []

    def detener(self):
        self.detenido = True


class _DeploymentFalso:
    """Deployment minimo con lo que usan reporte_desde_deployment y las fabricas."""

    chain_id = 11155111
    rpc_url = "http://localhost:8545"
    plataforma = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
    contratos = {
        "EnergyToken": "0x5FbDB2315678afecb367f032d93F642f64180aa3",
        "MarketEscrow": "0xe7f1725E7734CE288F8367e1Bb143E90bb3F0512",
    }
    herramientas = {"foundry": "1.9.0"}
    desplegado_en = "2026-01-01T00:00:00Z"
    ruta = Path("/tmp/deployment.json")


def _resultado(nombre: str) -> ExperimentResult:
    r = ExperimentResult(nombre.upper(), f"{nombre} titulo", "hip", started="s", finished="f")
    r.add("R", "ok", ok=True)
    return r


def _opciones(**kw):
    base = dict(seleccion="all", run_id="RUN-TEST", reports_dir=Path("/tmp/no-se-usa"))
    base.update(kw)
    return OpcionesCorrida(**base)


def _correr(opciones, *, orden, servicios, backend_calls, ejecutados):
    """Ejecuta `ejecutar_corrida` con todas las costuras inyectadas y registra el orden."""

    def preparar_entorno(*, deployment_path=None):
        orden.append("entorno")
        return (object(), object())  # (resultado, proceso_anvil)

    def detener_anvil(anvil):
        orden.append("detener_anvil")

    def cargar_deployment(path):
        return _DeploymentFalso()

    def construir_lector(dep):
        return object()

    def construir_servicios(dep, opts):
        orden.append("servicios")
        return servicios

    def construir_backend_e2(dep, opts):
        backend_calls.append(opts)
        return object()

    def ejecutor(nombre, run_id, lector):
        ejecutados.append(nombre)
        # Para E2, el backend debe estar ya cableado en las opciones.
        if nombre == "e2":
            assert opciones.backend_e2 is not None
        return _resultado(nombre)

    def escritor_reporte(reporte, reports_dir):
        orden.append("reporte")
        return Path("/tmp/report-dir")

    return ejecutar_corrida(
        opciones,
        preparar_entorno=preparar_entorno,
        detener_anvil=detener_anvil,
        cargar_deployment=cargar_deployment,
        construir_lector=construir_lector,
        construir_servicios=construir_servicios,
        construir_backend_e2=construir_backend_e2,
        ejecutor=ejecutor,
        escritor_reporte=escritor_reporte,
    )


def test_all_conecta_entorno_servicios_backend_experimentos_y_teardown():
    orden: list[str] = []
    servicios = _ServiciosFalsos()
    backend_calls: list = []
    ejecutados: list[str] = []
    opciones = _opciones()

    resultado = _correr(opciones, orden=orden, servicios=servicios,
                         backend_calls=backend_calls, ejecutados=ejecutados)

    # Se ejecutaron los tres experimentos en orden.
    assert ejecutados == ["e1", "e2", "e3"]
    # El backend de E2 se construyo y quedo cableado en las opciones.
    assert len(backend_calls) == 1
    assert opciones.backend_e2 is not None
    # Los servicios se iniciaron y se detuvieron (teardown en finally).
    assert servicios.iniciado and servicios.detenido
    # Orden del cableado: entorno -> servicios -> (experimentos) -> teardown (anvil) -> reporte.
    # El teardown ocurre en el `finally`; el reporte se escribe despues de liberar recursos.
    assert orden.index("entorno") < orden.index("servicios")
    assert orden.index("servicios") < orden.index("detener_anvil")
    assert orden.index("detener_anvil") < orden.index("reporte")
    # Veredicto de corrida derivado de los resultados.
    assert resultado.run_id == "RUN-TEST"
    assert resultado.verdict == "PASS"
    assert [r.experiment for r in resultado.experiments] == ["E1", "E2", "E3"]


def test_backend_e2_no_se_construye_si_ya_viene_en_opciones():
    orden: list[str] = []
    backend_calls: list = []
    ejecutados: list[str] = []
    backend_provisto = object()
    opciones = _opciones(seleccion="e2", backend_e2=backend_provisto)

    _correr(opciones, orden=orden, servicios=_ServiciosFalsos(),
            backend_calls=backend_calls, ejecutados=ejecutados)

    assert ejecutados == ["e2"]
    assert backend_calls == []  # no se reconstruye
    assert opciones.backend_e2 is backend_provisto


def test_no_se_levantan_servicios_con_gestionar_servicios_false():
    orden: list[str] = []
    servicios = _ServiciosFalsos()
    opciones = _opciones(seleccion="e1", gestionar_servicios=False)

    _correr(opciones, orden=orden, servicios=servicios,
            backend_calls=[], ejecutados=[])

    assert not servicios.iniciado and not servicios.detenido
    assert "servicios" not in orden


def test_servicios_se_detienen_aunque_falle_un_experimento():
    servicios = _ServiciosFalsos()
    opciones = _opciones(seleccion="all")
    orden: list[str] = []

    def preparar_entorno(*, deployment_path=None):
        return (object(), object())

    def ejecutor(nombre, run_id, lector):
        if nombre == "e2":
            raise RuntimeError("fallo del experimento")
        return _resultado(nombre)

    try:
        ejecutar_corrida(
            opciones,
            preparar_entorno=preparar_entorno,
            detener_anvil=lambda a: orden.append("detener_anvil"),
            cargar_deployment=lambda p: _DeploymentFalso(),
            construir_lector=lambda d: object(),
            construir_servicios=lambda d, o: servicios,
            construir_backend_e2=lambda d, o: object(),
            ejecutor=ejecutor,
            escritor_reporte=lambda r, d: Path("/tmp/x"),
        )
    except RuntimeError:
        pass
    # El teardown ocurre en finally aunque el experimento falle.
    assert servicios.detenido
    assert "detener_anvil" in orden
