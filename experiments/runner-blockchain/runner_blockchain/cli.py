"""CLI del Runner_Experimentos: `python -m runner_blockchain e1|e2|e3|all [opciones]` (R7).

Inspirado en `experiments/runner/runner/cli.py`, pero sin AWS: orquesta la corrida de los
experimentos blockchain locales (E1/E2/E3) de extremo a extremo y escribe el
`Reporte_Resultados` de la corrida.

Responsabilidades (tarea 12.1):

* **Selección (R7.6/R7.7).** Acepta exactamente `e1`, `e2`, `e3` o `all` (sin distinguir
  mayúsculas/minúsculas). Cualquier otra selección **rechaza la corrida sin ejecutar nada**
  y registra el error de selección inválida; no se arranca Anvil, no se despliega y no se
  ejecuta ningún experimento. La validación de la selección ocurre **antes** de cualquier
  efecto (orquestación del entorno, inyección, ejecución o lectura de eventos).
* **Orquestación (R7.6).** Para la selección válida prepara el `Entorno_Experimental`
  (arranca Anvil, despliega los contratos y publica `deployment.json`), construye el
  `ChainClient` y el `Lector_Eventos` sobre las direcciones desplegadas, ejecuta cada
  experimento seleccionado (inyección → ejecución → recolección de evidencia por
  `Lector_Eventos`) y agrega los `ExperimentResult` en un `RunReport` que se escribe como
  `report.json` + `report.md` (ver `reporte.py`).

El CLI deja costuras inyectables (`EjecutorExperimentos`) para que las pruebas ejerciten la
selección, el orden y el manejo de errores sin necesitar una cadena viva; por defecto usa la
orquestación real descrita arriba.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol

from .chain.chain_client import build_chain_client
from .chain.deployment import Deployment, load_deployment
from .eventos.lector import LectorEventos
from .experimentos import e1 as mod_e1
from .experimentos import e2 as mod_e2
from .experimentos import e3 as mod_e3
from .orquestador import entorno as mod_entorno
from .reporte import escribir_reporte, reporte_desde_deployment
from .reporte_modelo import ExperimentResult, now_iso
from .servicios import Microservicios, construir_specs

logger = logging.getLogger(__name__)

# Selecciones reconocidas por el CLI (R7.6). `all` ejecuta E1, E2 y E3 en ese orden.
EXPERIMENTOS = ("e1", "e2", "e3")
SELECCIONES = EXPERIMENTOS + ("all",)

# Directorio por defecto donde se escriben los reportes de corrida.
# experiments/runner-blockchain/runner_blockchain/cli.py -> experiments/
REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports-blockchain"

# URLs por defecto de los microservicios que tocan la cadena (puertos del repo). Deben
# coincidir con los puertos que fija el ciclo de vida de servicios (`servicios.py`).
DEFAULT_URL_ORACULO = "http://127.0.0.1:8080"


class SeleccionInvalida(ValueError):
    """Selección distinta de e1/e2/e3/all: la corrida se rechaza sin ejecutar nada (R7.7)."""


def normalizar_seleccion(seleccion: str | None) -> list[str]:
    """Normaliza la selección del CLI a la lista de experimentos a ejecutar (R7.6/R7.7).

    Acepta `e1`/`e2`/`e3`/`all` sin distinguir mayúsculas. `all` se expande a los tres
    experimentos en orden. Cualquier otro valor lanza `SeleccionInvalida` sin producir
    ningún efecto, para que el llamador rechace la corrida y registre el error (R7.7).
    """
    clave = (seleccion or "").strip().lower()
    if clave == "all":
        return list(EXPERIMENTOS)
    if clave in EXPERIMENTOS:
        return [clave]
    raise SeleccionInvalida(
        f"selección de experimento no reconocida: {seleccion!r}; "
        f"opciones válidas: {', '.join(SELECCIONES)}"
    )


# ---------------------------------------------------------------------------
# Opciones de la corrida
# ---------------------------------------------------------------------------
@dataclass
class OpcionesCorrida:
    """Parámetros de una corrida del runner, derivados de los argumentos del CLI."""

    seleccion: str
    run_id: str | None = None
    reports_dir: Path = REPORTS_DIR
    url_oraculo: str = DEFAULT_URL_ORACULO
    ms_venta_url: str = mod_e3.DEFAULT_MS_VENTA_URL
    ms_compra_url: str = mod_e3.DEFAULT_MS_COMPRA_URL
    deployment_path: Path | None = None
    gestionar_entorno: bool = True
    # Levantar los cinco microservicios (readiness por /healthz) como parte de la corrida.
    gestionar_servicios: bool = True
    # JWT de Pinata para ms_certificado (E2); si falta, se usa el fallback local (R3.3/R3.4).
    pinata_jwt: str | None = None
    from_block: int | str = 0
    to_block: int | str = "latest"
    # Backend de ms_certificado para E2 (lo provee el cableado extremo a extremo, tarea 13).
    backend_e2: Any | None = None

    def nuevo_run_id(self) -> str:
        """Identificador de corrida: el provisto o uno derivado de la hora UTC (R7.2)."""
        return self.run_id or time.strftime("RUN-%Y%m%dT%H%M%SZ", time.gmtime())


# ---------------------------------------------------------------------------
# Ejecutor de experimentos (costura inyectable)
# ---------------------------------------------------------------------------
class EjecutorExperimentos(Protocol):
    """Ejecuta un experimento concreto y devuelve su `ExperimentResult`.

    La orquestación real (`OrquestadorReal`) implementa este protocolo cableando cada
    experimento a sus microservicios y al `Lector_Eventos`; las pruebas pueden inyectar un
    ejecutor falso para validar selección/orden/errores sin una cadena viva.
    """

    def __call__(self, nombre: str, run_id: str, lector: LectorEventos) -> ExperimentResult: ...


@dataclass
class OrquestadorReal:
    """Orquestación real de cada experimento contra los microservicios y la cadena (R7.6).

    E1 y E3 se cablean a sus microservicios HTTP y al `Lector_Eventos`. E2 necesita un
    *backend* de `ms_certificado` (anclaje + verificación por contenido): su construcción
    real —con `CertificadoService`, el `ChainClient` y el almacén de contenido— pertenece al
    cableado extremo a extremo (tarea 13), así que aquí se toma de `opciones.backend_e2`
    cuando se provee; si no, E2 devuelve un `ExperimentResult` con error explícito en vez de
    romper la corrida, dejando que E1/E3 (y el reporte) se completen.
    """

    opciones: OpcionesCorrida

    def __call__(self, nombre: str, run_id: str, lector: LectorEventos) -> ExperimentResult:
        if nombre == "e1":
            return mod_e1.ejecutar_e1(
                run_id,
                self.opciones.url_oraculo,
                lector,
                from_block=self.opciones.from_block,
                to_block=self.opciones.to_block,
            )
        if nombre == "e2":
            return self._ejecutar_e2(run_id)
        if nombre == "e3":
            return mod_e3.ejecutar_e3(
                run_id,
                lector,
                venta=mod_e3.HttpVentaClient(self.opciones.ms_venta_url),
                compra=mod_e3.HttpCompraClient(self.opciones.ms_compra_url),
                from_block=self.opciones.from_block,
                to_block=self.opciones.to_block,
            )
        # normalizar_seleccion ya filtró lo desconocido; defensa en profundidad.
        raise SeleccionInvalida(f"experimento no soportado: {nombre!r}")

    def _ejecutar_e2(self, run_id: str) -> ExperimentResult:
        """Ejecuta E2 contra el backend de `ms_certificado` provisto por el cableado (R3)."""
        backend = self.opciones.backend_e2
        if backend is None:
            resultado = ExperimentResult(
                experiment="E2",
                title="E2 — Integridad del certificado off-chain",
                hypothesis="Toda alteración de un certificado se detecta contra el CID anclado.",
                started=now_iso(),
                finished=now_iso(),
                error=(
                    "E2 no se ejecutó: falta el backend de ms_certificado. Provee "
                    "OpcionesCorrida.backend_e2 (cableado extremo a extremo, tarea 13)."
                ),
            )
            resultado.params = {"runId": run_id}
            logger.error("E2 omitido en la corrida %s: backend de ms_certificado no provisto", run_id)
            return resultado
        return mod_e2.ejecutar(backend, run_id=run_id)


# ---------------------------------------------------------------------------
# Corrida completa
# ---------------------------------------------------------------------------
@dataclass
class ResultadoCorrida:
    """Resultado de `ejecutar_corrida`: ruta del reporte, veredicto y resultados."""

    run_id: str
    verdict: str
    report_dir: Path | None
    experiments: list[ExperimentResult] = field(default_factory=list)


def ejecutar_corrida(
    opciones: OpcionesCorrida,
    *,
    preparar_entorno: Callable[..., tuple[Any, Any]] = mod_entorno.preparar_entorno,
    detener_anvil: Callable[[Any], None] = mod_entorno.detener_anvil,
    cargar_deployment: Callable[[Path | None], Deployment] = load_deployment,
    construir_lector: Callable[[Deployment], LectorEventos] | None = None,
    construir_servicios: Callable[[Deployment, OpcionesCorrida], Any] | None = None,
    construir_backend_e2: Callable[[Deployment, OpcionesCorrida], Any] | None = None,
    ejecutor: EjecutorExperimentos | None = None,
    escritor_reporte: Callable[..., Path] = escribir_reporte,
) -> ResultadoCorrida:
    """Orquesta una corrida completa: selección → entorno → ejecución → recolección → reporte.

    Pasos (R7.1, R7.6):

    1. **Selección (R7.7).** Normaliza `opciones.seleccion`; si no es e1/e2/e3/all lanza
       `SeleccionInvalida` *antes* de preparar el entorno, por lo que no se produce ningún
       efecto.
    2. **Entorno (R1).** `preparar_entorno` arranca Anvil, despliega los contratos y publica
       `deployment.json`; de ahí se cargan las direcciones (`Deployment`).
    3. **Microservicios (R5).** Se levantan los cinco microservicios que tocan la cadena
       (`ms_oraculo`, `ms_energia`, `ms_venta`, `ms_compra`, `ms_certificado`) como procesos
       hijo y se espera su readiness por `GET /healthz` antes de inyectar casos.
    4. **Cadena/eventos.** Se construye el `ChainClient` sobre las direcciones desplegadas y
       el `Lector_Eventos` para recolectar la evidencia on-chain de cada experimento (R6).
       Si E2 está en la selección y no se pasó un `backend_e2`, se construye el
       `BackendEnProceso` de `ms_certificado` cableado al mismo despliegue.
    5. **Ejecución.** Se ejecuta cada experimento seleccionado con el `ejecutor` (real por
       defecto), recogiendo su `ExperimentResult`.
    6. **Reporte (R7.1–R7.5).** Se agregan los resultados en un `RunReport` tomando
       contratos/herramientas del despliegue y se escribe `report.json` + `report.md`.

    Teardown: los microservicios se detienen y luego Anvil, ambos en un `finally`, para no
    dejar procesos vivos aunque un experimento falle.

    Las costuras `preparar_entorno`, `cargar_deployment`, `construir_lector`,
    `construir_servicios`, `construir_backend_e2`, `ejecutor` y `escritor_reporte` se pueden
    inyectar en pruebas; por defecto usan la orquestación real.
    """
    # 1) Selección: rechazar sin efectos lo no reconocido (R7.7).
    nombres = normalizar_seleccion(opciones.seleccion)

    run_id = opciones.nuevo_run_id()
    inicio = now_iso()
    logger.info("inicio de corrida %s: experimentos=%s", run_id, nombres)

    anvil = None
    servicios: Any | None = None
    deployment: Deployment | None = None
    gestionado = opciones.gestionar_entorno
    levantar_servicios = opciones.gestionar_servicios
    resultados: list[ExperimentResult] = []
    try:
        # 2) Entorno: arranca Anvil, despliega y publica deployment.json (R1).
        if gestionado:
            _, anvil = preparar_entorno(deployment_path=opciones.deployment_path)
        deployment = cargar_deployment(opciones.deployment_path)

        # 3) Microservicios: arrancar y esperar readiness por /healthz (R5, R7.6).
        if levantar_servicios:
            constructor = construir_servicios or _servicios_por_defecto
            servicios = constructor(deployment, opciones)
            servicios.iniciar()

        # 3b) Backend de E2 (ms_certificado) cableado al despliegue, si hace falta.
        if "e2" in nombres and opciones.backend_e2 is None:
            fabrica = construir_backend_e2 or _backend_e2_por_defecto
            opciones.backend_e2 = fabrica(deployment, opciones)

        # 4) Lector_Eventos sobre las direcciones desplegadas (R6).
        lector = (
            construir_lector(deployment)
            if construir_lector is not None
            else _lector_por_defecto(deployment)
        )
        correr = ejecutor if ejecutor is not None else OrquestadorReal(opciones)

        # 5) Ejecución por experimento (inyección → ejecución → recolección).
        for nombre in nombres:
            logger.info("ejecutando %s en la corrida %s", nombre, run_id)
            resultados.append(correr(nombre, run_id, lector))
    finally:
        if servicios is not None:
            servicios.detener()
        if gestionado and anvil is not None:
            detener_anvil(anvil)

    fin = now_iso()

    # 5) Reporte de corrida (R7.1–R7.5). Si llegamos aquí, el despliegue se cargó.
    if deployment is not None:
        reporte = reporte_desde_deployment(
            run_id,
            resultados,
            deployment,
            params={"seleccion": opciones.seleccion, "experimentos": nombres},
            started=inicio,
            finished=fin,
        )
    else:  # pragma: no cover - sin despliegue no construimos reporte con contratos.
        from .reporte import construir_reporte

        reporte = construir_reporte(run_id, resultados, started=inicio, finished=fin)

    report_dir = escritor_reporte(reporte, opciones.reports_dir)
    logger.info("corrida %s terminada: veredicto=%s reporte=%s", run_id, reporte.verdict, report_dir)
    return ResultadoCorrida(
        run_id=run_id,
        verdict=reporte.verdict,
        report_dir=report_dir,
        experiments=resultados,
    )


def _lector_por_defecto(deployment: Deployment) -> LectorEventos:
    """Construye el `Lector_Eventos` real sobre el `ChainClient` de la corrida (R6)."""
    client = build_chain_client(deployment.rpc_url, contratos=dict(deployment.contratos))
    return LectorEventos(client)


def _servicios_por_defecto(deployment: Deployment, opciones: OpcionesCorrida) -> Microservicios:
    """Construye el gestor de los cinco microservicios cableado al despliegue de la corrida (R5)."""
    specs = construir_specs(
        deployment_path=deployment.ruta,
        rpc_url=deployment.rpc_url,
        pinata_jwt=opciones.pinata_jwt,
    )
    return Microservicios(specs)


def _backend_e2_por_defecto(deployment: Deployment, opciones: OpcionesCorrida) -> Any:
    """Construye el `BackendEnProceso` de E2 (ms_certificado) cableado al despliegue (R3).

    El JWT de Pinata se toma de `opciones.pinata_jwt` o, si falta, de `PINATA_JWT` del
    entorno (nunca se registra; R3.4). Sin credenciales se usa el fallback local (R3.3).
    """
    jwt = opciones.pinata_jwt or os.environ.get("PINATA_JWT")
    return mod_e2.construir_backend_en_proceso(deployment, pinata_jwt=jwt)


# ---------------------------------------------------------------------------
# Argparse
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    """Construye el parser del CLI: `seleccion` posicional + opciones de la corrida.

    `seleccion` **no** se restringe con `choices` de argparse a propósito: así una selección
    no reconocida llega a `main`, que la rechaza registrando el error de selección inválida
    (R7.7) en lugar del mensaje genérico de argparse.
    """
    p = argparse.ArgumentParser(
        prog="python -m runner_blockchain",
        description="Runner de la experimentación blockchain local de Voltera (E1/E2/E3).",
    )
    p.add_argument(
        "seleccion",
        help="experimento a ejecutar: e1, e2, e3 o all (los tres en orden)",
    )
    p.add_argument("--run-id", default=None, help="identificador de la corrida (por defecto RUN-<UTC>)")
    p.add_argument(
        "--reports-dir",
        default=str(REPORTS_DIR),
        help="directorio donde escribir report.json/report.md (por defecto experiments/reports-blockchain)",
    )
    p.add_argument("--url-oraculo", default=DEFAULT_URL_ORACULO, help="URL base de ms_oraculo (E1)")
    p.add_argument("--ms-venta-url", default=mod_e3.DEFAULT_MS_VENTA_URL, help="URL base de ms_venta (E3)")
    p.add_argument("--ms-compra-url", default=mod_e3.DEFAULT_MS_COMPRA_URL, help="URL base de ms_compra (E3)")
    p.add_argument(
        "--deployment",
        default=None,
        help="ruta de deployment.json (por defecto ROOT/deployment.json)",
    )
    p.add_argument(
        "--sin-entorno",
        dest="gestionar_entorno",
        action="store_false",
        help="no arrancar/desplegar Anvil; usar un deployment.json ya existente",
    )
    p.add_argument(
        "--sin-servicios",
        dest="gestionar_servicios",
        action="store_false",
        help="no levantar los microservicios; usar instancias ya en ejecucion",
    )
    p.set_defaults(gestionar_entorno=True, gestionar_servicios=True)
    return p


def opciones_desde_args(a: argparse.Namespace) -> OpcionesCorrida:
    """Construye `OpcionesCorrida` a partir del `Namespace` de argparse."""
    return OpcionesCorrida(
        seleccion=a.seleccion,
        run_id=a.run_id,
        reports_dir=Path(a.reports_dir),
        url_oraculo=a.url_oraculo,
        ms_venta_url=a.ms_venta_url,
        ms_compra_url=a.ms_compra_url,
        deployment_path=Path(a.deployment) if a.deployment else None,
        gestionar_entorno=a.gestionar_entorno,
        gestionar_servicios=a.gestionar_servicios,
    )


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main(argv: Iterable[str] | None = None, *, correr=ejecutar_corrida) -> int:
    """Punto de entrada del CLI. Devuelve el código de salida del proceso.

    Códigos: `0` corrida PASS, `1` corrida FAIL, `2` selección inválida (R7.7) o error de
    orquestación. La selección se valida antes de cualquier efecto: una selección no
    reconocida se rechaza registrando el error, sin ejecutar ningún experimento.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    a = build_parser().parse_args(list(argv) if argv is not None else None)

    # R7.7: validar la selección antes de orquestar nada.
    try:
        nombres = normalizar_seleccion(a.seleccion)
    except SeleccionInvalida as exc:
        logger.error("corrida rechazada: %s", exc)
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    opciones = opciones_desde_args(a)
    try:
        resultado = correr(opciones)
    except SeleccionInvalida as exc:  # defensa en profundidad (no debería ocurrir aquí).
        logger.error("corrida rechazada: %s", exc)
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # fallo de orquestación (entorno/cadena): no hay reporte.
        logger.error("corrida %s abortada: %s", a.run_id or "(auto)", exc)
        print(f"Corrida abortada: {exc}", file=sys.stderr)
        return 2

    print(f"\n== Corrida {resultado.run_id}: {resultado.verdict}")
    if resultado.report_dir is not None:
        print(f"   reporte: {resultado.report_dir}")
    for r in resultado.experiments:
        print(f"   [{r.verdict:4}] {r.experiment} {r.title}")
    _ = nombres  # usados por correr(); mantenidos para trazabilidad/depuración.
    return 0 if resultado.verdict == "PASS" else 1


__all__ = [
    "EXPERIMENTOS",
    "SELECCIONES",
    "SeleccionInvalida",
    "normalizar_seleccion",
    "OpcionesCorrida",
    "OrquestadorReal",
    "ResultadoCorrida",
    "ejecutar_corrida",
    "build_parser",
    "opciones_desde_args",
    "main",
]
