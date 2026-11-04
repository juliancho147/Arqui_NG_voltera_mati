"""Ciclo de vida de los cinco microservicios que tocan la cadena (R5, R7.1, R7.6).

El cableado extremo a extremo de la corrida `all` (tarea 13.1) necesita, entre el arranque
del entorno (Anvil + despliegue) y la ejecucion de los experimentos, **levantar los cinco
microservicios** (`ms_oraculo`, `ms_energia`, `ms_venta`, `ms_compra`, `ms_certificado`) como
procesos hijo, **esperar su readiness** por `GET /healthz` y, al terminar, **detenerlos** de
forma ordenada. Este modulo concentra esa responsabilidad para mantener `cli.py` legible y
para dejar costuras inyectables que las pruebas puedan ejercitar sin servicios vivos.

Cada microservicio vive en `services/ms-*/` con un `main.py` ejecutable (`python main.py`)
que importa su `config`/`main` como modulos de nivel superior y agrega
`experiments/runner-blockchain` al `sys.path` por su cuenta. Por eso se arrancan con
``cwd`` en su propia carpeta. La configuracion (puertos, URLs entre servicios, ruta de
`deployment.json`, RPC y llave custodial) se pasa por **variables de entorno**, de modo que:

* los puertos sean consistentes y no colisionen (ver `PUERTOS`),
* `ms_oraculo` sepa publicar `GeneracionValidada` a `ms_energia` (`MS_ENERGIA_URL`),
* todos resuelvan las direcciones de los contratos desde el mismo `deployment.json`.

Puertos (de los modulos `config` de cada servicio; el task 13.1 fija estos valores):

===============  ==========  ========================================
servicio         puerto      variable de entorno que lo fija
===============  ==========  ========================================
ms_oraculo       8080        HEALTH_PORT
ms_energia       8081        HEALTH_PORT (configurable; 8080 por defecto)
ms_venta         8083        HEALTH_PORT
ms_compra        8084        MS_COMPRA_PORT
ms_certificado   8085        MS_CERTIFICADO_PORT
===============  ==========  ========================================

`ms_oraculo` publica a `ms_energia` via `MS_ENERGIA_URL`, que aqui se apunta al puerto 8081
para que no colisione con el 8080 del propio oraculo.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib import error as urlerror
from urllib import request as urlrequest

logger = logging.getLogger(__name__)

# experiments/runner-blockchain/runner_blockchain/servicios.py -> repo root
ROOT = Path(__file__).resolve().parents[3]
SERVICES_DIR = ROOT / "services"

HOST = "127.0.0.1"

# Puertos por servicio (task 13.1). ms_energia es configurable; aqui 8081 para no chocar con
# el 8080 de ms_oraculo (que ademas publica a ms_energia por MS_ENERGIA_URL).
PUERTO_ORACULO = 8080
PUERTO_ENERGIA = 8081
PUERTO_VENTA = 8083
PUERTO_COMPRA = 8084
PUERTO_CERTIFICADO = 8085

# Tope de readiness por servicio (consistente con el readiness de Anvil del orquestador).
READINESS_TIMEOUT_S = 30
READINESS_POLL_INTERVAL_S = 0.5


class ServicioError(RuntimeError):
    """Fallo al arrancar o esperar la readiness de un microservicio (causa registrada)."""


@dataclass(frozen=True)
class EspecServicio:
    """Describe como arrancar y sondear un microservicio.

    * `nombre`: identificador legible (p. ej. `ms_oraculo`).
    * `directorio`: carpeta del servicio (`services/ms-*/`), que es el `cwd` del proceso.
    * `puerto`: puerto HTTP donde escucha `/healthz` y los endpoints de dominio.
    * `env`: variables de entorno adicionales especificas del servicio (puerto, URLs, etc.).
    """

    nombre: str
    directorio: Path
    puerto: int
    env: dict[str, str] = field(default_factory=dict)

    @property
    def base_url(self) -> str:
        return f"http://{HOST}:{self.puerto}"

    @property
    def health_url(self) -> str:
        return f"{self.base_url}/healthz"


@dataclass
class ServicioEnEjecucion:
    """Un microservicio arrancado: su especificacion y el proceso hijo asociado."""

    spec: EspecServicio
    proceso: subprocess.Popen[bytes]


def _dir_servicio(nombre_carpeta: str) -> Path:
    return SERVICES_DIR / nombre_carpeta


def construir_specs(
    *,
    deployment_path: Path | None = None,
    rpc_url: str | None = None,
    pinata_jwt: str | None = None,
) -> list[EspecServicio]:
    """Construye las especificaciones de los cinco microservicios con sus puertos/URLs (R5).

    Las variables de entorno fijan puertos consistentes y el cableado entre servicios:
    `ms_oraculo` publica `GeneracionValidada` a `ms_energia` (`MS_ENERGIA_URL`), y todos
    resuelven las direcciones de los contratos desde el mismo `deployment.json` (`DEPLOYMENT_PATH`).
    `rpc_url`/`pinata_jwt` se pasan solo si estan disponibles (si no, cada servicio usa su
    valor por defecto y, para Pinata, el fallback local de R3.3).
    """
    base_env: dict[str, str] = {}
    if deployment_path is not None:
        base_env["DEPLOYMENT_PATH"] = str(deployment_path)
    if rpc_url:
        base_env["RPC_URL"] = rpc_url

    energia_url = f"http://{HOST}:{PUERTO_ENERGIA}"

    oraculo_env = {"HEALTH_PORT": str(PUERTO_ORACULO), "MS_ENERGIA_URL": energia_url}
    energia_env = {**base_env, "HEALTH_PORT": str(PUERTO_ENERGIA)}
    venta_env = {**base_env, "HEALTH_PORT": str(PUERTO_VENTA)}
    compra_env = {**base_env, "MS_COMPRA_PORT": str(PUERTO_COMPRA), "MS_COMPRA_HOST": HOST}
    certificado_env = {**base_env, "MS_CERTIFICADO_PORT": str(PUERTO_CERTIFICADO)}
    if pinata_jwt:
        certificado_env["PINATA_JWT"] = pinata_jwt

    return [
        EspecServicio("ms_energia", _dir_servicio("ms-energia"), PUERTO_ENERGIA, energia_env),
        EspecServicio("ms_oraculo", _dir_servicio("ms-oraculo"), PUERTO_ORACULO, oraculo_env),
        EspecServicio("ms_venta", _dir_servicio("ms-venta"), PUERTO_VENTA, venta_env),
        EspecServicio("ms_compra", _dir_servicio("ms-compra"), PUERTO_COMPRA, compra_env),
        EspecServicio("ms_certificado", _dir_servicio("ms-certificado"), PUERTO_CERTIFICADO, certificado_env),
    ]


# ---------------------------------------------------------------------------
# Arranque y readiness
# ---------------------------------------------------------------------------
def arrancar_servicio(spec: EspecServicio) -> subprocess.Popen[bytes]:
    """Arranca `python main.py` del servicio en su carpeta como proceso hijo.

    El `cwd` es la carpeta del servicio porque su `main.py` importa `config`/`main` como
    modulos de nivel superior. El entorno del proceso hereda el actual y aplica las
    variables de `spec.env` (puertos, URLs entre servicios, `DEPLOYMENT_PATH`, etc.).
    """
    if not (spec.directorio / "main.py").is_file():
        raise ServicioError(f"{spec.nombre}: no se encontro main.py en {spec.directorio}")
    env = os.environ.copy()
    env.update(spec.env)
    cmd = [sys.executable, "main.py"]
    logger.info("arrancando %s en :%d (cwd=%s)", spec.nombre, spec.puerto, spec.directorio)
    try:
        return subprocess.Popen(  # noqa: S603 (argumentos controlados)
            cmd,
            cwd=str(spec.directorio),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    except OSError as exc:
        raise ServicioError(f"{spec.nombre}: no se pudo arrancar el proceso: {exc}") from exc


def _healthz_responde(url: str, *, timeout: float = 2.0) -> bool:
    """True si `GET {url}` responde 2xx (readiness del servicio)."""
    try:
        with urlrequest.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (URL interna controlada)
            codigo = resp.getcode()
            resp.read()
    except urlerror.HTTPError as exc:
        # 503 mientras arranca: no listo todavia; el polling reintenta.
        return 200 <= exc.code < 300
    except (urlerror.URLError, OSError):
        return False
    return 200 <= int(codigo) < 300


def esperar_readiness(
    spec: EspecServicio,
    *,
    proceso: subprocess.Popen[bytes] | None = None,
    timeout_s: int = READINESS_TIMEOUT_S,
    intervalo_s: float = READINESS_POLL_INTERVAL_S,
    sonda: Callable[[str], bool] = _healthz_responde,
) -> None:
    """Sondea `GET /healthz` del servicio hasta responder, con tope de 30 s (R7.6).

    Si el proceso hijo muere antes de responder, aborta con la causa (incluyendo la cola de
    su salida para depurar). Si se agota el tope, lanza `ServicioError`.
    """
    limite = time.monotonic() + timeout_s
    while time.monotonic() < limite:
        if proceso is not None and proceso.poll() is not None:
            raise ServicioError(
                f"{spec.nombre}: el proceso termino antes de responder /healthz "
                f"(codigo {proceso.returncode}){_cola_salida(proceso)}"
            )
        if sonda(spec.health_url):
            logger.info("%s listo en %s", spec.nombre, spec.health_url)
            return
        time.sleep(intervalo_s)
    raise ServicioError(
        f"{spec.nombre}: no respondio a GET {spec.health_url} en {timeout_s} s"
    )


def _cola_salida(proceso: subprocess.Popen[bytes], n: int = 500) -> str:
    """Devuelve la cola de la salida capturada del proceso (para el mensaje de error)."""
    salida = proceso.stdout
    if salida is None:
        return ""
    try:
        datos = salida.read() or b""
    except (ValueError, OSError):
        return ""
    texto = datos.decode("utf-8", "replace").strip()
    if not texto:
        return ""
    return f": {texto[-n:]}"


def detener_servicio(ejecucion: ServicioEnEjecucion, *, timeout_s: float = 10.0) -> None:
    """Detiene un microservicio (terminate, luego kill) de forma idempotente."""
    proceso = ejecucion.proceso
    if proceso.poll() is not None:
        return
    logger.info("deteniendo %s (pid=%s)", ejecucion.spec.nombre, proceso.pid)
    proceso.terminate()
    try:
        proceso.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        proceso.kill()
        try:
            proceso.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:  # pragma: no cover - el kill deberia bastar
            logger.warning("%s no termino tras kill", ejecucion.spec.nombre)


# ---------------------------------------------------------------------------
# Orquestacion del conjunto de microservicios
# ---------------------------------------------------------------------------
class Microservicios:
    """Gestiona el ciclo de vida del conjunto de microservicios de la corrida.

    Uso tipico (lo hace el cableado del CLI):

        servicios = Microservicios(specs)
        servicios.iniciar()          # arranca los 5 y espera su readiness por /healthz
        try:
            ...                       # ejecutar E1/E2/E3 contra los servicios vivos
        finally:
            servicios.detener()       # los detiene en orden inverso

    Las funciones de arranque, readiness y parada se inyectan para poder probar la
    orquestacion (orden de arranque, manejo de fallo de readiness, teardown) sin procesos
    reales ni puertos abiertos.
    """

    def __init__(
        self,
        specs: list[EspecServicio],
        *,
        arrancar: Callable[[EspecServicio], subprocess.Popen[bytes]] = arrancar_servicio,
        esperar: Callable[..., None] = esperar_readiness,
        detener: Callable[[ServicioEnEjecucion], None] = detener_servicio,
        readiness_timeout_s: int = READINESS_TIMEOUT_S,
    ) -> None:
        self.specs = list(specs)
        self._arrancar = arrancar
        self._esperar = esperar
        self._detener = detener
        self._readiness_timeout_s = readiness_timeout_s
        self.en_ejecucion: list[ServicioEnEjecucion] = []

    def iniciar(self) -> list[ServicioEnEjecucion]:
        """Arranca cada microservicio y espera su readiness; si uno falla, detiene todos.

        El orden de arranque respeta las dependencias de publicacion (`ms_energia` antes que
        `ms_oraculo`, que le publica `GeneracionValidada`). Ante cualquier fallo de arranque
        o readiness, detiene los ya levantados y propaga `ServicioError` para que la corrida
        se aborte sin dejar procesos huerfanos.
        """
        try:
            for spec in self.specs:
                proceso = self._arrancar(spec)
                ejecucion = ServicioEnEjecucion(spec=spec, proceso=proceso)
                self.en_ejecucion.append(ejecucion)
                self._esperar(spec, proceso=proceso, timeout_s=self._readiness_timeout_s)
        except Exception:
            self.detener()
            raise
        return list(self.en_ejecucion)

    def detener(self) -> None:
        """Detiene los microservicios levantados en orden inverso al de arranque (idempotente)."""
        for ejecucion in reversed(self.en_ejecucion):
            try:
                self._detener(ejecucion)
            except Exception:  # pragma: no cover - el teardown no debe enmascarar el error previo
                logger.exception("fallo al detener %s", ejecucion.spec.nombre)
        self.en_ejecucion = []


__all__ = [
    "ServicioError",
    "EspecServicio",
    "ServicioEnEjecucion",
    "Microservicios",
    "construir_specs",
    "arrancar_servicio",
    "esperar_readiness",
    "detener_servicio",
    "PUERTO_ORACULO",
    "PUERTO_ENERGIA",
    "PUERTO_VENTA",
    "PUERTO_COMPRA",
    "PUERTO_CERTIFICADO",
]
