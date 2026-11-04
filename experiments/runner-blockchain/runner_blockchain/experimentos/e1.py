"""E1 — Integridad del Oracle (R2).

E1 valida que ninguna lectura invalida llega a emitir tokens. El flujo es:

1. Generar, con una semilla fija derivada de `runId`/parametros (reproducibilidad, R7.4),
   exactamente 200 lecturas invalidas (>=50 por cada una de las tres categorias:
   `valor_alterado`, `medidor_desconocido`, `lectura_duplicada`) mezcladas con exactamente
   200 lecturas validas (R2.1).
2. Inyectar cada caso a `ms_oraculo` (`POST /lecturas`). Una lectura valida aceptada publica
   `GeneracionValidada` -> `ms_energia` -> `EnergyToken.emitir` -> evento `Emitido` (R2.4).
   Una lectura invalida se rechaza sin emitir (R2.3).
3. Medir, para cada lectura valida, la latencia desde `LecturaRegistrada` (justo antes de
   enviar la lectura a `ms_oraculo`) hasta `GeneracionValidada` (respuesta `aceptada` del
   oraculo, que solo retorna tras publicar a `ms_energia`) con `time.monotonic` (R2.7).
4. Si la Cadena_Local o `ms_oraculo` no responden durante 30 s, abortar E1 con veredicto FAIL
   por indisponibilidad (R2.9).
5. Al finalizar, calcular via el `Lector_Eventos`:
   * tasa de rechazo de las 200 invalidas (debe ser 100%, R2.5),
   * conteo de eventos `Emitido` originados por lecturas invalidas (debe ser 0, R2.6),
   * Latencia_p95 de las 200 validas (debe ser <= 10 s, R2.8),
   y asignar PASS si y solo si tasa=100% y emitidas_invalidas=0 y p95<=10 s (R2.10).

Diseno de duplicados
--------------------
`ms_oraculo` rechaza como `lectura_duplicada` una lectura cuyo `lecturaId` o cuya tupla
(medidor, epoca) ya fue *aceptada* en la corrida. Para que las invalidas de esa categoria se
rechacen de forma determinista, el generador las construye como copias de lecturas validas
del mismo dataset y el orden de inyeccion garantiza que la valida original se inyecta (y
acepta) antes que su duplicado.

Correlacion on-chain
--------------------
`ms_energia` emite `EnergyToken.emitir(..., lecturaId)` con `lecturaId` como `bytes32`
derivado con keccak256 del texto del `lecturaId` (o hex literal de 32 bytes). Para verificar
"0 `Emitido` por invalidas" (R2.6) se mapea el `lecturaId` de cada invalida a ese mismo
`bytes32` y se comprueba que ninguno aparece entre los `Emitido` observados por el lector.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from ..eventos.lector import EventoOnChain, LectorEventos, LectorEventosError
from ..reporte_modelo import ExperimentResult, now_iso

logger = logging.getLogger(__name__)

# --- Categorias de invalidez (coinciden con ms_oraculo/oraculo.py) -----------
VALOR_ALTERADO = "valor_alterado"
MEDIDOR_DESCONOCIDO = "medidor_desconocido"
LECTURA_DUPLICADA = "lectura_duplicada"
CATEGORIAS = (VALOR_ALTERADO, MEDIDOR_DESCONOCIDO, LECTURA_DUPLICADA)

# --- Cantidades del experimento (R2.1) ---------------------------------------
N_INVALIDAS = 200
N_VALIDAS = 200
MIN_POR_CATEGORIA = 50

# --- Umbrales (R2.8, R2.10) ---------------------------------------------------
P95_MAX_S = 10.0
# Tope de indisponibilidad de cadena/oraculo mientras corre E1 (R2.9).
INDISPONIBILIDAD_TIMEOUT_S = 30

# --- Padron de medidores conocido (stub de ms_oraculo) -----------------------
# Debe coincidir con services/ms-oraculo/stubs.py (PADRON_POR_DEFECTO) para que las validas
# sean aceptadas y las invalidas de valor rechazadas de forma determinista.
PADRON: dict[str, dict[str, int]] = {
    "MED-001": {"solar": 100, "eolica": 80},
    "MED-002": {"solar": 120, "eolica": 90},
    "MED-003": {"solar": 60, "hidro": 150},
    "MED-004": {"solar": 200},
    "MED-005": {"eolica": 110, "hidro": 140},
}

# Factores estacionales por fuente y mes (1..12), identicos al ClimaStub de ms_oraculo.
FACTORES_ESTACIONALES: dict[str, tuple[float, ...]] = {
    "solar": (0.6, 0.7, 0.9, 1.0, 1.1, 1.2, 1.3, 1.2, 1.0, 0.9, 0.7, 0.6),
    "eolica": (1.2, 1.2, 1.1, 1.0, 0.9, 0.8, 0.8, 0.9, 1.0, 1.1, 1.2, 1.2),
    "hidro": (1.0, 1.0, 1.1, 1.1, 1.0, 0.9, 0.9, 0.9, 1.0, 1.0, 1.1, 1.0),
}
# Tolerancia relativa del oraculo (Settings.tolerancia_relativa por defecto).
TOLERANCIA_RELATIVA = 0.10

# Direccion seudonima del participante (cuenta 1 de Anvil por defecto); la emision es custodial.
PARTICIPANTE_DEFECTO = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"


class E1Error(RuntimeError):
    """Error de ejecucion de E1 que impide producir un veredicto valido."""


# ---------------------------------------------------------------------------
# Modelo de caso y dataset
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CasoE1:
    """Un caso inyectable de E1: una lectura con su clasificacion esperada.

    * `valida`: True si la lectura debe ser aceptada por el oraculo.
    * `categoria`: categoria de invalidez esperada (None si `valida`).
    * `lectura`: payload JSON que se envia a `ms_oraculo` `POST /lecturas`.
    """

    lectura_id: str
    valida: bool
    categoria: str | None
    lectura: dict[str, Any]

    def lectura_id_bytes32(self) -> str:
        """`lecturaId` como `bytes32` keccak256 (igual que ms_energia) en hex `0x...`."""
        return lectura_id_a_bytes32(self.lectura_id)


@dataclass(frozen=True)
class DatasetE1:
    """Dataset reproducible de E1: casos en orden de inyeccion + semilla usada."""

    seed: int
    casos: tuple[CasoE1, ...]

    @property
    def validas(self) -> tuple[CasoE1, ...]:
        return tuple(c for c in self.casos if c.valida)

    @property
    def invalidas(self) -> tuple[CasoE1, ...]:
        return tuple(c for c in self.casos if not c.valida)

    def por_categoria(self) -> dict[str, int]:
        """Conteo de invalidas por categoria."""
        conteo = {cat: 0 for cat in CATEGORIAS}
        for c in self.invalidas:
            if c.categoria in conteo:
                conteo[c.categoria] += 1
        return conteo


# ---------------------------------------------------------------------------
# Helpers deterministas (referencia esperada / bytes32)
# ---------------------------------------------------------------------------
def factor_estacional(fuente: str, epoca: int) -> float:
    tabla = FACTORES_ESTACIONALES.get(fuente)
    if not tabla:
        return 1.0
    mes = int(epoca) % 100
    return tabla[mes - 1] if 1 <= mes <= 12 else 1.0


def referencia_esperada(medidor_id: str, fuente: str, epoca: int) -> int | None:
    """Referencia esperada de kWh = base del padron ajustada por el factor estacional."""
    base = PADRON.get(medidor_id, {}).get(fuente)
    if base is None:
        return None
    return int(base * factor_estacional(fuente, epoca))


def lectura_id_a_bytes32(lectura_id: str) -> str:
    """Deriva el `bytes32` de un `lecturaId` igual que ms_energia (`keccak256` del texto).

    Replica `Web3.keccak(text=...)` sin requerir web3: keccak256 (sha3 de Ethereum) del UTF-8.
    Si `lectura_id` ya es hex de 32 bytes, se usa literal (coherente con `_a_bytes32`).
    """
    s = lectura_id.strip()
    if s.startswith("0x") and len(s) == 66:
        try:
            bytes.fromhex(s[2:])
            return s.lower()
        except ValueError:
            pass
    digest = _keccak256(s.encode("utf-8"))
    return "0x" + digest.hex()


def _keccak256(data: bytes) -> bytes:
    """keccak256 (Ethereum sha3). Usa pysha3/`hashlib` segun disponibilidad."""
    try:
        h = hashlib.new("keccak_256")
    except (ValueError, TypeError):
        # Fallback: eth_utils.keccak (disponible via web3/eth-account en este paquete).
        from eth_utils import keccak  # type: ignore

        return keccak(data)
    h.update(data)
    return h.digest()


# ---------------------------------------------------------------------------
# Generacion del dataset (semilla fija -> reproducible, R2.1 / R7.4)
# ---------------------------------------------------------------------------
def derivar_semilla(run_id: str, params: dict[str, Any] | None = None) -> int:
    """Deriva una semilla entera estable a partir de `runId` y parametros (R7.4).

    La misma combinacion (`run_id`, `params`) produce siempre la misma semilla, y por tanto
    el mismo dataset y el mismo veredicto.
    """
    material = json.dumps(
        {"runId": run_id, "params": params or {}},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big")


def _xorshift(estado: int) -> tuple[int, int]:
    """PRNG determinista (xorshift64) para no depender del orden interno de `random`.

    Devuelve `(valor, nuevo_estado)`. Simple y reproducible entre versiones de Python.
    """
    x = estado & 0xFFFFFFFFFFFFFFFF
    if x == 0:
        x = 0x9E3779B97F4A7C15
    x ^= (x << 13) & 0xFFFFFFFFFFFFFFFF
    x ^= x >> 7
    x ^= (x << 17) & 0xFFFFFFFFFFFFFFFF
    x &= 0xFFFFFFFFFFFFFFFF
    return x, x


class _Rng:
    """Generador determinista minimo sobre xorshift64 (reproducible por semilla)."""

    def __init__(self, seed: int) -> None:
        self._estado = (seed & 0xFFFFFFFFFFFFFFFF) or 0x9E3779B97F4A7C15

    def _next(self) -> int:
        valor, self._estado = _xorshift(self._estado)
        return valor

    def randint(self, lo: int, hi: int) -> int:
        """Entero uniforme en [lo, hi] (inclusivo)."""
        span = hi - lo + 1
        return lo + (self._next() % span)

    def choice(self, seq: list[Any]) -> Any:
        return seq[self._next() % len(seq)]


def _medidores_fuentes() -> list[tuple[str, str]]:
    """Lista estable de pares (medidor, fuente) validos del padron, ordenada."""
    pares: list[tuple[str, str]] = []
    for medidor in sorted(PADRON):
        for fuente in sorted(PADRON[medidor]):
            pares.append((medidor, fuente))
    return pares


def _nueva_valida(rng: _Rng, indice: int, pares: list[tuple[str, str]]) -> CasoE1:
    """Construye una lectura valida unica (medidor+epoca unicos, kWh dentro de tolerancia)."""
    medidor, fuente = pares[indice % len(pares)]
    # Epoca unica por caso: anio base 2026 + mes 1..12; el indice evita colisiones (medidor,epoca).
    anio = 2026 + (indice // 12)
    mes = (indice % 12) + 1
    epoca = anio * 100 + mes
    referencia = referencia_esperada(medidor, fuente, epoca) or 1
    # kWh dentro de la tolerancia relativa: variacion determinista acotada por el margen.
    margen = int(referencia * TOLERANCIA_RELATIVA)
    delta = rng.randint(-margen, margen) if margen > 0 else 0
    kwh = max(0, referencia + delta)
    precio = rng.randint(1, 50)
    lectura_id = f"E1-V-{indice:04d}"
    return CasoE1(
        lectura_id=lectura_id,
        valida=True,
        categoria=None,
        lectura={
            "lecturaId": lectura_id,
            "medidorId": medidor,
            "epoca": epoca,
            "fuente": fuente,
            "kwh": kwh,
            "precio": precio,
            "participante": PARTICIPANTE_DEFECTO,
        },
    )


def _invalida_valor_alterado(rng: _Rng, indice: int, pares: list[tuple[str, str]]) -> CasoE1:
    """Lectura con medidor/fuente conocidos pero kWh muy fuera de la tolerancia."""
    medidor, fuente = pares[indice % len(pares)]
    anio = 2030 + (indice // 12)
    mes = (indice % 12) + 1
    epoca = anio * 100 + mes
    referencia = referencia_esperada(medidor, fuente, epoca) or 1
    # Muy por encima de la referencia (>> tolerancia) para forzar valor_alterado determinista.
    kwh = referencia * (3 + rng.randint(0, 5))
    lectura_id = f"E1-I-VAL-{indice:04d}"
    return CasoE1(
        lectura_id=lectura_id,
        valida=False,
        categoria=VALOR_ALTERADO,
        lectura={
            "lecturaId": lectura_id,
            "medidorId": medidor,
            "epoca": epoca,
            "fuente": fuente,
            "kwh": kwh,
            "precio": rng.randint(1, 50),
            "participante": PARTICIPANTE_DEFECTO,
        },
    )


def _invalida_medidor_desconocido(rng: _Rng, indice: int) -> CasoE1:
    """Lectura cuyo medidor no esta en el padron (medidor_desconocido)."""
    medidor = f"MED-999-{indice:04d}"
    epoca = 203001 + indice
    lectura_id = f"E1-I-MED-{indice:04d}"
    return CasoE1(
        lectura_id=lectura_id,
        valida=False,
        categoria=MEDIDOR_DESCONOCIDO,
        lectura={
            "lecturaId": lectura_id,
            "medidorId": medidor,
            "epoca": epoca,
            "fuente": "solar",
            "kwh": rng.randint(1, 500),
            "precio": rng.randint(1, 50),
            "participante": PARTICIPANTE_DEFECTO,
        },
    )


def _invalida_duplicada(indice: int, original: CasoE1) -> CasoE1:
    """Duplicado de una lectura valida: mismo (medidor, epoca) -> lectura_duplicada.

    Se usa un `lecturaId` distinto para ejercitar la deteccion por tupla (medidor, epoca),
    que es la clave que el oraculo registra tras aceptar la original.
    """
    lectura_id = f"E1-I-DUP-{indice:04d}"
    payload = dict(original.lectura)
    payload["lecturaId"] = lectura_id
    return CasoE1(
        lectura_id=lectura_id,
        valida=False,
        categoria=LECTURA_DUPLICADA,
        lectura=payload,
    )


def generar_dataset_e1(run_id: str, params: dict[str, Any] | None = None) -> DatasetE1:
    """Genera el dataset de E1 por semilla fija: 200 invalidas (>=50/categoria) + 200 validas.

    El orden de `casos` es el orden de inyeccion: cada duplicado aparece DESPUES de su valida
    de origen, para que el oraculo ya la haya aceptado y registrado la tupla (medidor, epoca).
    La misma (`run_id`, `params`) produce siempre el mismo dataset (R2.1, R7.4).
    """
    seed = derivar_semilla(run_id, params)
    rng = _Rng(seed)
    pares = _medidores_fuentes()

    # 200 validas unicas.
    validas = [_nueva_valida(rng, i, pares) for i in range(N_VALIDAS)]

    # Reparto de invalidas por categoria: >=50 por categoria, total exacto 200.
    # 67 valor_alterado + 67 medidor_desconocido + 66 duplicada = 200 (cada una >= 50).
    n_val = 67
    n_med = 67
    n_dup = N_INVALIDAS - n_val - n_med  # 66
    assert n_val >= MIN_POR_CATEGORIA and n_med >= MIN_POR_CATEGORIA and n_dup >= MIN_POR_CATEGORIA

    inval_valor = [_invalida_valor_alterado(rng, i, pares) for i in range(n_val)]
    inval_medidor = [_invalida_medidor_desconocido(rng, i) for i in range(n_med)]
    # Los duplicados se basan en las primeras `n_dup` validas (que se inyectan antes).
    inval_dup = [_invalida_duplicada(i, validas[i]) for i in range(n_dup)]

    # Orden de inyeccion determinista: primero validas, luego invalidas. Garantiza que cada
    # duplicado se inyecta despues de su valida de origen (R: deteccion de duplicados).
    casos: list[CasoE1] = []
    casos.extend(validas)
    # Intercalado determinista de las invalidas (no requiere azar; patron fijo por categoria).
    maximo = max(len(inval_valor), len(inval_medidor), len(inval_dup))
    for i in range(maximo):
        if i < len(inval_valor):
            casos.append(inval_valor[i])
        if i < len(inval_medidor):
            casos.append(inval_medidor[i])
        if i < len(inval_dup):
            casos.append(inval_dup[i])

    return DatasetE1(seed=seed, casos=tuple(casos))


# ---------------------------------------------------------------------------
# Inyeccion a ms_oraculo y medicion de latencia
# ---------------------------------------------------------------------------
@dataclass
class ResultadoInyeccion:
    """Resultado de inyectar un caso a ms_oraculo."""

    caso: CasoE1
    aceptada: bool
    categoria: str | None
    http_status: int
    latencia_s: float | None  # solo para validas aceptadas (LecturaRegistrada->GeneracionValidada)
    error: str | None = None


def _post_lectura(url: str, payload: dict[str, Any], timeout_s: float) -> tuple[int, dict[str, Any]]:
    """`POST {url}/lecturas` con el payload; devuelve (status, cuerpo_json)."""
    cuerpo = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{url}/lecturas",
        data=cuerpo,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        raw = resp.read()
        status = resp.getcode()
    try:
        return status, (json.loads(raw) if raw else {})
    except ValueError:
        return status, {}


def inyectar_caso(
    url_oraculo: str,
    caso: CasoE1,
    *,
    timeout_s: float = INDISPONIBILIDAD_TIMEOUT_S,
    reloj: Callable[[], float] = time.monotonic,
) -> ResultadoInyeccion:
    """Inyecta un caso a ms_oraculo midiendo la latencia LecturaRegistrada->GeneracionValidada.

    La latencia se mide solo para lecturas validas aceptadas: el oraculo solo responde
    `aceptada:true` tras publicar `GeneracionValidada` a ms_energia (flujo sincrono), por lo
    que el intervalo cubre el tramo R2.7. Si el oraculo responde 502 (emision no confirmada),
    la lectura no se cuenta como aceptada.

    Lanza `E1Error` si ms_oraculo no responde dentro de `timeout_s` (indisponibilidad, R2.9).
    """
    inicio = reloj()  # LecturaRegistrada
    try:
        status, cuerpo = _post_lectura(url_oraculo, caso.lectura, timeout_s)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise E1Error(
            f"ms_oraculo no respondio para {caso.lectura_id} dentro de {timeout_s} s: {exc}"
        ) from exc
    fin = reloj()  # GeneracionValidada (respuesta aceptada del oraculo)

    aceptada = bool(cuerpo.get("aceptada")) and status == 200
    categoria = cuerpo.get("categoria")
    latencia = (fin - inicio) if aceptada else None
    error = None
    if status == 502:
        # La lectura era valida pero la emision no se confirmo: no cuenta como aceptada (R5.10).
        error = str(cuerpo.get("detalle") or "emision_fallida")
    return ResultadoInyeccion(
        caso=caso,
        aceptada=aceptada,
        categoria=categoria,
        http_status=status,
        latencia_s=latencia,
        error=error,
    )


# ---------------------------------------------------------------------------
# Metricas
# ---------------------------------------------------------------------------
def percentil(valores: list[float], pct: float) -> float:
    """Percentil `pct` (0..100) por interpolacion lineal (metodo "linear" de numpy)."""
    if not valores:
        return 0.0
    ordenados = sorted(valores)
    if len(ordenados) == 1:
        return ordenados[0]
    rango = (pct / 100.0) * (len(ordenados) - 1)
    bajo = int(rango)
    alto = min(bajo + 1, len(ordenados) - 1)
    frac = rango - bajo
    return ordenados[bajo] + (ordenados[alto] - ordenados[bajo]) * frac


def emitidos_por_invalidas(
    eventos: Iterable[EventoOnChain], dataset: DatasetE1
) -> list[EventoOnChain]:
    """Eventos `Emitido` cuyo `lecturaId` corresponde a una lectura invalida del dataset (R2.6)."""
    bytes32_invalidas = {c.lectura_id_bytes32().lower() for c in dataset.invalidas}
    coincidencias: list[EventoOnChain] = []
    for ev in eventos:
        if ev.tipo != "Emitido":
            continue
        lid = _arg_lectura_id(ev.args)
        if lid is not None and lid.lower() in bytes32_invalidas:
            coincidencias.append(ev)
    return coincidencias


def _arg_lectura_id(args: dict[str, Any]) -> str | None:
    """Extrae el `lecturaId` (bytes32 hex) de los args de un evento `Emitido`, si existe."""
    for clave in ("lecturaId", "lectura_id", "lectura"):
        valor = args.get(clave)
        if isinstance(valor, str):
            return valor if valor.startswith("0x") else f"0x{valor}"
    return None


# ---------------------------------------------------------------------------
# Ejecucion de E1
# ---------------------------------------------------------------------------
def ejecutar_e1(
    run_id: str,
    url_oraculo: str,
    lector: LectorEventos,
    *,
    params: dict[str, Any] | None = None,
    from_block: int | str = 0,
    to_block: int | str = "latest",
    dataset: DatasetE1 | None = None,
    inyector: Callable[[str, CasoE1], ResultadoInyeccion] | None = None,
    reloj: Callable[[], float] = time.monotonic,
) -> ExperimentResult:
    """Ejecuta E1 de extremo a extremo y devuelve el `ExperimentResult` con veredicto (R2).

    * `run_id`: identificador de la corrida (semilla del dataset + trazado de eventos).
    * `url_oraculo`: URL base de `ms_oraculo` (p. ej. `http://localhost:8080`).
    * `lector`: `LectorEventos` ya configurado con el `ChainClient` de la corrida.
    * `dataset`: dataset precomputado (si None se genera con la semilla derivada).
    * `inyector`: inyectable para pruebas; por defecto hace el `POST /lecturas` real.
    * `from_block`/`to_block`: rango de bloques para la lectura de eventos (R6).

    Aborta con FAIL si la cadena o el oraculo no responden dentro del tope de 30 s (R2.9).
    """
    params = dict(params or {})
    resultado = ExperimentResult(
        experiment="E1",
        title="E1 — Integridad del Oracle",
        hypothesis="Ninguna lectura invalida llega a emitir tokens; las validas se emiten con p95<=10s.",
        started=now_iso(),
    )

    if dataset is None:
        dataset = generar_dataset_e1(run_id, params)

    conteo_cat = dataset.por_categoria()
    resultado.params.update(
        {
            "runId": run_id,
            "seed": dataset.seed,
            "invalidas": len(dataset.invalidas),
            "validas": len(dataset.validas),
            "porCategoria": conteo_cat,
            "umbralP95Segundos": P95_MAX_S,
            **params,
        }
    )

    _post = inyector or (lambda url, caso: inyectar_caso(url, caso, reloj=reloj))

    # --- Inyeccion de casos ---------------------------------------------------
    resultados: list[ResultadoInyeccion] = []
    try:
        for caso in dataset.casos:
            resultados.append(_post(url_oraculo, caso))
    except E1Error as exc:
        # Indisponibilidad de cadena/oraculo durante E1 -> abortar con FAIL (R2.9).
        resultado.error = f"indisponibilidad durante E1: {exc}"
        resultado.finished = now_iso()
        resultado.add(
            "R2.9",
            "Cadena/oraculo responden durante E1",
            ok=False,
            expected="responden dentro de 30 s",
            observed=str(exc),
        )
        return resultado

    # --- Metricas de rechazo (R2.5) ------------------------------------------
    invalidas_rechazadas = [r for r in resultados if (not r.caso.valida) and (not r.aceptada)]
    invalidas_aceptadas = [r for r in resultados if (not r.caso.valida) and r.aceptada]
    total_invalidas = len(dataset.invalidas)
    tasa_rechazo = (len(invalidas_rechazadas) / total_invalidas) if total_invalidas else 0.0

    # Validacion adicional: cada invalida fue rechazada con la categoria esperada.
    categoria_ok = all(
        r.categoria == r.caso.categoria for r in resultados if not r.caso.valida and not r.aceptada
    )

    # --- Latencias de validas (R2.7, R2.8) -----------------------------------
    validas_aceptadas = [r for r in resultados if r.caso.valida and r.aceptada]
    latencias = [r.latencia_s for r in validas_aceptadas if r.latencia_s is not None]
    p95 = percentil(latencias, 95.0)

    # --- Evidencia on-chain via Lector_Eventos (R2.6) ------------------------
    try:
        eventos = lector.leer_eventos(run_id, from_block=from_block, to_block=to_block)
    except LectorEventosError as exc:
        resultado.error = f"indisponibilidad de la cadena al leer eventos: {exc}"
        resultado.finished = now_iso()
        resultado.add(
            "R2.9",
            "Cadena responde a la lectura de eventos durante E1",
            ok=False,
            expected="responde dentro de 30 s",
            observed=str(exc),
        )
        return resultado

    emitidos_invalidas = emitidos_por_invalidas(eventos, dataset)
    n_emitidos_invalidas = len(emitidos_invalidas)
    emitidos_total = [ev for ev in eventos if ev.tipo == "Emitido"]

    # --- Criterios PASS/FAIL (R2.5, R2.6, R2.8, R2.10) -----------------------
    resultado.add(
        "R2.5",
        "Tasa de rechazo de lecturas invalidas",
        ok=(tasa_rechazo >= 1.0 and categoria_ok),
        expected="100% rechazadas (con categoria correcta)",
        observed=f"{tasa_rechazo * 100:.2f}% ({len(invalidas_rechazadas)}/{total_invalidas}); "
        f"categoria_correcta={categoria_ok}",
        invalidasAceptadas=[r.caso.lectura_id for r in invalidas_aceptadas],
    )
    resultado.add(
        "R2.6",
        "Tokens emitidos por lecturas invalidas",
        ok=(n_emitidos_invalidas == 0),
        expected="0 eventos Emitido por lecturas invalidas",
        observed=f"{n_emitidos_invalidas} eventos Emitido por invalidas",
        eventos=[ev.as_dict() for ev in emitidos_invalidas],
    )
    resultado.add(
        "R2.8",
        "Latencia p95 de lecturas validas",
        ok=(p95 <= P95_MAX_S),
        expected=f"p95 <= {P95_MAX_S} s",
        observed=f"p95={p95:.4f} s sobre {len(latencias)} validas aceptadas",
        umbralSegundos=P95_MAX_S,
        p95Segundos=round(p95, 6),
    )

    # --- Metricas y evidencia en data (R2.10, R7.3) --------------------------
    resultado.data.update(
        {
            "tasaRechazo": tasa_rechazo,
            "tasaRechazoPorcentaje": tasa_rechazo * 100,
            "invalidasRechazadas": len(invalidas_rechazadas),
            "invalidasAceptadas": len(invalidas_aceptadas),
            "tokensEmitidosPorInvalidas": n_emitidos_invalidas,
            "totalEventosEmitido": len(emitidos_total),
            "validasAceptadas": len(validas_aceptadas),
            "latenciaP95Segundos": p95,
            "latenciasSegundos": [round(l, 6) for l in latencias],
            "conteoPorCategoria": conteo_cat,
            "eventos": [ev.as_dict() for ev in eventos],
        }
    )

    resultado.finished = now_iso()
    logger.info(
        "E1 veredicto=%s tasaRechazo=%.2f%% emitidasInvalidas=%d p95=%.3fs",
        resultado.verdict,
        tasa_rechazo * 100,
        n_emitidos_invalidas,
        p95,
    )
    return resultado
